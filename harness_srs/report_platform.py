#!/usr/bin/env python
"""Generate a Markdown report from platform Harness evidence (offline).

Old records were written before the Harness had explicit failure layers, so this
report re-derives the effective error type from the immutable evidence
(JSONL + per-run SSE event files) instead of trusting a missing `error_type`.
"""
from __future__ import annotations

import importlib.util
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECORDS = ROOT / "evidence" / "platform_runs.jsonl"
OUT = ROOT / "evidence" / "platform_report.md"


def _load_reclassify():
    spec = importlib.util.spec_from_file_location("reclassify_platform", ROOT / "reclassify_platform.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reclassify = _load_reclassify()


def load_events(record: dict) -> list[dict]:
    path = record.get("events_file")
    if path and Path(path).is_file():
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
    return []


def effective(record: dict, events: list[dict]) -> tuple[str, bool]:
    """Return (effective_error_type, success)."""
    if record.get("error_type"):
        error_type = record["error_type"]
    elif record.get("kind") == "suite_run" and record.get("judgement"):
        error_type = reclassify.classify(record, events)
    else:
        error_type = reclassify.classify(record, events)
    answer = (record.get("final_answer") or "").strip()
    judgement = record.get("judgement") or {}
    success = bool(judgement.get("success")) if judgement else (error_type == "ok" and bool(answer))
    return error_type, success


def main() -> int:
    if not RECORDS.is_file():
        raise SystemExit(f"missing evidence file: {RECORDS}")
    rows = [json.loads(line) for line in RECORDS.read_text(encoding="utf-8").splitlines() if line.strip()]
    runs = [r for r in rows if r.get("kind") in ("run", "suite_run")]

    enriched = []
    for r in runs:
        events = load_events(r)
        error_type, success = effective(r, events)
        tools = r.get("tool_names") or [str(e.get("tool_name")) for e in events if e.get("type") == "tool_call"]
        decisions = r.get("decision_actions") or [e for e in events if e.get("type") == "decision"]
        enriched.append({
            "record": r,
            "error_type": error_type,
            "success": success,
            "tool_names": tools,
            "decisions": decisions,
        })

    dist = Counter(e["error_type"] for e in enriched)

    lines: list[str] = []
    lines.append("# 平台层 Harness 运行报告")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- 证据来源：`{RECORDS.relative_to(ROOT.parent)}` + 逐次 SSE 事件")
    lines.append(f"- 运行总数：{len(enriched)}")
    lines.append("- 失败分层：旧记录缺 `error_type` 时，从不可变证据重新推导（原记录未修改）")
    lines.append("")
    lines.append("## 1 失败分层")
    lines.append("")
    lines.append("| 类型 | 次数 |")
    lines.append("|---|---|")
    for key, count in dist.most_common():
        lines.append(f"| `{key}` | {count} |")
    lines.append("")

    by_case: dict[str, list[dict]] = defaultdict(list)
    for item in enriched:
        if item["record"].get("kind") == "suite_run":
            by_case[str(item["record"].get("case_id"))].append(item)
    if by_case:
        lines.append("## 2 用例汇总（suite）")
        lines.append("")
        lines.append("| 用例 | n | 成功 | 成功率 | 错误类型 | 平均耗时(s) |")
        lines.append("|---|---|---|---|---|---|")
        for case_id in sorted(by_case):
            group = by_case[case_id]
            success = sum(1 for item in group if item["success"])
            types = Counter(item["error_type"] for item in group)
            elapsed = [item["record"].get("elapsed_seconds") or 0 for item in group]
            type_text = "、".join(f"{k}×{v}" for k, v in types.most_common())
            lines.append(
                f"| {case_id} | {len(group)} | {success} | {success / len(group):.3f} | "
                f"{type_text} | {sum(elapsed) / len(elapsed):.2f} |"
            )
        lines.append("")

    decision_count = sum(len(item["decisions"]) for item in enriched)
    tool_count = sum(len(item["tool_names"]) for item in enriched)
    names = Counter(name for item in enriched for name in item["tool_names"])
    lines.append("## 3 审批与工具")
    lines.append("")
    lines.append(f"- 审批决策数（含未处理）：{decision_count}")
    lines.append(f"- 工具调用数：{tool_count}")
    if names:
        lines.append("- 工具调用分布：" + "、".join(f"`{k}`×{v}" for k, v in names.most_common()))
    lines.append("")

    lines.append("## 4 运行明细")
    lines.append("")
    lines.append("| run_id | 类型 | 用例 | status | error_type | 耗时(s) | 回答摘要 |")
    lines.append("|---|---|---|---|---|---|---|")
    for item in enriched:
        r = item["record"]
        answer = (r.get("final_answer") or "").replace("\n", " ")[:40]
        lines.append(
            f"| {r.get('run_id')} | {r.get('kind')} | {r.get('case_id') or '-'} | "
            f"{r.get('status')} | `{item['error_type']}` | {r.get('elapsed_seconds')} | {answer} |"
        )
    lines.append("")
    lines.append("## 5 说明")
    lines.append("")
    lines.append("- 本报告由 `report_platform.py` 从原始 JSONL 与事件文件生成，数字未手工填写。")
    lines.append("- `infrastructure_error` 不计入 Agent 行为失败率。")
    lines.append("- 完整 SSE 事件见 `evidence/platform_events/`。")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(enriched)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
