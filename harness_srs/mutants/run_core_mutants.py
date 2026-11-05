#!/usr/bin/env python
"""Mutation runner for the GENERIC core of the Harness.

Copies the core into an isolated directory, applies one precise single-logic
change, and runs the core self-tests. A surviving mutant means the shared
judging/aggregation semantics are not actually enforced.

Offline: no network, no credentials.

    python harness_srs/mutants/run_core_mutants.py
"""
from __future__ import annotations

import argparse
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
sys.path.insert(0, str(HERE))
from core_mutant_definitions import MUTANTS, RESPONSIBILITY_CLASSES  # noqa: E402


def copy_core(dest: Path) -> Path:
    """Copy the core plus every module the core self-tests import."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "core").mkdir(parents=True, exist_ok=True)
    shutil.copy2(SUBMISSION / "core" / "__init__.py", dest / "core" / "__init__.py")
    for name in ("platform_harness.py", "reclassify_platform.py", "report_platform.py"):
        src = SUBMISSION / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    (dest / "adapters").mkdir(parents=True, exist_ok=True)
    shutil.copy2(SUBMISSION / "adapters" / "__init__.py", dest / "adapters" / "__init__.py")
    if (SUBMISSION / "platform_cases").is_dir():
        shutil.copytree(SUBMISSION / "platform_cases", dest / "platform_cases")
    shutil.copytree(SUBMISSION / "tests", dest / "tests")
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


def run_tests(target: Path) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
            cwd=str(target), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {"outcome": "timeout", "output": "", "elapsed": round(time.perf_counter() - started, 2)}
    output = (completed.stdout or "") + (completed.stderr or "")
    return {
        "outcome": "failed" if completed.returncode != 0 else "passed",
        "output": output[-4000:],
        "elapsed": round(time.perf_counter() - started, 2),
    }


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Mutate the generic Harness core")
    parser.add_argument("--out", default=str(SUBMISSION / "evidence" / "core_mutants.json"))
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="core_mutant_baseline_") as tmp:
        baseline = run_tests(copy_core(Path(tmp) / "h"))
    print(f"== baseline (unmutated core) == outcome={baseline['outcome']}")
    if baseline["outcome"] != "passed":
        print(baseline["output"][-2000:])
        return 2

    records: List[Dict[str, Any]] = []
    for mutant_id, klass, rel_file, old, new, prop in MUTANTS:
        with tempfile.TemporaryDirectory(prefix=f"core_mutant_{mutant_id}_") as tmp:
            target = copy_core(Path(tmp) / "h")
            entry: Dict[str, Any] = {
                "mutant_id": mutant_id,
                "responsibility_class": klass,
                "responsibility_label": RESPONSIBILITY_CLASSES.get(klass, klass),
                "target_file": rel_file,
                "violated_property": prop,
            }
            try:
                apply_mutant(target, rel_file, old, new)
            except ValueError as exc:
                entry["outcome"] = "invalid_mutant"
                entry["detail"] = str(exc)
                records.append(entry)
                print(f"[{mutant_id}] invalid_mutant: {exc}")
                continue
            result = run_tests(target)
            entry["outcome"] = {"passed": "survived", "failed": "killed"}.get(result["outcome"], result["outcome"])
            entry["elapsed"] = result["elapsed"]
            m = re.search(r"^(?:FAIL|ERROR): (\w+) \(", result["output"], re.MULTILINE)
            entry["detected_by"] = m.group(1) if m else None
            entry["evidence_tail"] = "\n".join(result["output"].splitlines()[-10:])
            records.append(entry)
            print(f"[{mutant_id}] {entry['outcome']:14s} ({klass}) detected_by={entry.get('detected_by')}")

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
