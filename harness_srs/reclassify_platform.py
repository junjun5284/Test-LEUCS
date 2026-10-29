#!/usr/bin/env python
"""Re-derive platform failure classification from stored evidence.

The original suite records were written before the platform layer had explicit
failure categories (awaiting_approval / classification_rejected / 502). This
script re-classifies those runs from the immutable evidence (JSONL records +
events files) and writes a *derived* summary. It never modifies the original
records.

Usage:
  python harness_srs/reclassify_platform.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
RECORDS = ROOT / "evidence" / "platform_runs.jsonl"
OUT = ROOT / "evidence" / "platform_suite_summary_v2.json"


def classify(record: Dict[str, Any], events: List[Dict[str, Any]]) -> str:
    status = record.get("status")
    if isinstance(status, int) and status != 200:
        return "infrastructure_error"
    decision = any(e.get("type") == "decision" for e in events)
    rejected = any(e.get("type") == "classification_contract_rejected" for e in events)
    api_error = any(
        "api_error" in str(e.get("content") or "") or "HTTP_40" in str(e.get("content") or "")
        for e in events
    )
    final = str(record.get("final_answer") or "")
    stop_reason = str(record.get("stop_reason") or "")
    if decision:
        return "awaiting_approval"
    if rejected:
        return "classification_rejected"
    if api_error:
        return "infrastructure_error"
    if stop_reason == "error":
        return "agent_failure"
    if not final:
        return "incomplete_stream"
    return "ok"


def main() -> int:
    rows = [json.loads(line) for line in RECORDS.read_text(encoding="utf-8").splitlines() if line.strip()]
    suite = [r for r in rows if r.get("kind") == "suite_run"]

    out_rows: List[Dict[str, Any]] = []
    for r in suite:
        events: List[Dict[str, Any]] = []
        ev_file = r.get("events_file")
        if ev_file and Path(ev_file).is_file():
            events = json.loads(Path(ev_file).read_text(encoding="utf-8"))
        et = classify(r, events)
        out_rows.append({
            "run_id": r["run_id"],
            "case_id": r["case_id"],
            "rep": r["rep"],
            "status": r.get("status"),
            "event_count": r.get("event_count"),
            "elapsed_seconds": r.get("elapsed_seconds"),
            "final_answer": (r.get("final_answer") or "")[:80],
            "original_error_type": r.get("error_type"),
            "derived_error_type": et,
            "derived_success": et == "ok" and bool((r.get("final_answer") or "").strip()),
        })

    by_case: Dict[str, Dict[str, Any]] = {}
    dist: Dict[str, int] = {}
    for r in out_rows:
        agg = by_case.setdefault(r["case_id"], {"n": 0, "success": 0, "types": {}, "elapsed": []})
        agg["n"] += 1
        if r["derived_success"]:
            agg["success"] += 1
        agg["types"][r["derived_error_type"]] = agg["types"].get(r["derived_error_type"], 0) + 1
        agg["elapsed"].append(r["elapsed_seconds"] or 0)
        dist[r["derived_error_type"]] = dist.get(r["derived_error_type"], 0) + 1
    for agg in by_case.values():
        agg["success_rate"] = round(agg["success"] / agg["n"], 3) if agg["n"] else 0.0
        agg["avg_elapsed_seconds"] = round(sum(agg["elapsed"]) / len(agg["elapsed"]), 2) if agg["elapsed"] else 0.0
        del agg["elapsed"]

    total = len(out_rows)
    success = sum(1 for r in out_rows if r["derived_success"])
    summary = {
        "schema_version": "1.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "re-derived offline from platform_runs.jsonl + platform_events/*.json; original records unchanged",
        "totals": {
            "runs": total,
            "success": success,
            "success_rate": round(success / total, 3) if total else 0.0,
            "error_type_distribution": dist,
        },
        "by_case": by_case,
        "runs": out_rows,
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))
    for cid, agg in by_case.items():
        print(f"{cid}: n={agg['n']} success={agg['success']} rate={agg['success_rate']} types={agg['types']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
