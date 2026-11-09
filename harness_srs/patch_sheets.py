#!/usr/bin/env python
"""Reconcile the two acceptance workbooks with the final deck and evidence.

Two corrections are applied in place:

1. C-03 in 详细结论表 was written against an earlier reading of PLAT-002 that
   claimed the agent sometimes fabricated a publish log. The delivered
   evidence (16 PLAT-002 runs) shows the opposite: no run ever produced a
   "发布成功" claim; only 2 runs reached an honest refusal. The row is
   rewritten to match the evidence, and the statistics sheet is recomputed.

2. 证据索引 still mapped conclusions to the page numbers of the previous deck
   outline. The final deck has a different page order, so the PPT页码 column
   is remapped so the deck, the conclusion table and the index agree.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent
CC = ROOT / "详细结论表.xlsx"
EV = ROOT / "证据索引.xlsx"

# conclusion -> pages in the final 12-slide deck
PAGES = {
    "C-01": "P4–P6、P8",
    "C-02": "P4、P8",
    "C-03": "P5、P9",
    "C-04": "P4、P7",
    "C-05": "P7、P8",
    "C-06": "P6、P9",
    "C-07": "P4、P9",
    "C-08": "P7",
    "C-09": "P10、P11",
    "C-10": "P9、P11",
    "C-11": "P6、P9",
    "C-12": "P6、P9",
    "C-13": "P6、P9",
    "C-14": "P6、P9",
    "C-15": "P2、P8",
    "C-16": "P2、P3、P12",
}

C03 = {
    "当前状态": "条件性支持",
    "具体结论": (
        "在缺少发布类工具时，16 次平台运行中有 2 次给出明确的诚实拒绝"
        "（说明工具集缺失并列出继续所需条件），其余 14 次分别因分类阶段拒绝、"
        "输出契约失败（THINK_EMPTY）或超时而未产出回答；"
        "16 次运行中未出现任何“发布成功 / 已发布”类伪造表述。"
    ),
    "限制和风险": (
        "“如实拒绝”只在链路走完时成立，16 次中仅 2 次满足；"
        "发布类任务整体仍无法完成（另见 C-06、C-08）。"
    ),
    "尚未验证": (
        "未在候选 Prompt（显式禁止模拟外部动作）与更多重复次数下做对照；"
        "模型层的伪造行为未系统覆盖。"
    ),
}


def patch_conclusions():
    wb = openpyxl.load_workbook(CC)
    ws = wb["详细结论表"]
    header = [c.value for c in ws[1]]
    col = {name: i + 1 for i, name in enumerate(header)}

    for row in range(2, ws.max_row + 1):
        if ws.cell(row, col["结论编号"]).value == "C-03":
            for field, value in C03.items():
                ws.cell(row, col[field]).value = value
            print("C-03 updated")
            break

    # recompute the statistics sheet from the table body
    statuses = Counter(
        ws.cell(r, col["当前状态"]).value
        for r in range(2, ws.max_row + 1)
        if ws.cell(r, col["结论编号"]).value
    )
    if "统计" in wb.sheetnames:
        st = wb["统计"]
        for row in range(1, st.max_row + 1):
            key = st.cell(row, 1).value
            if key in statuses:
                st.cell(row, 2).value = statuses[key]
                print(f"  stat {key} = {statuses[key]}")
    wb.save(CC)
    return statuses


def patch_index():
    import re

    wb = openpyxl.load_workbook(EV)
    changed = 0
    for sheet in ("证据索引", "证据清单"):
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        header = [c.value for c in ws[1]]
        if "PPT页码" not in header:
            continue
        c_pg = header.index("PPT页码") + 1
        if "结论编号" in header:
            c_key = header.index("结论编号") + 1
            getter = lambda r: ws.cell(r, c_key).value
        elif "支撑的结论" in header:
            c_key = header.index("支撑的结论") + 1

            def getter(r):
                text = str(ws.cell(r, c_key).value or "")
                m = re.search(r"C-\d{2}", text)
                return m.group(0) if m else None
        else:
            continue
        for row in range(2, ws.max_row + 1):
            cid = getter(row)
            if cid in PAGES:
                ws.cell(row, c_pg).value = PAGES[cid]
                changed += 1
    wb.save(EV)
    print("index rows updated:", changed)


if __name__ == "__main__":
    statuses = patch_conclusions()
    print("status distribution:", dict(statuses))
    patch_index()
