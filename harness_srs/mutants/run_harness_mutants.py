#!/usr/bin/env python
"""Mutation runner for the LEUCS Harness itself.

Applies one precise single-logic change to a copy of the Harness, runs the
Harness's own self-tests, and classifies the outcome:

  killed / survived / invalid_mutant / error

The point is to answer: "do the Harness's assertions actually assert anything?"
A surviving mutant means the corresponding check is vacuous.

This is offline: it needs neither platform access nor credentials, because the
Harness self-tests use synthetic evidence records.

Usage:
    python harness_srs/mutants/run_harness_mutants.py
    python harness_srs/mutants/run_harness_mutants.py --out evidence/harness_mutants.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
SUBMISSION = HERE.parent
TESTS_DIR = SUBMISSION / "tests"
HARNESS_FILES = ["platform_harness.py", "reclassify_platform.py", "report_platform.py"]

sys.path.insert(0, str(HERE))
from harness_mutant_definitions import MUTANTS, RESPONSIBILITY_CLASSES  # noqa: E402


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def copy_harness(dest: Path) -> Path:
    """Copy the harness + its self-tests + case files into an isolated directory."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in HARNESS_FILES:
        shutil.copy2(SUBMISSION / name, dest / name)
    shutil.copytree(TESTS_DIR, dest / "tests")
    shutil.copytree(SUBMISSION / "platform_cases", dest / "platform_cases")
    for cache in dest.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    return dest


def apply_mutant(target: Path, rel_file: str, old: str, new: str) -> None:
    path = target / rel_file
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise ValueError(f"snippet matched {count} times in {rel_file} (must be exactly 1)")
    path.write_text(text.replace(old, new), encoding="utf-8")


def run_self_tests(target: Path) -> Dict[str, Any]:
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": "",
    }
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
            cwd=str(target), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {
            "outcome": "timeout",
            "output": "",
            "elapsed": round(time.perf_counter() - started, 2),
        }
    output = (completed.stdout or "") + (completed.stderr or "")
    return {
        "outcome": "failed" if completed.returncode != 0 else "passed",
        "output": output[-4000:],
        "elapsed": round(time.perf_counter() - started, 2),
    }


def baseline_check() -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="harness_mutant_baseline_") as tmp:
        target = copy_harness(Path(tmp) / "harness")
        return run_self_tests(target)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Mutate the LEUCS Harness to test its own assertions")
    parser.add_argument("--out", default=str(SUBMISSION / "evidence" / "harness_mutants.json"))
    parser.add_argument("--only", default="", help="run only mutants whose id starts with this")
    args = parser.parse_args(argv)

    print("== baseline (unmutated harness) ==")
    baseline = baseline_check()
    print(f"   outcome={baseline['outcome']} elapsed={baseline['elapsed']}s")
    if baseline["outcome"] != "passed":
        print("   baseline does not pass; aborting mutation run.")
        print(baseline["output"][-2000:])
        return 2

    records: List[Dict[str, Any]] = []
    for mutant_id, klass, rel_file, old, new, property_text, detector in MUTANTS:
        if args.only and not mutant_id.startswith(args.only):
            continue
        with tempfile.TemporaryDirectory(prefix=f"harness_mutant_{mutant_id}_") as tmp:
            target = copy_harness(Path(tmp) / "harness")
            entry: Dict[str, Any] = {
                "mutant_id": mutant_id,
                "responsibility_class": klass,
                "responsibility_label": RESPONSIBILITY_CLASSES.get(klass, klass),
                "target_file": rel_file,
                "violated_property": property_text,
                "expected_detector": detector,
            }
            try:
                apply_mutant(target, rel_file, old, new)
            except ValueError as exc:
                entry["outcome"] = "invalid_mutant"
                entry["detail"] = str(exc)
                records.append(entry)
                print(f"[{mutant_id}] invalid_mutant: {exc}")
                continue
            result = run_self_tests(target)
            outcome = result["outcome"]
            if outcome == "passed":
                entry["outcome"] = "survived"
            elif outcome == "failed":
                entry["outcome"] = "killed"
            else:
                entry["outcome"] = outcome
            entry["elapsed"] = result["elapsed"]
            m = re.search(r"^(?:FAIL|ERROR): (\w+) \(", result["output"], re.MULTILINE)
            entry["detected_by"] = m.group(1) if m else None
            tail = "\n".join(result["output"].splitlines()[-12:])
            entry["evidence_tail"] = tail
            records.append(entry)
            print(f"[{mutant_id}] {entry['outcome']}  ({klass})  detected_by={entry.get('detected_by')}")

    evaluable = [r for r in records if r["outcome"] in ("killed", "survived")]
    killed = sum(1 for r in evaluable if r["outcome"] == "killed")
    by_class: Dict[str, Dict[str, int]] = {}
    for r in records:
        agg = by_class.setdefault(r["responsibility_class"], {"total": 0, "killed": 0})
        agg["total"] += 1
        if r["outcome"] == "killed":
            agg["killed"] += 1
    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_outcome": baseline["outcome"],
        "summary": {
            "mutants_total": len(records),
            "evaluable": len(evaluable),
            "killed": killed,
            "survived": sum(1 for r in evaluable if r["outcome"] == "survived"),
            "ratio": round(killed / len(evaluable), 4) if evaluable else 0.0,
            "by_class": by_class,
            "survivors": [r["mutant_id"] for r in evaluable if r["outcome"] == "survived"],
        },
        "mutants": records,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n== summary ==")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
