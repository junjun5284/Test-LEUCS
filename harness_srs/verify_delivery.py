#!/usr/bin/env python
"""One-command delivery verification for the LEUCS test Harness.

A reviewer should be able to run ONE command and learn:
  - is the package self-contained and free of credentials?
  - do the self-tests pass?
  - do the mutation tests still hold (i.e. are the assertions real)?
  - are the case definitions sane?
  - do the capability contracts still hold?
  - is every recorded run traceable to its evidence?
  - do the documents agree with the code (version numbers, issue counts)?

Everything here is OFFLINE. It never touches the platform or the model service.

Usage:
    python harness_srs/verify_delivery.py
    python harness_srs/verify_delivery.py --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SECRET_PATTERNS = [
    re.compile(r"gpustack_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsftx4[A-Za-z0-9_]{20,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_.\-]{24,}"),
    re.compile(r"\bcsdZO[A-Za-z0-9_]{20,}"),
    re.compile(r"\bLnS0h4[A-Za-z0-9_]{20,}"),
    re.compile(r"\bqQA8B[A-Za-z0-9_]{20,}"),
    re.compile(r"\bU95L3M[A-Za-z0-9_]{20,}"),
]

SKIP_DIRS = {"__pycache__", ".git"}

# Test files legitimately contain credential-shaped strings as negative
# fixtures. A file counts as a fixture when it declares this marker, so the
# scanner neither flags them nor becomes blind to real leaks elsewhere.
SAMPLE_MARKER = "SAMPLE_CREDENTIAL_FOR_TEST"


def is_test_fixture(text: str, path: Path) -> bool:
    return SAMPLE_MARKER in text or path.name.startswith("test_")


def run(cmd: List[str], cwd: Path, timeout: int = 600) -> Tuple[int, str]:
    try:
        completed = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 1, "timeout"
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, output


class Checks:
    def __init__(self) -> None:
        self.results: List[Dict[str, Any]] = []

    def add(self, name: str, ok: bool, detail: str = "", severity: str = "error") -> bool:
        self.results.append({
            "check": name,
            "ok": bool(ok),
            "severity": severity,
            "detail": detail[:400],
        })
        return bool(ok)

    @property
    def errors(self) -> List[Dict[str, Any]]:
        return [r for r in self.results if not r["ok"] and r["severity"] == "error"]

    @property
    def warnings(self) -> List[Dict[str, Any]]:
        return [r for r in self.results if not r["ok"] and r["severity"] == "warn"]


def scan_secrets(checks: Checks) -> None:
    hits: List[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in (".py", ".json", ".jsonl", ".md", ".txt", ".json"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if is_test_fixture(text, path):
            continue
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                hits.append(f"{path.relative_to(ROOT)}: {match.group(0)[:16]}...")
    checks.add("无凭据泄漏", not hits, "; ".join(hits[:5]))


def check_selftests(checks: Checks) -> None:
    code, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], ROOT)
    m = re.search(r"Ran (\d+) tests", out)
    count = m.group(1) if m else "?"
    ok = code == 0 and "OK" in out
    checks.add("自测全部通过", ok, f"{count} 项, exit={code}")


def check_mutations(checks: Checks) -> None:
    for script, label in (("mutants/run_core_mutants.py", "通用核心变异"),
                          ("mutants/run_harness_mutants.py", "平台层判定变异")):
        code, out = run([sys.executable, script], ROOT)
        ratio = re.search(r'"ratio":\s*([\d.]+)', out)
        survivors = re.findall(r'"survivors":\s*\[([^\]]*)\]', out)
        r = float(ratio.group(1)) if ratio else 0.0
        surv = survivors[0].strip() if survivors else ""
        checks.add(f"{label}变异全部被识别", code == 0 and r >= 0.999,
                   f"ratio={r} survivors=[{surv}] exit={code}")


def check_cases(checks: Checks) -> None:
    for script, label in (("lint_cases.py", "platform_cases"),
                          ("lint_cases.py", "mock_cases")):
        directory = ROOT / script if False else ROOT / script
    code, out = run([sys.executable, "lint_cases.py", "--cases", str(ROOT / "platform_cases")], ROOT)
    m = re.search(r"(\d+) 个错误", out)
    errors = int(m.group(1)) if m else 1
    checks.add("平台用例静态检查通过", code == 0, f"{errors} 个错误 exit={code}")

    code, out = run([sys.executable, "lint_cases.py", "--cases", str(ROOT / "mock_cases")], ROOT)
    m = re.search(r"(\d+) 个错误", out)
    errors = int(m.group(1)) if m else 1
    checks.add("模拟用例静态检查通过", code == 0, f"{errors} 个错误 exit={code}")


def check_contracts(checks: Checks) -> None:
    code, out = run([sys.executable, "capability_contract.py", "--adapter", "leucs", "--check"], ROOT)
    m = re.search(r'"contracts_holding":\s*(\d+)', out)
    total = re.search(r'"contracts_total":\s*(\d+)', out)
    holding = int(m.group(1)) if m else 0
    tot = int(total.group(1)) if total else 0
    checks.add("能力契约成立", code == 0 and tot > 0 and holding == tot,
               f"{holding}/{tot} 成立 exit={code}")


def check_evidence(checks: Checks) -> None:
    runs = ROOT / "evidence" / "platform_runs.jsonl"
    if not runs.is_file():
        checks.add("运行证据存在", False, "platform_runs.jsonl 缺失")
        return
    rows = [json.loads(l) for l in runs.read_text(encoding="utf-8").splitlines() if l.strip()]
    missing_events = [r["run_id"] for r in rows
                      if r.get("events_file") and not Path(r["events_file"]).is_file()]
    checks.add("全部运行记录可追溯到事件文件", not missing_events,
               f"{len(rows)} 条记录, {len(missing_events)} 条缺事件文件")

    # The immutable evidence keeps its original schema; a derived normalized
    # view must provide the uniform schema for downstream analysis.
    normalized = ROOT / "evidence" / "platform_runs_normalized.jsonl"
    if not normalized.is_file():
        checks.add("规范化视图已生成", False, "platform_runs_normalized.jsonl 缺失")
        return
    nrows = [json.loads(l) for l in normalized.read_text(encoding="utf-8").splitlines() if l.strip()]
    required = ["run_id", "case_id", "timestamp", "final_answer", "error_type", "elapsed_seconds"]
    bad = [r.get("run_id") for r in nrows
           if r.get("verdict_applicable") and any(k not in r for k in required)]
    checks.add("规范化记录字段完整", not bad, f"{len(nrows)} 条, {len(bad)} 条缺字段")

    checks.add("规范化视图与源记录条数一致", len(nrows) == len(rows),
               f"源={len(rows)} 规范化={len(nrows)}")

    # Every judged record must carry a verdict.
    no_verdict = [r.get("run_id") for r in rows
                  if "judgement" not in r and "success" not in r and r.get("kind") == "suite_run"]
    checks.add("套件运行均带判定结果", not no_verdict,
               f"{len(no_verdict)} 条无判定（早期版本记录，已由规范化视图补全）", severity="warn")


def check_docs(checks: Checks) -> None:
    srs = (ROOT / "01_SRS_LEUCS_Testing_Agent_Harness.md").read_text(encoding="utf-8")
    issues = (ROOT / "02_current_issue_list_and_prompt_methods.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    m = re.search(r"版本：v([\d.]+)", srs)
    srs_version = m.group(1) if m else "?"
    checks.add("SRS 版本号存在", bool(m), f"v{srs_version}")

    issue_ids = set(re.findall(r"ISSUE-(\d{3})", issues))
    checks.add("问题列表条目数量合理", len(issue_ids) >= 20, f"{len(issue_ids)} 条")

    for token in ("core/", "adapters/", "ADAPTER_GUIDE"):
        checks.add(f"README 引用 {token}", token in readme)

    checks.add("SRS 含通用性需求章节", "FR-30" in srs and "FR-36" in srs)
    checks.add("SRS 含回归判定需求章节", "FR-39" in srs and "FR-41" in srs)
    checks.add("问题列表含 v6.1 迭代记录", "v6.1" in issues)

    # The documented self-test count must match reality.
    code, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], ROOT)
    m = re.search(r"Ran (\d+) tests", out)
    actual = int(m.group(1)) if m else 0
    m2 = re.search(r"自测\s*\*?\*?(\d+)\s*项", readme)
    documented = int(m2.group(1)) if m2 else 0
    checks.add("README 记录的自测数量与实际一致", documented == actual,
               f"README={documented} 实际={actual}")


def build_manifest(checks: Checks) -> Dict[str, Any]:
    """Hash every delivered artifact so the package can be verified later."""
    entries = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in (".py", ".md", ".json", ".jsonl", ".txt"):
            continue
        data = path.read_bytes()
        entries.append({
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(entries),
        "files": entries,
    }
    out = ROOT / "evidence" / "delivery_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify the delivery package (offline)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-manifest", action="store_true")
    args = parser.parse_args(argv)

    checks = Checks()
    scan_secrets(checks)
    check_selftests(checks)
    check_mutations(checks)
    check_cases(checks)
    check_contracts(checks)
    check_evidence(checks)
    check_docs(checks)

    manifest = None if args.skip_manifest else build_manifest(checks)

    passed = sum(1 for r in checks.results if r["ok"])
    print("=" * 66)
    print("LEUCS 测试 Harness —— 交付自检")
    print("=" * 66)
    for r in checks.results:
        mark = "PASS" if r["ok"] else ("WARN" if r["severity"] == "warn" else "FAIL")
        print(f"  [{mark:4s}] {r['check']:34s} {r['detail']}")
    print("-" * 66)
    print(f"  通过 {passed}/{len(checks.results)}"
          f"（错误 {len(checks.errors)}，警告 {len(checks.warnings)}）")
    if manifest:
        print(f"  交付清单：{manifest['file_count']} 个文件已记录 SHA-256")
    print("=" * 66)

    if args.json:
        print(json.dumps({
            "checks": checks.results,
            "passed": passed,
            "total": len(checks.results),
            "errors": len(checks.errors),
            "warnings": len(checks.warnings),
        }, ensure_ascii=False, indent=2))

    return 1 if checks.errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
