#!/usr/bin/env python
"""Unified CLI for the Harness: run suites, list adapters, summarize evidence.

    python harness_srs/harness_cli.py adapters
    python harness_srs/harness_cli.py cases --adapter leucs
    python harness_srs/harness_cli.py run --adapter leucs --repeat 2
    python harness_srs/harness_cli.py summary --adapter leucs
    python harness_srs/harness_cli.py dashboard --port 8801
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import adapters  # noqa: E402  (registers built-in adapters)
from core import EvidenceStore, aggregate, get_adapter, list_adapters, run_suite  # noqa: E402


def _adapter_options(adapter: str) -> Dict[str, Any]:
    """Resolve adapter options from the environment."""
    if adapter == "leucs":
        return {
            "base": os.environ.get("LEUCS_PLATFORM_BASE", "https://123.57.180.120"),
            "token": os.environ.get("LEUCS_PLATFORM_TOKEN", ""),
            "cases_dir": str(ROOT / "platform_cases"),
            "evidence_dir": str(ROOT / "evidence"),
        }
    return {}


def _evidence_file(adapter: str) -> Path:
    return ROOT / "evidence" / ("platform_runs.jsonl" if adapter == "leucs" else f"{adapter}_runs.jsonl")


def cmd_adapters(_args) -> int:
    print("可用适配器：\n")
    for a in list_adapters():
        print(f"  {a['name']}")
        print(f"      {a['description']}")
        if a["requires"]:
            print(f"      需要凭据: {', '.join(a['requires'])}")
        if a["options"]:
            print(f"      可配置项 : {', '.join(a['options'])}")
        print()
    return 0


def cmd_cases(args) -> int:
    instance = get_adapter(args.adapter, **_adapter_options(args.adapter))
    cases = instance.list_cases()
    if args.json:
        print(json.dumps(cases, ensure_ascii=False, indent=2))
        return 0
    print(f"用例（{len(cases)} 个）：\n")
    for c in cases:
        print(f"  {c.get('case_id'):12s} [{c.get('category','-'):10s}] {c.get('title','')}")
        print(f"      repeat={c.get('repeat', 3)}  oracle={list((c.get('oracle') or {}).keys())}")
    return 0


def cmd_run(args) -> int:
    instance = get_adapter(args.adapter, **_adapter_options(args.adapter))
    cases = instance.list_cases()
    if args.case:
        wanted = set(args.case)
        cases = [c for c in cases if c.get("case_id") in wanted]
    if not cases:
        print("没有匹配的用例。", file=sys.stderr)
        return 2
    store = EvidenceStore(_evidence_file(args.adapter))
    print(f"运行 {len(cases)} 个用例 × {args.repeat or '用例默认'} 次 …\n")
    summary = run_suite(instance, store, cases, repeat_override=args.repeat,
                       on_event=lambda r: _print_run(r))
    print("\n=== 汇总 ===")
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))
    print()
    for cid, agg in summary["by_case"].items():
        print(f"  {cid:12s} n={agg['n']:3d} ok={agg['success']:3d} "
              f"rate={agg['success_rate']:.3f} avg={agg['avg_elapsed_seconds']}s")
    return 0


def _print_run(record: Dict[str, Any]) -> None:
    verdict = record.get("judgement") or {}
    ok = verdict.get("success")
    mark = "OK  " if ok else "FAIL"
    et = record.get("error_type") or "-"
    answer = (record.get("final_answer") or "").replace("\n", " ")[:70]
    print(f"  [{mark}] {record.get('run_id'):28s} {record.get('case_id','-'):12s} "
          f"{et:22s} {record.get('elapsed_seconds','-')}s  {answer}")


def cmd_summary(args) -> int:
    store = EvidenceStore(_evidence_file(args.adapter))
    rows = store.runs(kinds=["suite_run", "run"])
    summary = aggregate(rows)
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))
    print()
    for cid, agg in summary["by_case"].items():
        print(f"  {cid:12s} n={agg['n']:3d} ok={agg['success']:3d} "
              f"rate={agg['success_rate']:.3f} avg={agg['avg_elapsed_seconds']}s")
    return 0


def cmd_dashboard(args) -> int:
    import dashboard
    argv = ["--port", str(args.port), "--host", args.host]
    if args.evidence_dir:
        argv += ["--evidence-dir", args.evidence_dir]
    return dashboard.main(argv)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="LEUCS 测试 Harness 统一入口")
    parser.add_argument("--adapter", default="leucs", help="目标适配器名称")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("adapters", help="列出可用适配器").set_defaults(func=cmd_adapters)

    p_cases = sub.add_parser("cases", help="列出用例")
    p_cases.add_argument("--json", action="store_true")
    p_cases.set_defaults(func=cmd_cases)

    p_run = sub.add_parser("run", help="运行套件")
    p_run.add_argument("--repeat", type=int, default=0)
    p_run.add_argument("--case", action="append", help="只跑指定 case_id（可重复）")
    p_run.set_defaults(func=cmd_run)

    sub.add_parser("summary", help="汇总历史证据").set_defaults(func=cmd_summary)

    p_dash = sub.add_parser("dashboard", help="启动 Web 控制台")
    p_dash.add_argument("--port", type=int, default=8801)
    p_dash.add_argument("--host", default="127.0.0.1")
    p_dash.add_argument("--evidence-dir", default="")
    p_dash.set_defaults(func=cmd_dashboard)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
