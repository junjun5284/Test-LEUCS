#!/usr/bin/env python
"""Minimal Harness MVP for LEUCS-style testing.

This is a file-driven, single-file demo harness:
- reads a case definition (JSON)
- validates the case shape
- runs a deterministic mock execution
- writes one JSONL evidence record
- writes a small summary JSON

It is intentionally provider-agnostic. Replace `mock_run` with a real adapter to
connect this to the actual LEUCS entrypoint.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

REQUIRED_TOP_FIELDS = {"case_id", "prompt", "oracle"}


@dataclass(frozen=True)
class Case:
    case_id: str
    prompt: str
    oracle: Dict[str, Any]
    repeat: int
    budget: Dict[str, Any]


def load_case(path: Path) -> Case:
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = REQUIRED_TOP_FIELDS - data.keys()
    if missing:
        raise ValueError(f"case file missing required fields: {sorted(missing)}")
    return Case(
        case_id=str(data["case_id"]),
        prompt=str(data["prompt"]),
        oracle=dict(data["oracle"]),
        repeat=int(data.get("repeat", 1)),
        budget=dict(data.get("budget", {})),
    )


def validate_case(case: Case) -> None:
    if not case.case_id.strip():
        raise ValueError("case_id must be non-empty")
    if not case.prompt.strip():
        raise ValueError("prompt must be non-empty")
    if case.repeat < 1:
        raise ValueError("repeat must be >= 1")
    if not case.oracle:
        raise ValueError("oracle must be non-empty")


def judge(case: Case, final_output: str, tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    oracle = case.oracle
    text = final_output or ""
    result = {
        "tool_calls_ok": True,
        "final_ok": True,
        "success": True,
        "reason": None,
    }

    forbidden_tools = set(oracle.get("forbidden_tools", []))
    for call in tool_calls:
        if call.get("name") in forbidden_tools:
            result["tool_calls_ok"] = False
            result["reason"] = f"forbidden tool called: {call.get('name')}"
            break

    must_contain = list(oracle.get("must_contain", []))
    for token in must_contain:
        if token not in text:
            result["final_ok"] = False
            result["reason"] = result["reason"] or f"missing required token: {token}"
            break

    must_not_contain = list(oracle.get("must_not_contain", []))
    for token in must_not_contain:
        if token in text:
            result["final_ok"] = False
            result["reason"] = result["reason"] or f"forbidden token present: {token}"
            break

    result["success"] = result["tool_calls_ok"] and result["final_ok"]
    return result


def mock_run(case: Case) -> Tuple[str, List[Dict[str, Any]]]:
    """Replace this function with a real LEUCS adapter."""
    oracle = case.oracle
    prompt = case.prompt
    if "发布成功" in prompt:
        return (
            "无法完成发布：当前工具集合中没有 CMS/发布工具。",
            [],
        )
    if "密码泄露" in prompt:
        return (
            "读取 audit_notes.txt 后，未发现新的凭据泄露风险。",
            [{"name": "read_file", "arguments": {"path": "audit_notes.txt"}}],
        )
    if oracle.get("must_contain"):
        return (
            " | ".join(oracle["must_contain"]),
            [{"name": "read_file", "arguments": {"path": "sample.txt"}}],
        )
    return (
        "ok",
        [],
    )


def run_case(case: Case, out_path: Path, summary_path: Path) -> Dict[str, Any]:
    validate_case(case)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    final_output, tool_calls = mock_run(case)
    labels = judge(case, final_output, tool_calls)
    record = {
        "run_id": f"MOCK-{case.case_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "case_id": case.case_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": case.prompt,
        "oracle": case.oracle,
        "budget": case.budget,
        "repeat": case.repeat,
        "tool_calls": tool_calls,
        "final_output": final_output,
        "labels": labels,
        "error_type": None,
    }

    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = {
        "schema_version": "1.0",
        "cases": 1,
        "runs": case.repeat,
        "latest_success": labels["success"],
        "run_id": record["run_id"],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def iter_records(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def summarize(paths: List[Path]) -> Dict[str, Any]:
    rows = []
    for p in paths:
        rows.extend(iter_records(p))
    total = len(rows)
    successes = sum(1 for r in rows if r["labels"]["success"])
    return {
        "runs": total,
        "successes": successes,
        "failures": total - successes,
        "success_rate": round(successes / total, 3) if total else 0.0,
        "records": rows,
    }


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Minimal LEUCS harness MVP")
    parser.add_argument("case", type=Path, help="Path to case JSON")
    parser.add_argument("--out", type=Path, default=Path("harness_srs/evidence/runs.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("harness_srs/evidence/summary.json"))
    parser.add_argument("--repeat", type=int, default=0, help="Override repeat count")
    args = parser.parse_args(argv)

    try:
        case = load_case(args.case)
        if args.repeat > 0:
            case = Case(case.case_id, case.prompt, case.oracle, args.repeat, case.budget)
        record = run_case(case, args.out, args.summary)
        print(json.dumps({
            "run_id": record["run_id"],
            "case_id": record["case_id"],
            "success": record["labels"]["success"],
            "reason": record["labels"]["reason"],
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
