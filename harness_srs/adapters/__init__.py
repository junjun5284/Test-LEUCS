"""LEUCS adapter: teaches the generic core how to drive the LEUCS platform.

This is the ONLY module that knows about LEUCS specifics (endpoints, SSE event
names, approval flow, mount semantics). The generic core in
``harness_srs/core`` knows nothing about LEUCS.

Credentials come only from environment variables:
  LEUCS_PLATFORM_BASE    e.g. https://123.57.180.120
  LEUCS_PLATFORM_TOKEN   bearer token from the browser session
"""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import os
import sys
from pathlib import Path

_HARNESS_ROOT = Path(__file__).resolve().parents[1]
if str(_HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(_HARNESS_ROOT))

from core import AdapterSpec, EvidenceStore, register_adapter  # noqa: E402

DEFAULT_BASE = "https://123.57.180.120"
QUERY_ONLY_TOOLS = {"tool_lookup", "tool_check", "get_helper", "env_info", "env_prober"}
EXECUTION_TOOLS = ("run_command", "exec", "python_exec", "run_python", "shell")
HARNESS_ROOT = _HARNESS_ROOT


class BudgetExceededError(RuntimeError):
    pass


def _ctx(insecure: bool = True):
    return ssl._create_unverified_context() if insecure else ssl.create_default_context()


def _redact(text: str, token: str) -> str:
    return text.replace(token, "[token redacted]") if token else text


class LeucsAdapter:
    """Adapter for the LEUCS web platform."""

    name = "leucs"

    def __init__(
        self,
        base: str = "",
        token: str = "",
        cases_dir: Optional[Path] = None,
        evidence_dir: Optional[Path] = None,
        timeout: float = 30.0,
        run_timeout: float = 120.0,
        insecure: bool = True,
        decision: str = "none",
        task_name: str = "leucs_main",
        temperature: float = 0.7,
        use_mount: bool = False,
    ):
        self.base = base or os.environ.get("LEUCS_PLATFORM_BASE", DEFAULT_BASE)
        self.token = token or os.environ.get("LEUCS_PLATFORM_TOKEN", "")
        self.cases_dir = Path(cases_dir) if cases_dir else HARNESS_ROOT / "platform_cases"
        self.evidence_dir = Path(evidence_dir) if evidence_dir else HARNESS_ROOT / "evidence"
        self.timeout = timeout
        self.run_timeout = run_timeout
        self.insecure = insecure
        self.decision = decision
        self.task_name = task_name
        self.temperature = temperature
        self.use_mount = use_mount
        self._mount_conv: Optional[str] = None
        self._counter = 0

    # ------------------------------------------------------------------ #
    # generic adapter interface
    # ------------------------------------------------------------------ #

    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "base": self.base,
            "cases_dir": str(self.cases_dir),
            "evidence_dir": str(self.evidence_dir),
            "decision_policy": self.decision,
            "use_mount": self.use_mount,
            "authenticated": bool(self.token),
            "endpoints": [
                "GET  /api/leucs/health",
                "GET  /api/leucs/conversations",
                "GET  /api/leucs/conversation/{id}",
                "GET  /api/leucs/conversation/{id}/events",
                "GET  /api/lei-bit/accounts/feed?after=N",
                "POST /api/lei-bit/chat            (run, SSE)",
                "POST /api/leucs/decision          (approval)",
                "GET  /api/leucs/mount/status",
                "GET  /api/leucs/mount/policy",
            ],
        }

    def list_cases(self) -> List[Dict[str, Any]]:
        if not self.cases_dir.is_dir():
            return []
        cases = []
        for path in sorted(self.cases_dir.glob("*.json")):
            try:
                cases.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return cases

    def list_runs(self) -> List[Dict[str, Any]]:
        store = EvidenceStore(self.evidence_dir / "platform_runs.jsonl")
        return store.runs(kinds=["suite_run", "run"])

    def run_case(self, case: Dict[str, Any], repetition: int) -> Dict[str, Any]:
        if case.get("requires_mount"):
            if not self.use_mount:
                return self._skipped(case, "requires_mount but use_mount is disabled")
            if not self._mount_conv:
                self._mount_conv = self.resolve_mount_conversation()
            if not self._mount_conv:
                return self._skipped(case, "no browser mount is attached")
            target = self._mount_conv
        else:
            target = ""

        if case.get("follow_up"):
            first = self._chat(case["message"], "", 1)
            conv = first.get("conv_id") or ""
            result = self._chat(case["follow_up"], conv, 2)
            result["continued_in_same_conversation"] = bool(conv) and result.get("conv_id") == conv
            result["first_turn"] = {
                "conv_id": conv,
                "final_answer": first.get("final_answer", ""),
                "error_type": first.get("error_type"),
            }
        else:
            result = self._chat(case["message"], target, 1)
        result["case_id"] = case.get("case_id")
        result["rep"] = repetition
        if case.get("requires_mount"):
            result["mount_conversation_id"] = self._mount_conv
            result["ran_in_mounted_conversation"] = result.get("conv_id") == self._mount_conv
        return result

    # ------------------------------------------------------------------ #
    # LEUCS specifics
    # ------------------------------------------------------------------ #

    def _skipped(self, case: Dict[str, Any], reason: str) -> Dict[str, Any]:
        return {
            "run_id": f"SKIP-{case.get('case_id')}-{datetime.now(timezone.utc).strftime('%H%M%S')}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "final_answer": "",
            "tool_calls": [],
            "tool_names": [],
            "error_type": "skipped",
            "error": reason,
            "usage": {},
            "elapsed_seconds": 0.0,
            "events_file": None,
            "skipped": True,
            "skip_reason": reason,
        }

    def _request(self, path: str, method: str = "GET", body: Optional[Dict[str, Any]] = None,
                 timeout: Optional[float] = None) -> Dict[str, Any]:
        url = self.base.rstrip("/") + path
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"authorization": "Bearer " + self.token, "accept": "application/json"}
        if data is not None:
            headers["content-type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        started = time.time()
        status: Any = None
        payload = b""
        error = None
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout, context=_ctx(self.insecure)) as resp:
                status = resp.status
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload = exc.read()
            error = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        return {
            "status": status,
            "error": error,
            "elapsed_seconds": round(time.time() - started, 2),
            "text": _redact(payload.decode("utf-8", "replace"), self.token),
        }

    def resolve_mount_conversation(self) -> Optional[str]:
        """The browser mount binds to exactly one conversation."""
        data = self._request("/api/leucs/mount/status")
        try:
            payload = json.loads(data["text"])
        except json.JSONDecodeError:
            return None
        ids = [m.get("conv_id") for m in (payload.get("mounts") or []) if m.get("conv_id")]
        return ids[0] if ids else None

    def read_mount_contract(self) -> Dict[str, Any]:
        status = self._request("/api/leucs/mount/status")
        policy = self._request("/api/leucs/mount/policy")
        def parse(t: str) -> Dict[str, Any]:
            try:
                return json.loads(t)
            except json.JSONDecodeError:
                return {}
        st, pol = parse(status["text"]), parse(policy["text"])
        mounts = st.get("mounts") or []
        contract: Dict[str, Any] = {
            "online": st.get("online"),
            "mount_count": len(mounts),
            "policy": pol.get("policy") or {},
            "mounted_conversation_ids": [m.get("conv_id") for m in mounts if m.get("conv_id")],
        }
        if mounts:
            m = mounts[0]
            caps = m.get("caps") or {}
            tools = caps.get("tools") or []
            contract.update({
                "device_class": m.get("device_class"),
                "executor_kind": m.get("executor_kind"),
                "worker": caps.get("worker"),
                "fs_access": caps.get("fs_access"),
                "tools": tools,
                "tool_count": len(tools),
                "has_execution_tool": any(t in tools for t in EXECUTION_TOOLS),
                "conv_id": m.get("conv_id"),
            })
        return contract

    def _post_decision(self, conv_id: str, choice: str) -> Dict[str, Any]:
        res = self._request("/api/leucs/decision", "POST",
                            {"choice": choice, "conversation_id": conv_id})
        return {"choice": choice, "status": res["status"], "error": res["error"]}

    def _chat(self, message: str, conversation_id: str, turn_index: int) -> Dict[str, Any]:
        from http.client import HTTPSConnection

        turn_id = str(uuid.uuid4())
        body = {
            "message": message,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "turn_index": turn_index,
            "task_name": self.task_name,
            "temperature": self.temperature,
        }
        host = self.base.split("://", 1)[-1].split("/", 1)[0]
        started = time.time()
        events: List[Dict[str, Any]] = []
        status: Any = None
        conv_id = conversation_id
        error = None
        buffer = ""
        decisions: List[Dict[str, Any]] = []
        decision_actions: List[Dict[str, Any]] = []
        handled = set()
        try:
            conn = HTTPSConnection(host, 443, context=_ctx(self.insecure), timeout=self.run_timeout)
            conn.request("POST", "/api/lei-bit/chat",
                         body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                         headers={"Authorization": "Bearer " + self.token,
                                  "Content-Type": "application/json",
                                  "Accept": "text/event-stream"})
            resp = conn.getresponse()
            status = resp.status
            conv_id = resp.getheader("x-leucs-conversation-id") or conversation_id
            deadline = time.time() + self.run_timeout
            timed_out = False
            while time.time() < deadline:
                chunk = resp.read1(8192)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", "replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw in ("", "[DONE]"):
                        continue
                    try:
                        ev = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    events.append(ev)
                    if ev.get("type") == "decision" and self.decision in ("approve", "deny"):
                        did = str(ev.get("decision_id") or "")
                        if did and did not in handled:
                            handled.add(did)
                            action = self._post_decision(conv_id, self.decision)
                            action["decision_id"] = did
                            action["tool_name"] = ev.get("tool_name")
                            decision_actions.append(action)
            else:
                timed_out = True
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            timed_out = False

        elapsed = round(time.time() - started, 2)
        final_answer = ""
        usage: Dict[str, Any] = {}
        stop_reason = ""
        stop_detail = ""
        api_error = ""
        contract_rejected = 0
        for ev in events:
            etype = ev.get("type")
            if etype == "final_answer":
                final_answer = str(ev.get("content") or "")
            elif etype == "done":
                usage = ev.get("usage") or {}
                stop_reason = str(ev.get("stop_reason") or "")
                stop_detail = str(ev.get("stop_detail") or "")
            elif etype == "decision":
                decisions.append({"decision_id": ev.get("decision_id"),
                                  "decision_type": ev.get("decision_type"),
                                  "tool_name": ev.get("tool_name"),
                                  "content": str(ev.get("content") or "")[:200]})
            elif etype == "classification_contract_rejected":
                contract_rejected += 1
            if ev.get("is_error"):
                api_error = str(ev.get("content") or "")[:300]

        tool_calls = []
        for ev in events:
            if ev.get("type") == "tool_call":
                raw = ev.get("arguments")
                text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
                tool_calls.append({"name": str(ev.get("tool_name") or ""), "arguments": text[:300]})
        tool_names = [c["name"] for c in tool_calls]

        query_counts = Counter(n for n in tool_names if n in QUERY_ONLY_TOOLS)
        action_calls = [n for n in tool_names if n not in QUERY_ONLY_TOOLS]
        max_same = max(Counter(tool_names).values()) if tool_names else 0
        discovery_loop = bool(tool_names and not action_calls and sum(query_counts.values()) >= 10) or max_same >= 20

        http_status = status if isinstance(status, int) else None
        contract_text = (stop_detail or "") + " " + (api_error or "")
        error_type = None
        if http_status is not None and http_status != 200:
            error_type = "infrastructure_error"
        elif error and not events:
            error_type = "infrastructure_error"
        elif decisions and not decision_actions:
            error_type = "awaiting_approval"
        elif contract_rejected:
            error_type = "classification_rejected"
        elif "response_contract" in contract_text or "THINK_EMPTY" in contract_text:
            error_type = "model_contract_error"
        elif "api_error" in (api_error or ""):
            error_type = "infrastructure_error"
        elif discovery_loop:
            error_type = "tool_discovery_loop"
        elif timed_out:
            error_type = "timeout"
        elif stop_reason == "error":
            error_type = "agent_failure"
        elif not final_answer:
            error_type = "incomplete_stream"

        self._counter += 1
        run_id = f"LEUCS-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{self._counter:04d}"
        events_file = self._save_events(run_id, events)
        return {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "final_answer": _redact(final_answer, self.token),
            "tool_calls": tool_calls,
            "tool_names": tool_names,
            "error_type": error_type,
            "error": error,
            "usage": usage,
            "elapsed_seconds": elapsed,
            "events_file": events_file,
            "event_count": len(events),
            "event_types": dict(Counter(str(e.get("type") or "?") for e in events)),
            "conv_id": conv_id,
            "turn_id": turn_id,
            "stop_reason": stop_reason,
            "stop_detail": _redact(stop_detail, self.token),
            "decisions": decisions,
            "decision_actions": decision_actions,
            "discovery_detail": {
                "query_only_calls": dict(query_counts),
                "action_calls": action_calls,
                "max_same_tool_calls": max_same,
                "tool_call_total": len(tool_names),
            },
        }

    def _save_events(self, run_id: str, events: List[Dict[str, Any]]) -> Optional[str]:
        if not events:
            return None
        directory = self.evidence_dir / "platform_events"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{run_id}.json"
        safe = json.loads(_redact(json.dumps(events, ensure_ascii=False), self.token))
        path.write_text(json.dumps(safe, ensure_ascii=False, indent=1), encoding="utf-8")
        return str(path)


def _factory(**kwargs) -> LeucsAdapter:
    return LeucsAdapter(**kwargs)


register_adapter(AdapterSpec(
    name="leucs",
    factory=_factory,
    description="LEUCS 智能体平台（网站 API + SSE 事件流）",
    requires=["LEUCS_PLATFORM_BASE", "LEUCS_PLATFORM_TOKEN"],
    options=["base", "token", "cases_dir", "evidence_dir", "timeout", "run_timeout",
             "insecure", "decision", "task_name", "temperature", "use_mount"],
))
