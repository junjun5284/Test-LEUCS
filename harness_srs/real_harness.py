#!/usr/bin/env python
"""Real-adapter Harness runner for LEUCS.

Runs a case definition against the real LEUCS AgentLoop + ChatProvider + ToolRegistry.

Credentials are read only from environment variables:
  STUDENT_AGENT_API_KEY
  LEUCS_BASE_URL
  LEUCS_MODEL
Optional sampling overrides:
  LEUCS_TEMPERATURE
  LEUCS_TOP_P
  LEUCS_MAX_TOKENS

Usage:
  python harness_srs/real_harness.py harness_srs/cases_real/sample_publish_real.json --out harness_srs/evidence/runs.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "leucs_agent" / "leucs_agent"))
sys.path.insert(0, str(ROOT / "leucs_agent" / "leucs_agent" / "src"))

from leucs_agent.core.agent_loop import AgentLoop  # type: ignore
from leucs_agent.plugins.api import PluginError  # type: ignore
from leucs_agent.providers.chat_completions import ChatProvider, ProviderError  # type: ignore
from leucs_agent.tools.registry import ActionPlugin, ToolRegistry  # type: ignore

FAILURE_PHRASES = ("失败", "无法", "错误", "未能", "failed", "error", "不能")


@dataclass(frozen=True)
class Case:
    case_id: str
    prompt: str
    expected: Dict[str, Any]
    tool_names: List[str]
    workspace_files: Dict[str, str]
    custom_tools: List[Dict[str, Any]]
    repeat: int
    limits: Dict[str, Any]
    prompt_file: Optional[str] = None


class BudgetExceededError(RuntimeError):
    pass


class SamplingChatProvider(ChatProvider):
    def __init__(self, base_url: str, model: str, key: str, *, timeout: float,
                 temperature: float, top_p: float, max_tokens: int):
        super().__init__(base_url, model, key, timeout=timeout)
        self.sampling = {"temperature": temperature, "top_p": top_p, "max_tokens": max_tokens}

    def request_json(self, path: str, body: dict, headers: dict) -> dict:
        return super().request_json(path, {**body, **self.sampling}, headers)


class BoundedProvider:
    def __init__(self, provider, max_model_requests: int, provider_timeout_seconds: float):
        self._provider = provider
        self.max_model_requests = max_model_requests
        self.count = 0
        self.terminated_by: Optional[str] = None

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        if self.count >= self.max_model_requests:
            self.terminated_by = "model_request_limit"
            raise BudgetExceededError(f"model request budget exceeded ({self.max_model_requests})")
        self.count += 1
        return self._provider.complete(messages, tools)

    def redact(self, text: str) -> str:
        return self._provider.redact(text)

    @property
    def timeout(self) -> float:
        return getattr(self._provider, "timeout", 120)


class BoundedTools:
    def __init__(self, registry, max_tool_calls: int, allow_names: set[str]):
        self._registry = registry
        self.max_tool_calls = max_tool_calls
        self.count = 0
        self.terminated_by: Optional[str] = None
        self.calls: List[Dict[str, Any]] = []
        self.allow_names = allow_names

    def invoke(self, name: str, arguments: dict) -> dict:
        if self.count >= self.max_tool_calls:
            self.terminated_by = "tool_call_limit"
            raise BudgetExceededError(f"tool call budget exceeded ({self.max_tool_calls})")
        if name not in self.allow_names:
            raise PluginError(f"tool not allowed for this case: {name}")
        self.count += 1
        entry: Dict[str, Any] = {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False, sort_keys=True)}
        try:
            result = self._registry.invoke(name, arguments)
        except Exception as exc:
            entry["ok"] = False
            entry["error"] = str(exc)[:300]
            self.calls.append(entry)
            raise
        entry["ok"] = result.get("exit_code", 0) == 0
        entry["result_sha256"] = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        entry["summary"] = json.dumps(result, ensure_ascii=False)[:300]
        self.calls.append(entry)
        return result

    def __getattr__(self, item):
        return getattr(self._registry, item)


def load_case(path: Path) -> Case:
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = {"case_id", "prompt", "expected", "tool_names"} - data.keys()
    if missing:
        raise ValueError(f"case file missing required fields: {sorted(missing)}")
    return Case(
        case_id=str(data["case_id"]),
        prompt=str(data["prompt"]),
        expected=dict(data["expected"]),
        tool_names=list(data.get("tool_names", [])),
        workspace_files=dict(data.get("workspace_files", {})),
        custom_tools=list(data.get("custom_tools", [])),
        repeat=int(data.get("repeat", 1)),
        limits=dict(data.get("limits", {})),
        prompt_file=data.get("prompt_file"),
    )


def validate_case(case: Case) -> None:
    if not case.case_id.strip():
        raise ValueError("case_id must be non-empty")
    if not case.prompt.strip():
        raise ValueError("prompt must be non-empty")
    if case.repeat < 1:
        raise ValueError("repeat must be >= 1")
    if not isinstance(case.expected, dict):
        raise ValueError("expected must be a JSON object")


def materialize_workspace(case: Case, root: Path) -> Dict[str, str]:
    written = {}
    for rel, content in case.workspace_files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written[rel] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return written


def build_tools(case: Case, root: Path) -> ToolRegistry:
    registry = ToolRegistry(root)
    allow_names = set(case.tool_names)
    for tool in registry.schemas():
        name = tool["function"]["name"]
        if name not in allow_names:
            registry.host.unregister(name)
            registry._tools.pop(name, None)
    for tool in case.custom_tools:
        if tool["name"] not in allow_names:
            continue
        static_result = tool.get("static_result")
        if static_result is None:
            raise ValueError(f"custom tool {tool['name']} requires static_result")
        action = lambda result=static_result: lambda **_kwargs: dict(result)
        registry.register(ActionPlugin(
            tool["name"],
            str(tool.get("description", "")),
            dict(tool.get("properties", {})),
            tuple(tool.get("required", [])),
            action,
        ))
    return registry


def judge(case: Case, calls: List[Dict[str, Any]], final_text: str) -> Dict[str, Any]:
    expected = case.expected
    text = final_text or ""
    names = [c["name"] for c in calls]
    allowed = set(expected.get("allowed_tools", case.tool_names))
    forbidden = set(expected.get("forbidden_tools", []))

    forbidden_called = [n for n in names if n in forbidden]
    tool_choice_correct = not forbidden_called and all(n in allowed for n in names)
    tool_need_correct = len(names) > 0 if expected.get("tool_required") else True
    arguments_correct = True
    result_used_correctly = True
    failure_honest = True
    unnecessary_call = False

    repeated = False
    prev_failed_sig: Optional[str] = None
    for call in calls:
        sig = call["name"] + ":" + call["arguments"]
        if prev_failed_sig is not None and sig == prev_failed_sig:
            repeated = True
        prev_failed_sig = None if call.get("ok") else sig
    if repeated:
        arguments_correct = False
        unnecessary_call = True

    must = list(expected.get("must_contain", []))
    any_groups = expected.get("must_contain_any", [])
    must_not = set(expected.get("must_not_contain", []))
    for token in must:
        if token not in text:
            result_used_correctly = False
            break
    for group in any_groups:
        if not any(token in text for token in group):
            result_used_correctly = False
            break
    for token in must_not:
        if token in text:
            result_used_correctly = False
            break

    failed_calls = [c for c in calls if not c.get("ok", True)]
    if failed_calls:
        failure_honest = any(p in text for p in FAILURE_PHRASES)

    task_success = (
        tool_need_correct and tool_choice_correct and arguments_correct
        and result_used_correctly and failure_honest and not unnecessary_call
    )
    return {
        "tool_need_correct": tool_need_correct,
        "tool_choice_correct": tool_choice_correct,
        "arguments_correct": arguments_correct,
        "result_used_correctly": result_used_correctly,
        "failure_honest": failure_honest,
        "unnecessary_call": unnecessary_call,
        "task_success": task_success,
    }


def build_provider(cfg: Dict[str, Any]):
    return SamplingChatProvider(
        cfg["base_url"], cfg["model"], cfg["api_key"],
        timeout=float(cfg["provider_timeout_seconds"]),
        temperature=float(cfg["temperature"]),
        top_p=float(cfg["top_p"]),
        max_tokens=int(cfg["max_tokens"]),
    )


def run_case_real(case: Case, cfg: Dict[str, Any], out_path: Path, summary_path: Path) -> Dict[str, Any]:
    validate_case(case)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    limits = {
        "max_model_requests": int(case.limits.get("max_model_requests", 8)),
        "max_tool_calls": int(case.limits.get("max_tool_calls", 6)),
        "provider_timeout_seconds": int(case.limits.get("provider_timeout_seconds", 120)),
        "total_timeout_seconds": int(case.limits.get("total_timeout_seconds", 300)),
    }

    with tempfile.TemporaryDirectory(prefix="real_harness_") as directory:
        root = Path(directory)
        written = materialize_workspace(case, root)
        registry = build_tools(case, root)
        provider = build_provider(cfg)
        bounded_provider = BoundedProvider(provider, limits["max_model_requests"], limits["provider_timeout_seconds"])
        bounded_tools = BoundedTools(registry, limits["max_tool_calls"], set(case.tool_names))
        agent = AgentLoop(bounded_provider, bounded_tools)

        prompt = case.prompt
        if case.prompt_file:
            prompt_path = ROOT / case.prompt_file
            prompt = prompt_path.read_text(encoding="utf-8")
        agent.messages[0]["content"] = prompt
        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

        final_output: Optional[str] = None
        error_type = None
        detail = None
        terminated_by: Optional[str] = None
        try:
            final_output = agent.run(case.prompt)
        except BudgetExceededError as exc:
            error_type = "budget_exceeded"
            detail = str(exc)
            terminated_by = "budget_exceeded"
        except ProviderError as exc:
            error_type = "infrastructure_error"
            detail = str(exc)
        except PluginError as exc:
            error_type = "agent_failure"
            detail = f"plugin error: {exc}"
        except Exception as exc:
            error_type = "agent_failure"
            detail = f"{type(exc).__name__}: {exc}"

        elapsed = round(time.time() - started, 2)
        terminated_by = terminated_by or bounded_provider.terminated_by or bounded_tools.terminated_by
        final_output = provider.redact(final_output or "") if final_output is not None else ""
        labels = judge(case, bounded_tools.calls, final_output)
        if error_type == "budget_exceeded":
            labels["task_success"] = False

        record = {
            "run_id": f"REAL-{case.case_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "case_id": case.case_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_config": {
                "model": cfg["model"],
                "temperature": cfg["temperature"],
                "top_p": cfg["top_p"],
                "max_tokens": cfg["max_tokens"],
                "seed_support": False,
            },
            "prompt": case.prompt,
            "prompt_sha256": prompt_sha,
            "tool_names": case.tool_names,
            "workspace_files_sha256": written,
            "tool_calls": bounded_tools.calls,
            "final_output": final_output,
            "labels": labels,
            "error_type": error_type,
            "notes": detail or "ok",
            "limits": limits,
            "usage": {
                "model_request_count": bounded_provider.count,
                "tool_call_count": bounded_tools.count,
                "elapsed_seconds": elapsed,
                "terminated_by": terminated_by,
            },
        }
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = {
        "schema_version": "1.0",
        "mode": "real",
        "case_id": case.case_id,
        "runs": 1,
        "success": labels["task_success"],
        "run_id": record["run_id"],
        "error_type": error_type,
        "usage": record["usage"],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def load_cases(target: Path) -> List[Case]:
    if target.is_dir():
        files = sorted(p for p in target.glob("*.json"))
        if not files:
            raise ValueError(f"no case JSON files found in {target}")
        return [load_case(p) for p in files]
    return [load_case(target)]


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Real LEUCS Harness runner")
    parser.add_argument("cases", type=Path, help="Path to a single case JSON or a directory of case JSON files")
    parser.add_argument("--out", type=Path, default=Path("harness_srs/evidence/runs_real.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("harness_srs/evidence/summary_real.json"))
    parser.add_argument("--repeat", type=int, default=0, help="Override per-case repeat count; 0 = use case value")
    args = parser.parse_args(argv)

    api_key = os.environ.get("STUDENT_AGENT_API_KEY", "")
    base_url = os.environ.get("LEUCS_BASE_URL", "")
    model = os.environ.get("LEUCS_MODEL", "")
    if not (api_key and base_url and model):
        print("ERROR: set STUDENT_AGENT_API_KEY, LEUCS_BASE_URL and LEUCS_MODEL first.", file=sys.stderr)
        return 2

    cfg = {
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "temperature": float(os.environ.get("LEUCS_TEMPERATURE", "0.7")),
        "top_p": float(os.environ.get("LEUCS_TOP_P", "1.0")),
        "max_tokens": int(os.environ.get("LEUCS_MAX_TOKENS", "1024")),
        "provider_timeout_seconds": 120,
    }

    try:
        cases = load_cases(args.cases)
        for case in cases:
            run_case_real(case, cfg, args.out, args.summary)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
