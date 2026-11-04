#!/usr/bin/env python
"""Unified regression entry for the LEUCS Harness.

Runs the platform layer (cases + optional health probe) and the model layer
(optional), then writes one consolidated regression report.

Design goals:
- One command for "is the platform still behaving?".
- Deterministic ordering and a stable schema so results are comparable over time.
- Failures are separated into platform-layer and model-layer so a broken
  platform does not silently invalidate model-layer conclusions.

Usage:
    # platform layer only (recommended for routine checks)
    python harness_srs/run_all.py --platform-only --reps 3

    # with health probe
    python harness_srs/run_all.py --platform-only --probe

    # model layer (needs STUDENT_AGENT_API_KEY / LEUCS_BASE_URL / LEUCS_MODEL)
    python harness_srs/run_all.py --model-only

    # both
    python harness_srs/run_all.py --probe
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
PLATFORM_CASES = ROOT / "platform_cases"
REPORT = EVIDENCE / "regression_report.md"
REPORT_JSON = EVIDENCE / "regression_report.json"


def run(cmd: List[str], cwd: Path) -> Dict[str, Any]:
    started = time.time()
    completed = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1800,
    )
    return {
        "cmd": " ".join(cmd),
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.time() - started, 2),
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-2000:],
    }


def platform_layer(reps: int, run_timeout: float, decision: str) -> Dict[str, Any]:
    runs_file = EVIDENCE / "platform_runs.jsonl"
    before = runs_file.stat().st_size if runs_file.is_file() else 0
    result = run([
        sys.executable, str(ROOT / "platform_harness.py"), "suite",
        "--cases", str(PLATFORM_CASES),
        "--repeat", str(reps),
        "--run-timeout", str(run_timeout),
        "--decision", decision,
    ], cwd=ROOT.parent)
    new_lines: List[Dict[str, Any]] = []
    if runs_file.is_file():
        with runs_file.open("r", encoding="utf-8") as handle:
            handle.seek(before)
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        new_lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return {"result": result, "runs": new_lines}


def model_layer() -> Dict[str, Any]:
    cases = ROOT / "cases_real"
    if not cases.is_dir() or not any(cases.glob("*.json")):
        return {"skipped": "no model-layer case files", "runs": []}
    runs_file = EVIDENCE / "runs_real.jsonl"
    before = runs_file.stat().st_size if runs_file.is_file() else 0
    result = run([sys.executable, str(ROOT / "real_harness.py"), str(cases)], cwd=ROOT.parent)
    new_lines: List[Dict[str, Any]] = []
    if runs_file.is_file():
        with runs_file.open("r", encoding="utf-8") as handle:
            handle.seek(before)
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        new_lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return {"result": result, "runs": new_lines}


def probe() -> Dict[str, Any]:
    result = run([sys.executable, str(ROOT / "platform_probe.py"), "--compare-baseline"], cwd=ROOT.parent)
    verdict = "unknown"
    try:
        payload = json.loads(result["stdout_tail"])
        verdict = payload["summary"]["verdict"]
    except Exception:
        pass
    return {"result": result, "verdict": verdict}


def build_report(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# LEUCS Harness 统一回归报告")
    lines.append("")
    lines.append(f"- 生成时间：{payload['timestamp']}")
    lines.append(f"- 模式：{payload['mode']}")
    lines.append("")

    lines.append("## 1 健康探针")
    lines.append("")
    probe_result = payload.get("probe")
    if not probe_result:
        lines.append("- 未执行")
    else:
        lines.append(f"- 结论：`{probe_result.get('verdict')}`")
        lines.append(f"- 退出码：{probe_result['result']['returncode']}")
    lines.append("")

    lines.append("## 2 平台层")
    lines.append("")
    plat = payload.get("platform") or {}
    runs = plat.get("runs") or []
    if not runs:
        lines.append("- 未执行或无新增记录")
    else:
        dist = Counter(r.get("error_type") or "ok" for r in runs)
        lines.append(f"- 运行数：{len(runs)}")
        lines.append("- 失败分层：" + "、".join(f"`{k}`×{v}" for k, v in dist.most_common()))
        by_case: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in runs:
            by_case[str(r.get("case_id"))].append(r)
        lines.append("")
        lines.append("| 用例 | n | 成功 | 错误类型 |")
        lines.append("|---|---|---|---|")
        for cid in sorted(by_case):
            group = by_case[cid]
            ok = sum(1 for r in group if (r.get("judgement") or {}).get("success"))
            types = Counter(r.get("error_type") or "ok" for r in group)
            lines.append(f"| {cid} | {len(group)} | {ok} | " + "、".join(f"{k}×{v}" for k, v in types.most_common()) + " |")
    lines.append("")

    lines.append("## 3 模型层")
    lines.append("")
    mod = payload.get("model") or {}
    if mod.get("skipped"):
        lines.append(f"- 跳过：{mod['skipped']}")
    else:
        lines.append(f"- 退出码：{mod.get('result', {}).get('returncode')}")
        lines.append(f"- 新增记录：{len(mod.get('runs') or [])}")
    lines.append("")

    lines.append("## 4 结论边界")
    lines.append("")
    lines.append("- `infrastructure_error` 不计入 Agent 行为失败率。")
    lines.append("- 本报告只覆盖本次执行的用例与配置，不外推到其他模型、挂载模式或工具组合。")
    lines.append("- 平台不可用时模型层结论不具可比性，应先确认健康探针通过。")
    lines.append("")
    lines.append("原始证据：`evidence/platform_runs.jsonl`、`evidence/platform_probe.jsonl`。")
    return "\n".join(lines) + "\n"


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Unified LEUCS Harness regression")
    parser.add_argument("--platform-only", action="store_true")
    parser.add_argument("--model-only", action="store_true")
    parser.add_argument("--probe", action="store_true", help="run the health probe first")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--run-timeout", type=float, default=150.0)
    parser.add_argument("--decision", choices=["none", "deny", "approve"], default="none")
    args = parser.parse_args(argv)

    payload: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "platform-only" if args.platform_only else ("model-only" if args.model_only else "both"),
        "probe": None,
        "platform": None,
        "model": None,
    }

    if args.probe:
        payload["probe"] = probe()

    if not args.model_only:
        payload["platform"] = platform_layer(args.reps, args.run_timeout, args.decision)
    if not args.platform_only:
        payload["model"] = model_layer()

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(payload), encoding="utf-8")
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {REPORT}")
    print(f"wrote {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
