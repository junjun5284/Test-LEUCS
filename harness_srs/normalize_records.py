#!/usr/bin/env python
"""Normalise legacy run records into the current schema — without mutating originals.

Early runs (from the first platform-harness version) were written before the
record schema settled: they lack `judgement`, `success`, and a few standard
fields. Analysis code has to tolerate both shapes (see `core.is_success`),
but a *delivery package* should also carry a clean, uniform view.

This tool therefore produces a **derived** file:
  evidence/platform_runs_normalized.jsonl

The original `platform_runs.jsonl` is never rewritten — the append-only
evidence chain stays intact, and the derived file records which source record
each row came from.

Usage:
    python harness_srs/normalize_records.py
    python harness_srs/normalize_records.py --check
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import is_success  # noqa: E402

SOURCE = ROOT / "evidence" / "platform_runs.jsonl"
NORMALIZED = ROOT / "evidence" / "platform_runs_normalized.jsonl"

REQUIRED = ("run_id", "case_id", "timestamp", "final_answer", "error_type", "elapsed_seconds")

# Records that are platform read-only calls rather than Agent runs: they have
# no case and no verdict by nature.
NON_RUN_KINDS = {"health", "list", "conversation", "events", "feed", "mount", "config"}


def normalize(record: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(record)
    kind = out.get("kind") or "run"

    out.setdefault("final_answer", "")
    out.setdefault("tool_calls", [])
    out.setdefault("tool_names", [])
    out.setdefault("error", None)
    out.setdefault("usage", {})
    out.setdefault("elapsed_seconds", 0.0)
    out.setdefault("timestamp", "")
    out.setdefault("case_id", "")
    out.setdefault("title", "")
    out.setdefault("category", "")
    out.setdefault("rep", 1)

    if kind in NON_RUN_KINDS:
        out["verdict_applicable"] = False
        out.setdefault("success", None)
        return out

    out["verdict_applicable"] = True
    if "success" not in out:
        out["success"] = is_success(record)
    if "judgement" not in out:
        out["judgement"] = {"success": out["success"], "checks": {}, "tool_names": out.get("tool_names", [])}
    if out.get("error_type") is None and not out["success"]:
        out["error_type"] = "unclassified_failure"
    return out


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Normalise legacy run records (derived output only)")
    parser.add_argument("--check", action="store_true", help="report only, do not write")
    args = parser.parse_args(argv)

    if not SOURCE.is_file():
        print(f"ERROR: missing {SOURCE}", file=sys.stderr)
        return 2

    rows = [json.loads(l) for l in SOURCE.read_text(encoding="utf-8").splitlines() if l.strip()]
    normalized: List[Dict[str, Any]] = []
    changed = 0
    for row in rows:
        fixed = normalize(row)
        if fixed != row:
            changed += 1
        fixed["_source_run_id"] = row.get("run_id")
        fixed["_normalized_at"] = datetime.now(timezone.utc).isoformat()
        normalized.append(fixed)

    incomplete = [r.get("run_id") for r in normalized
                  if r.get("verdict_applicable") and any(k not in r for k in REQUIRED)]
    unclassified = [r.get("run_id") for r in normalized
                    if r.get("verdict_applicable") and r.get("error_type") == "unclassified_failure"]

    print(f"源记录      : {len(rows)}")
    print(f"补全字段    : {changed}")
    print(f"仍缺必填字段: {len(incomplete)}")
    print(f"无错误类型  : {len(unclassified)}（成功记录不计）")

    if not args.check:
        NORMALIZED.parent.mkdir(parents=True, exist_ok=True)
        with NORMALIZED.open("w", encoding="utf-8") as handle:
            for row in normalized:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"\nwrote {NORMALIZED}")

    return 1 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
