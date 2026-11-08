#!/usr/bin/env python
"""Compare two runs of the same case set and decide whether behaviour regressed.

This is the piece that turns a pile of run records into a *verdict about change*.
It answers: "given the same cases, did the target get better or worse since the
baseline, and if so, which cases moved?"

Design rules
------------
- Compares like with like: only cases present in BOTH snapshots are compared.
- Distinguishes **behaviour change** from **noise**: a case that flipped
  verdicts in both directions across repetitions is reported as *flaky*, not
  as a regression.
- Separates infrastructure failures from behaviour failures, so a platform
  outage never looks like a product regression.
- Never mutates either snapshot.

Usage:
    # save a baseline
    python harness_srs/baseline.py save --adapter leucs --label 2026-11-08

    # later, compare current runs against it
    python harness_srs/baseline.py compare --adapter leucs --baseline baselines/leucs-2026-11-08.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import EvidenceStore, is_success  # noqa: E402

BASELINE_DIR = ROOT / "baselines"


def _evidence_file(adapter: str) -> Path:
    if adapter == "mock-target":
        return ROOT / "evidence" / "mock_runs.jsonl"
    return ROOT / "evidence" / ("platform_runs.jsonl" if adapter == "leucs" else f"{adapter}_runs.jsonl")


def collect(adapter: str) -> Dict[str, List[Dict[str, Any]]]:
    """Group current runs by case_id."""
    store = EvidenceStore(_evidence_file(adapter))
    rows = store.runs(kinds=["suite_run"])
    by_case: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_case.setdefault(str(r.get("case_id")), []).append(r)
    return by_case


def case_profile(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(runs)
    successes = sum(1 for r in runs if is_success(r))
    infra = sum(1 for r in runs if r.get("error_type") == "infrastructure_error")
    err_types: Dict[str, int] = {}
    for r in runs:
        key = r.get("error_type") or "ok"
        err_types[key] = err_types.get(key, 0) + 1
    return {
        "n": n,
        "successes": successes,
        "success_rate": round(successes / n, 3) if n else 0.0,
        "infrastructure_error": infra,
        "error_types": err_types,
        "avg_elapsed": round(sum(r.get("elapsed_seconds") or 0 for r in runs) / n, 2) if n else 0.0,
    }


def classify_change(before: Dict[str, Any], after: Dict[str, Any]) -> str:
    """One of: improved / regressed / unchanged / flaky / inconclusive."""
    if before["n"] == 0 or after["n"] == 0:
        return "inconclusive"
    b_rate, a_rate = before["success_rate"], after["success_rate"]
    if abs(a_rate - b_rate) < 1e-9:
        return "unchanged"
    # A case whose verdicts flip in both directions across runs is noise, not
    # a behavioural regression.
    if before["successes"] not in (0, before["n"]) and after["successes"] not in (0, after["n"]):
        return "flaky"
    if after["infrastructure_error"] > before["infrastructure_error"]:
        return "inconclusive"
    return "improved" if a_rate > b_rate else "regressed"


def compare_snapshots(base: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    base_cases: Dict[str, Any] = base.get("cases") or {}
    cur_cases: Dict[str, Any] = current.get("cases") or {}
    shared = sorted(set(base_cases) & set(cur_cases))
    only_base = sorted(set(base_cases) - set(cur_cases))
    only_cur = sorted(set(cur_cases) - set(base_cases))

    changes: List[Dict[str, Any]] = []
    buckets: Dict[str, int] = {}
    for cid in shared:
        verdict = classify_change(base_cases[cid], cur_cases[cid])
        buckets[verdict] = buckets.get(verdict, 0) + 1
        if verdict in ("regressed", "improved", "flaky"):
            changes.append({
                "case_id": cid,
                "verdict": verdict,
                "before": base_cases[cid],
                "after": cur_cases[cid],
            })

    overall_before = base.get("totals", {})
    overall_after = current.get("totals", {})
    return {
        "schema_version": "1.0",
        "compared_at": datetime.now(timezone.utc).isoformat(),
        "baseline_label": base.get("label"),
        "baseline_captured_at": base.get("captured_at"),
        "current_captured_at": current.get("captured_at"),
        "cases_compared": len(shared),
        "cases_only_in_baseline": only_base,
        "cases_only_in_current": only_cur,
        "verdict_counts": buckets,
        "regressed": [c["case_id"] for c in changes if c["verdict"] == "regressed"],
        "improved": [c["case_id"] for c in changes if c["verdict"] == "improved"],
        "flaky": [c["case_id"] for c in changes if c["verdict"] == "flaky"],
        "changes": changes,
        "totals_before": overall_before,
        "totals_after": overall_after,
        "overall_verdict": overall_verdict(buckets, overall_before, overall_after),
    }


def overall_verdict(buckets: Dict[str, int], before: Dict[str, Any], after: Dict[str, Any]) -> str:
    if not buckets:
        return "no_comparable_cases"
    if buckets.get("regressed", 0) > buckets.get("improved", 0):
        return "regressed"
    if buckets.get("improved", 0) > buckets.get("regressed", 0):
        return "improved"
    if buckets.get("flaky", 0):
        return "unstable"
    return "unchanged"


def snapshot_from_runs(adapter: str, label: str) -> Dict[str, Any]:
    by_case = collect(adapter)
    cases = {cid: case_profile(runs) for cid, runs in by_case.items()}
    total_n = sum(c["n"] for c in cases.values())
    total_ok = sum(c["successes"] for c in cases.values())
    total_infra = sum(c["infrastructure_error"] for c in cases.values())
    return {
        "schema_version": "1.0",
        "label": label,
        "adapter": adapter,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "cases": len(cases),
            "runs": total_n,
            "successes": total_ok,
            "success_rate": round(total_ok / total_n, 3) if total_n else 0.0,
            "infrastructure_error": total_infra,
        },
        "cases": cases,
    }


def cmd_save(args) -> int:
    snap = snapshot_from_runs(args.adapter, args.label)
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    path = BASELINE_DIR / f"{args.adapter}-{args.label}.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path}")
    print(json.dumps(snap["totals"], ensure_ascii=False, indent=2))
    return 0


def cmd_compare(args) -> int:
    base_path = Path(args.baseline)
    if not base_path.is_absolute() and not base_path.is_file():
        # Allow a label-style path such as "mock-target-2026-11-08.json".
        candidate = BASELINE_DIR / base_path.name
        if candidate.is_file():
            base_path = candidate
    if not base_path.is_file():
        print(f"ERROR: baseline not found: {base_path}", file=sys.stderr)
        print(f"       available: {[p.name for p in BASELINE_DIR.glob('*.json')]}", file=sys.stderr)
        return 2
    base = json.loads(base_path.read_text(encoding="utf-8"))
    current = snapshot_from_runs(args.adapter, args.label or "current")
    result = compare_snapshots(base, current)
    out = ROOT / "evidence" / f"baseline_diff_{args.adapter}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "overall_verdict": result["overall_verdict"],
        "cases_compared": result["cases_compared"],
        "verdict_counts": result["verdict_counts"],
        "regressed": result["regressed"],
        "improved": result["improved"],
        "flaky": result["flaky"],
    }, ensure_ascii=False, indent=2))
    print(f"\nwrote {out}")
    return 0


def cmd_list(args) -> int:
    if not BASELINE_DIR.is_dir():
        print("（还没有基线）")
        return 0
    for path in sorted(BASELINE_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        totals = data.get("totals", {})
        print(f"{path.name:40s} cases={totals.get('cases')} runs={totals.get('runs')} "
              f"rate={totals.get('success_rate')} captured={data.get('captured_at')}")
    return 0


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Harness baseline / regression comparison")
    parser.add_argument("--adapter", default="leucs")
    sub = parser.add_subparsers(dest="command", required=True)

    p_save = sub.add_parser("save", help="save current runs as a baseline")
    p_save.add_argument("--label", required=True)
    p_save.set_defaults(func=cmd_save)

    p_cmp = sub.add_parser("compare", help="compare current runs against a baseline")
    p_cmp.add_argument("--baseline", required=True)
    p_cmp.add_argument("--label", default="current")
    p_cmp.set_defaults(func=cmd_compare)

    sub.add_parser("list", help="list saved baselines").set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
