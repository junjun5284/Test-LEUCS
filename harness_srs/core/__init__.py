"""Generic, target-agnostic core of the test Harness.

Everything platform-specific lives in an *adapter*; this package only knows
about cases, runs, verdicts, evidence and reporting.

Contract for an adapter
-----------------------
An adapter is any object exposing:

    name: str
    def describe(self) -> dict          # optional metadata (endpoints, notes)
    def list_cases(self) -> list[dict]  # case definitions (schema below)
    def run_case(self, case, repetition) -> dict   # execute one repetition
    def list_runs(self) -> list[dict]   # historical run records

Case schema
-----------
{
  "case_id":     str,
  "title":      str,
  "category":   str,
  "message":    str,             # the task handed to the system under test
  "repeat":     int,             # default repetitions
  "oracle": {                    # mechanical expectations, evaluated by core
     "expect_final_answer_contains": [str],
     "must_not_contain":           [str],
     "refusal_any":                [str],
     "forbidden_tools":            [str],
     "must_call_any":              [str],
     "expect_no_error":            bool,
  },
}

Run record schema (what an adapter must return from run_case)
-----------------------------------------------------------
{
  "run_id": str, "case_id": str, "timestamp": str,
  "final_answer": str, "tool_calls": [{"name","arguments"}],
  "tool_names": [str], "error_type": str|None, "error": str|None,
  "usage": dict, "elapsed_seconds": float, "events_file": str|None,
  ... any adapter-specific extra fields are preserved verbatim
}

This module deliberately contains no HTTP calls, no model calls and no
knowledge of any particular agent platform.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# --------------------------------------------------------------------------- #
# text matching (FR-22): ASCII tokens need word boundaries, CJK does not
# --------------------------------------------------------------------------- #

def contains_token(text: str, token: str) -> bool:
    """Token presence with word-boundary awareness for ASCII tokens.

    "okay" must not satisfy an expectation of "ok"; "not ok" legitimately
    contains the word "ok" because a space is a valid boundary. CJK tokens keep
    plain substring semantics because Chinese has no word separators.
    """
    if not token:
        return False
    if token.isascii() and any(ch.isalnum() for ch in token):
        pattern = r"(?<![0-9A-Za-z_])" + re.escape(token) + r"(?![0-9A-Za-z_])"
        return re.search(pattern, text) is not None
    return token in text


# --------------------------------------------------------------------------- #
# oracle evaluation
# --------------------------------------------------------------------------- #

def judge(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate one run against its case oracle. Pure function."""
    oracle = case.get("oracle") or {}
    final = result.get("final_answer") or ""
    tool_names = result.get("tool_names") or []
    checks: Dict[str, bool] = {"answer_present": bool(final.strip())}

    if oracle.get("expect_final_answer_contains"):
        checks["contains"] = all(contains_token(final, t) for t in oracle["expect_final_answer_contains"])
    if oracle.get("must_not_contain"):
        checks["no_forbidden"] = not any(contains_token(final, t) for t in oracle["must_not_contain"])
    if oracle.get("refusal_any"):
        checks["refusal"] = any(contains_token(final, t) for t in oracle["refusal_any"])
    if oracle.get("forbidden_tools"):
        checks["no_forbidden_tool"] = not any(name in oracle["forbidden_tools"] for name in tool_names)
    if oracle.get("must_call_any"):
        checks["must_call_tool"] = any(name in oracle["must_call_any"] for name in tool_names)
    if oracle.get("expect_no_error"):
        checks["no_error"] = result.get("error_type") is None

    success = all(checks.values()) and result.get("error_type") is None
    return {"success": success, "checks": checks, "tool_names": tool_names}


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #

def is_success(record: Dict[str, Any]) -> bool:
    """Whether a run passed.

    Newer records carry a top-level ``success``; older ones only have it inside
    ``judgement``. Both shapes are accepted so historical evidence stays usable.
    """
    if "success" in record:
        return bool(record["success"])
    judgement = record.get("judgement") or {}
    return bool(judgement.get("success"))


def aggregate(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Roll per-run verdicts up to per-case and total statistics."""
    by_case: Dict[str, Dict[str, Any]] = {}
    error_types: Dict[str, int] = {}
    rows = list(rows)
    for r in rows:
        agg = by_case.setdefault(r.get("case_id") or "?", {"n": 0, "success": 0, "elapsed": []})
        agg["n"] += 1
        if is_success(r):
            agg["success"] += 1
        key = r.get("error_type") or "ok"
        error_types[key] = error_types.get(key, 0) + 1
        agg["elapsed"].append(r.get("elapsed_seconds") or 0)
    for agg in by_case.values():
        agg["success_rate"] = round(agg["success"] / agg["n"], 3) if agg["n"] else 0.0
        agg["avg_elapsed_seconds"] = round(sum(agg["elapsed"]) / len(agg["elapsed"]), 2) if agg["elapsed"] else 0.0
        del agg["elapsed"]
    total = len(rows)
    success = sum(1 for r in rows if is_success(r))
    return {
        "schema_version": "1.0",
        "totals": {
            "runs": total,
            "success": success,
            "success_rate": round(success / total, 3) if total else 0.0,
            "error_type_distribution": dict(sorted(error_types.items(), key=lambda kv: -kv[1])),
        },
        "by_case": by_case,
    }


# --------------------------------------------------------------------------- #
# adapter registry
# --------------------------------------------------------------------------- #

@dataclass
class AdapterSpec:
    """Describes how to obtain an adapter instance."""
    name: str
    factory: Any                      # callable(**kwargs) -> adapter
    description: str = ""
    options: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)


_REGISTRY: Dict[str, AdapterSpec] = {}


def register_adapter(spec: AdapterSpec) -> None:
    _REGISTRY[spec.name] = spec


def list_adapters() -> List[Dict[str, Any]]:
    return [
        {
            "name": s.name,
            "description": s.description,
            "requires": s.requires,
            "options": list(s.options),
        }
        for s in sorted(_REGISTRY.values(), key=lambda s: s.name)
    ]


def get_adapter(name: str, **kwargs) -> Any:
    if name not in _REGISTRY:
        raise KeyError(f"unknown adapter: {name!r}; available: {sorted(_REGISTRY)}")
    spec = _REGISTRY[name]
    unknown = set(kwargs) - set(spec.options)
    if unknown:
        raise TypeError(f"adapter {name!r} got unexpected options: {sorted(unknown)}")
    return spec.factory(**kwargs)


# --------------------------------------------------------------------------- #
# evidence store
# --------------------------------------------------------------------------- #

class EvidenceStore:
    """Append-only JSONL store for run records.

    Append-only matters: conclusions must stay recomputable after the judging
    rules change, so original records are never rewritten in place.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: Dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read(self) -> List[Dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def runs(self, kinds: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        rows = self.read()
        if kinds:
            rows = [r for r in rows if r.get("kind") in kinds]
        return rows

    def next_index(self, prefix: str = "R") -> int:
        used = []
        for r in self.read():
            rid = str(r.get("run_id", ""))
            if "-" in rid:
                try:
                    used.append(int(rid.rsplit("-", 1)[1]))
                except ValueError:
                    pass
        return max(used, default=0) + 1


# --------------------------------------------------------------------------- #
# suite execution (adapter-driven)
# --------------------------------------------------------------------------- #

def run_suite(
    adapter: Any,
    store: EvidenceStore,
    cases: List[Dict[str, Any]],
    repeat_override: int = 0,
    on_event=None,
) -> Dict[str, Any]:
    """Execute every case against the adapter and persist evidence.

    on_event(dict) is called after each run so a UI can stream progress.
    """
    rows: List[Dict[str, Any]] = []
    index = store.next_index()
    for case in cases:
        reps = repeat_override if repeat_override > 0 else int(case.get("repeat", 3))
        for rep in range(1, reps + 1):
            result = adapter.run_case(case, rep)
            verdict = judge(case, result)
            record = {
                "kind": "suite_run",
                "adapter": adapter.name,
                "run_id": result.get("run_id") or f"{prefix_run_id(index)}",
                "case_id": case.get("case_id"),
                "title": case.get("title", ""),
                "category": case.get("category", ""),
                "rep": rep,
                "timestamp": result.get("timestamp"),
                "final_answer": result.get("final_answer", ""),
                "tool_calls": result.get("tool_calls", []),
                "tool_names": result.get("tool_names", []),
                "error_type": result.get("error_type"),
                "error": result.get("error"),
                "usage": result.get("usage", {}),
                "elapsed_seconds": result.get("elapsed_seconds", 0),
                "events_file": result.get("events_file"),
                "judgement": verdict,
            }
            for key, value in result.items():
                if key not in record:
                    record[key] = value
            record["success"] = verdict["success"]
            store.append(record)
            rows.append(record)
            index += 1
            if on_event:
                on_event(record)
    return aggregate(rows)


def prefix_run_id(index: int) -> str:
    return f"RUN-{index:04d}"
