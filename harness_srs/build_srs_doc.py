#!/usr/bin/env python
"""Convert the SRS markdown into a styled .docx, reusing the design-doc styles.

The markdown source stays the single source of truth (it is what the verifier
reads for the version number), so the .docx is always regenerated from it
instead of being maintained by hand in parallel.

Run:
    python build_srs_doc.py
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

from build_design_doc import Doc, cell_text, no_split, set_run, HEAD_EA, BODY_EA, LATIN, LIGHT

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "01_SRS_LEUCS_Testing_Agent_Harness.md"
OUT = ROOT / "软件需求规格说明书.docx"


# --------------------------------------------------------------------------- #
# block parser
# --------------------------------------------------------------------------- #

def parse(md_text: str):
    """Turn the markdown into a flat list of (kind, payload) blocks."""
    lines = md_text.splitlines()
    blocks = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # horizontal rule
        if re.fullmatch(r"-{3,}", stripped):
            i += 1
            continue

        # fenced code
        if stripped.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append(("code", "\n".join(buf)))
            continue

        # heading
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            blocks.append(("h", (level, m.group(2).strip())))
            i += 1
            continue

        # blockquote
        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(("quote", buf))
            continue

        # table
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            blocks.append(("table", (header, rows)))
            continue

        # ordered list
        if re.match(r"^\d+\.\s+", stripped):
            buf = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                buf.append(re.sub(r"^\d+\.\s+", "", lines[i].strip()))
                i += 1
            blocks.append(("ol", buf))
            continue

        # unordered list
        if re.match(r"^[-*]\s+", stripped):
            buf = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                buf.append(re.sub(r"^[-*]\s+", "", lines[i].strip()))
                i += 1
            blocks.append(("ul", buf))
            continue

        # paragraph: consume until a blank line or a structural line
        buf = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith("#") or nxt.startswith("```")
                    or nxt.startswith(">") or nxt.startswith("|")
                    or re.match(r"^[-*]\s+", nxt) or re.match(r"^\d+\.\s+", nxt)
                    or re.fullmatch(r"-{3,}", nxt)):
                break
            buf.append(nxt)
            i += 1
        blocks.append(("p", " ".join(buf)))

    return blocks


def column_widths(header, rows):
    """Size columns by content length so wide text columns get more room."""
    cols = len(header)
    weights = []
    for c in range(cols):
        longest = len(header[c])
        for row in rows:
            if c < len(row):
                longest = max(longest, len(row[c]))
        weights.append(min(max(longest, 5), 42))
    scale = 16.0 / sum(weights)
    return [w * scale for w in weights]


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

def build_cover(d: Doc, version: str):
    doc = d.doc
    for _ in range(3):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("软件需求规格说明书"), size=30, bold=True, ea=HEAD_EA,
            color=RGBColor(0x1F, 0x3B, 0x63))

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(10)
    set_run(p.add_run("LEUCS 智能体平台测试系统（Test Harness）"), size=16, bold=True, ea=HEAD_EA)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    set_run(p.add_run("—— 测试问题、验收场景、功能与约束"), size=11.5, ea=BODY_EA,
            color=RGBColor(0x59, 0x59, 0x59))

    for _ in range(3):
        doc.add_paragraph()

    rows = [
        ("文档名称", "软件需求规格说明书（SRS）"),
        ("参考格式", "IEEE 830 中文版"),
        ("文档版本", version),
        ("描述对象", "本小组围绕 LEUCS 建立的测试系统 / 测试工程（非 LEUCS 被测系统本身）"),
        ("对应代码", "仓库 Test-LEUCS，测试工程目录 harness_srs/"),
        ("小组成员", "李彦均（1120243269）、王泽辰（1120233314）"),
        ("课程名称", "软件需求工程与设计模式"),
        ("编写日期", datetime.date.today().strftime("%Y 年 %m 月 %d 日")),
    ]
    table = doc.add_table(rows=0, cols=2)
    for k, v in rows:
        tr = table.add_row()
        no_split(tr)
        cell_text(tr.cells[0], k, size=10, bold=True, ea=HEAD_EA, align=WD_ALIGN_PARAGRAPH.CENTER)
        from build_design_doc import shade
        shade(tr.cells[0], LIGHT)
        cell_text(tr.cells[1], v, size=10)
    d._fixed_layout(table, [3.6, 10.6])
    d._borders(table)

    for _ in range(4):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("本说明书描述对象：测试系统的需求，而非 LEUCS 本身"), size=10,
            ea=BODY_EA, color=RGBColor(0x80, 0x80, 0x80))


def build_front(d: Doc, quotes, chapters, version):
    d.h1("文档信息", page_break=True)

    d.h2("0.1 文档身份")
    pairs = [
        ("文档名称", "软件需求规格说明书（LEUCS 测试系统）"),
        ("文档编号", "LEUCS-TEST-SRS-01"),
        ("版本", version),
        ("参考格式", "IEEE 830 中文版"),
        ("状态", "随最终验收材料提交"),
        ("配套文档", "《软件详细设计说明书》（软件详细设计说明书.docx）"),
        ("描述对象", "本小组自建的 LEUCS 测试系统；LEUCS 仅作为被测对象（SUT）"),
    ]
    d.kv_table(pairs)

    if quotes:
        d.h2("0.2 版本与变更说明")
        for q in quotes:
            if not q:
                continue
            d.note(q.lstrip("> ").strip())

    d.h2("0.3 章节目录")
    d.table(
        ["序", "章节", "内容提要"],
        [[str(i), title, summary] for i, (title, summary) in enumerate(chapters, 1)],
        widths=[1.0, 6.4, 8.6],
        size=8.8,
        header_size=8.8,
        align_center_cols=(0,),
    )
    d.note("提示：本目录由章节标题自动生成。Word 中可使用“视图 → 导航窗格”按标题层级跳转。")


def build_body(d: Doc, blocks, skip_titles=()):
    first_h1 = True
    for kind, payload in blocks:
        if kind == "h":
            level, text = payload
            if level == 1:
                continue  # document title, handled by the cover
            if level == 2:
                if text in skip_titles:
                    continue
                d.h1(text, page_break=not first_h1)
                first_h1 = False
            elif level == 3:
                d.h2(text)
            elif level == 4:
                d.h3(text)
            else:
                d.h4(text)
        elif kind == "p":
            d.p(payload)
        elif kind == "code":
            d.code(payload)
        elif kind == "quote":
            for q in payload:
                if q:
                    d.note(q)
        elif kind == "ul":
            d.bullets(payload, numbered=False)
        elif kind == "ol":
            d.bullets(payload, numbered=True)
        elif kind == "table":
            header, rows = payload
            # Markdown tables occasionally carry a short row; pad so every row
            # matches the header width instead of raising on cell access.
            cols = len(header)
            fixed = []
            for row in rows:
                cells = [c for c in row][:cols]
                cells += [""] * (cols - len(cells))
                fixed.append(cells)
            d.table(header, fixed,
                    widths=column_widths(header, fixed),
                    size=8.8, header_size=8.8)


def main():
    md = SRC.read_text(encoding="utf-8")
    version_match = re.search(r"版本：v([\d.]+)", md)
    version = f"v{version_match.group(1)}" if version_match else "v?"

    blocks = parse(md)

    # The first '##' headings before the first numbered chapter are the
    # document subtitle, not a chapter; they must not appear as chapters.
    chapters = []          # [(title, short description)]
    skip_titles = []
    first_numbered_seen = False
    for idx, (kind, payload) in enumerate(blocks):
        if kind != "h" or payload[0] != 2:
            continue
        title = payload[1]
        if not first_numbered_seen and not re.match(r"^\d+\.", title):
            skip_titles.append(title)
            continue
        first_numbered_seen = True
        summary = ""
        for k2, p2 in blocks[idx + 1:]:
            if k2 == "h":
                break
            if k2 == "p":
                summary = p2
                break
            if k2 in ("ul", "ol") and p2:
                summary = p2[0]
                break
        summary = re.sub(r"[*`]", "", summary)
        if len(summary) > 46:
            summary = summary[:46] + "…"
        chapters.append((title, summary))

    quotes = []
    for kind, payload in blocks:
        if kind == "quote":
            quotes = payload
            break

    # drop the leading version-note block from the body (rendered in front matter)
    seen_first = False
    trimmed = []
    for kind, payload in blocks:
        if kind == "quote" and not seen_first:
            seen_first = True
            continue
        trimmed.append((kind, payload))

    d = Doc()
    d.header_footer(f"LEUCS 测试系统 · 软件需求规格说明书 {version}", "LEUCS 测试系统")
    build_cover(d, version)
    build_front(d, quotes, chapters, version)
    build_body(d, trimmed, skip_titles)
    d.save(OUT)

    check = Document(str(OUT))
    print(f"saved: {OUT}")
    print(f"version={version} chapters={len(chapters)} "
          f"paragraphs={len(check.paragraphs)} tables={len(check.tables)} "
          f"bytes={OUT.stat().st_size}")


if __name__ == "__main__":
    main()
