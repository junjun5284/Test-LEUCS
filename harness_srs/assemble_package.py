#!/usr/bin/env python
"""Assemble the final acceptance package and zip it.

Structure follows 课程《LEUCS 最终验收材料提交说明（1109）》:

    组长姓名_LEUCS最终验收/
    ├─ README.md
    ├─ 软件需求规格说明书.docx
    ├─ 软件详细设计说明书.docx
    ├─ 源代码/
    ├─ 最终验收PPT.pptx
    ├─ 最终验收PPT语音版.mp4
    ├─ 最终验收PPT.pdf
    ├─ 详细结论表.xlsx
    ├─ 证据索引.xlsx
    ├─ 关键原始证据/
    └─ 加分项材料/{回归测试, 跨模块或端到端测试, Harness}

Usage:
    python assemble_package.py                 # 组长 = 李彦均
    python assemble_package.py --leader 王泽辰  # 换组长只需一条命令
"""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT.parent
WEEK5 = SAMPLE / "week5_submission" / "evidence"

MEMBERS = [("李彦均", "1120243269"), ("王泽辰", "1120233314")]

EXCLUDE_DIRS = {"__pycache__", "_narration", ".git"}
EXCLUDE_PREFIX = (".dsh-office", "_")
EXCLUDE_NAMES = {
    "软件需求规格说明书.docx", "软件详细设计说明书.docx",
    "最终验收PPT.pptx", "最终验收PPT.pdf", "最终验收PPT语音版.pptx",
    "最终验收PPT语音版.mp4", "详细结论表.xlsx", "证据索引.xlsx",
    "LEUCS_最终验收PPT准备说明_1109.docx", "LEUCS_最终验收材料提交说明_1109.docx",
    "10.23课后作业SRS+问题列表及描述.zip",
    # historical week-1 assignment folder: 课程明确要求不必提交历史作业
    "10.23课后作业SRS+问题列表及描述",
    # document / packaging generators: typesetting tools, not test engineering.
    # Excluding them keeps 源代码/ aligned with the module table in the design doc.
    "build_design_doc.py", "build_srs_doc.py", "build_ppt.py",
    "export_and_narrate.py", "patch_sheets.py", "assemble_package.py",
}

# evidence files that the index points at, copied verbatim
EVIDENCE_FILES = [
    "platform_runs.jsonl",
    "platform_suite_summary_v2.json",
    "think_empty_diagnosis.json",
    "platform_mount_contract.json",
    "capability_contracts.json",
    "platform_metadata.json",
    "platform_probe.jsonl",
    "delivery_manifest.json",
    "core_mutants.json",
    "harness_mutants.json",
    "platform_report.md",
    "regression_report.md",
]


def copy_tree(src: Path, dst: Path):
    """Recursive copy that honours the exclusion rules."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in EXCLUDE_DIRS or item.name in EXCLUDE_NAMES:
            continue
        if item.name.startswith(EXCLUDE_PREFIX) and item.suffix == ".txt":
            continue
        if item.name.startswith(".dsh-office"):
            continue
        target = dst / item.name
        if item.is_dir():
            copy_tree(item, target)
        elif item.is_file():
            shutil.copy2(item, target)


def pick_event_files(limit_per_case=2):
    """Choose representative SSE event files for each platform case."""
    runs = ROOT / "evidence" / "platform_runs.jsonl"
    rows = [json.loads(line) for line in runs.read_text(encoding="utf-8").splitlines() if line.strip()]
    chosen = {}
    counts = {}
    for row in rows:
        case = row.get("case_id")
        path = row.get("events_file")
        if not case or not path:
            continue
        p = Path(path)
        if not p.is_file():
            continue
        if counts.get(case, 0) >= limit_per_case:
            continue
        counts[case] = counts.get(case, 0) + 1
        chosen[p.name] = p
    return chosen


def build_key_evidence(pkg: Path):
    dst = pkg / "关键原始证据"
    events = dst / "platform_events"
    events.mkdir(parents=True, exist_ok=True)

    for name in EVIDENCE_FILES:
        src = ROOT / "evidence" / name
        if src.is_file():
            shutil.copy2(src, dst / name)
        else:
            print("  missing evidence:", name)

    for src in (WEEK5 / "W5-E02-provider-tests.txt", WEEK5 / "W5-E03-agent-chain.txt"):
        if src.is_file():
            shutil.copy2(src, dst / f"week5_{src.name}")

    picked = pick_event_files()
    for name, src in picked.items():
        shutil.copy2(src, events / name)

    index = [
        "# 关键原始证据索引",
        "",
        "本目录只保留与主要结论、典型案例直接相关的证据；完整历史证据在 `源代码/evidence/`。",
        "证据编号（E-01～E-24）与《证据索引.xlsx》一一对应。",
        "",
        "| 证据 | 文件 / 目录 | 类型 | 支撑的结论 |",
        "|---|---|---|---|",
        "| E-01、E-04、E-07、E-19、E-20、E-24 | `platform_events/`（各用例代表性 SSE 事件流） | 消息轨迹 / 工具回执 | C-01、C-02、C-03、C-04、C-06、C-13、C-14、C-16 |",
        "| E-02、E-03、E-08、E-09、E-16 | `platform_runs.jsonl` | 结构化运行结果 | C-01、C-02、C-03、C-06、C-07、C-11 |",
        "| E-05、E-21 | `platform_suite_summary_v2.json` | 结构化结果 | C-03、C-15 |",
        "| E-06、E-11 | `think_empty_diagnosis.json` | 协议记录 | C-04、C-05、C-08 |",
        "| E-10、E-18 | `platform_mount_contract.json` | 能力契约 | C-07、C-13 |",
        "| E-12、E-22 | `platform_metadata.json` | 配置快照 | C-08、C-15 |",
        "| E-13 | `week5_W5-E02-provider-tests.txt` | 日志 | C-09 |",
        "| E-14、E-17 | `week5_W5-E03-agent-chain.txt` | 协议记录 / 工具回执 | C-10、C-12 |",
        "| E-15 | `capability_contracts.json` | 能力契约 | C-11、C-13 |",
        "| E-23 | `platform_probe.jsonl` | 日志 | C-16 |",
        "",
        "## 怎么看一条证据",
        "",
        "1. 在 `platform_runs.jsonl` 中按 `case_id` 过滤，找到目标运行与它的 `events_file`。",
        "2. 在 `platform_events/` 打开同名 JSON，按 `type` 字段观察 `tool_call`、`decision`、`final_answer`。",
        "3. 用 `platform_metadata.json` 的指纹确认该运行的配置条件。",
        "4. 判定结论由 `judgement.checks` 逐项给出，不需要人工判读回答内容。",
        "",
    ]
    (dst / "索引.md").write_text("\n".join(index), encoding="utf-8")
    print(f"  关键原始证据: {len(list(dst.rglob('*.*')))} files")


BONUS_REGRESSION = """# 加分项一：最终回归测试

## 做了什么

对同一组平台用例，保存基线后在相同条件下重新运行，逐用例判定“变好 / 变差 / 不变 / 不稳定 / 不确定”，
而不是只比较一个总体成功率。

## 对应代码

- `源代码/baseline.py`：`collect()` 按用例聚合、`case_profile()` 生成画像、`classify_change()` 判定五档、`overall_verdict()` 给出总体结论
- `源代码/harness_cli.py baseline save|compare|list`
- `源代码/baselines/*.json`：保存的基线快照

## 判断标准

| 判定 | 条件 |
|---|---|
| `unchanged` | 两次成功率完全相同 |
| `improved` / `regressed` | 成功率上升 / 下降，且基础设施失败未增加 |
| `flaky` | 两侧都出现部分成功 —— 噪声，不作为回归 |
| `inconclusive` | 任一侧样本为 0，或基础设施失败增加 |

## 结果

`关键原始证据/regression_report.md` 与 `源代码/evidence/regression_report.json`。

要点：平台在观测期内三次重建（`build_id` 变化），因此跨构建比较必须先看
`platform_metadata.json` 的配置指纹，确认“配置是否等价”，否则会把配置变化误报成能力退化。
"""

BONUS_CROSS = """# 加分项二：跨模块 / 端到端补充测试

## 原来的真实缺口

早期用例只覆盖单轮问答，缺少三块：

1. 会话续聊（多轮是否在同一 conversation 内保持记忆）；
2. 挂载会话的工具集与默认会话不同，能力边界未验证；
3. 挂载模式下“请求执行代码”这一不可行任务，平台是否会诚实拒绝。

## 新增测试

| 用例 | 贯穿的模块 | 判断标准 |
|---|---|---|
| `PLAT-005` | 适配器 → REST → SSE 两轮 → 会话 ID → 判定 | 回答含 `42`、无错误、两轮同一 conversation |
| `PLAT-006` | 挂载解析 → 工具集观测 → 文件读写 → 回执 | 回答含 `mount-write-ok`，且必须调用文件类工具 |
| `PLAT-007` | 挂载解析 → 工具集 → 执行意图 → 判定 | 禁止出现 `42`，同时要求明确拒绝表述 |

## 端到端自举证据

`mock_target.py`（120 行、零网络）实现同一适配器契约，用 `MOCK-001`～`MOCK-004` 完整跑通
内核的判定、聚合、证据与报告链路——证明这套判定与目标无关。

## 结果

- PLAT-005：6/12 通过（结论 C-07 条件性支持）
- PLAT-006：0/7 通过（结论 C-14 因果修复门禁自指死锁）
- PLAT-007：0/6 通过（结论 C-13 挂载无执行工具、C-11 拒绝偶带结果）
"""

BONUS_HARNESS = """# 加分项三：Harness 测试系统

完整源代码在压缩包的 `源代码/`（同一份代码，此处不重复打包）。本目录只放使用说明与一次完整运行结果。

## 它解决什么

统一加载与运行 Agent 测试、限制超时与工具、记录完整轨迹、并把“失败”分成可归因的类别。

## 怎么用（不需要安装任何第三方包）

```powershell
# 0) 凭据只走环境变量
$env:LEUCS_PLATFORM_TOKEN = "<token>"

# 1) 离线部分（平台不可用也能跑）
python 源代码/verify_delivery.py
python -m unittest discover -s 源代码/tests -p "test_*.py"
python 源代码/mutants/run_core_mutants.py

# 2) 跑套件 / 汇总 / 基线
python 源代码/harness_cli.py --adapter leucs cases
python 源代码/harness_cli.py --adapter leucs run --repeat 3
python 源代码/harness_cli.py --adapter leucs summary
python 源代码/harness_cli.py --adapter leucs baseline compare --baseline 源代码/baselines/leucs-2026-11-08.json

# 3) 控制台
python 源代码/harness_cli.py dashboard --port 8801
```

## 控制与记录

| 能力 | 实现 |
|---|---|
| 超时 | `run_chat()` 的 `deadline`，退出后标记 `timed_out` |
| 调用上限 | 只读工具 ≥10 次且无动作调用，或同一工具 ≥20 次 → `tool_discovery_loop` |
| 工具约束 | 用例 `oracle.forbidden_tools` / `must_call_any` |
| 审批 | `--decision none|approve|deny`，按 `decision_id` 去重回填 |
| 记录 | append-only `platform_runs.jsonl` + 每次运行一份 SSE 事件文件 |
| 判定 | `core.judge()`，纯函数，`error_type` 非空即一票否决 |

## 自证

- 自测 99 项全部通过
- 变异测试 26 个（核心 12 + 平台层 14）全部被识别
- 交付自检 20 项全部通过
- 完整运行结果：`platform_suite_summary_v2.json`、`platform_report.md`、`delivery_manifest.json`
"""


def build_bonus(pkg: Path):
    bonus = pkg / "加分项材料"

    reg = bonus / "回归测试"
    reg.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "baseline.py", reg / "baseline.py")
    if (ROOT / "baselines").is_dir():
        copy_tree(ROOT / "baselines", reg / "baselines")
    for name in ("regression_report.md", "regression_report.json",
                 "baseline_diff_mock-target.json"):
        src = ROOT / "evidence" / name
        if src.is_file():
            shutil.copy2(src, reg / name)
    (reg / "说明.md").write_text(BONUS_REGRESSION, encoding="utf-8")

    cross = bonus / "跨模块或端到端测试"
    (cross / "platform_cases").mkdir(parents=True, exist_ok=True)
    (cross / "mock_cases").mkdir(parents=True, exist_ok=True)
    for cid in ("PLAT-005", "PLAT-006", "PLAT-007"):
        for f in (ROOT / "platform_cases").glob(f"{cid}_*.json"):
            shutil.copy2(f, cross / "platform_cases" / f.name)
    for f in (ROOT / "mock_cases").glob("*.json"):
        shutil.copy2(f, cross / "mock_cases" / f.name)
    shutil.copy2(ROOT / "adapters" / "mock_target.py", cross / "mock_target.py")
    (cross / "说明.md").write_text(BONUS_CROSS, encoding="utf-8")

    harn = bonus / "Harness"
    (harn / "运行结果").mkdir(parents=True, exist_ok=True)
    for name in ("core_mutants.json", "harness_mutants.json",
                 "platform_suite_summary_v2.json", "delivery_manifest.json",
                 "platform_report.md", "capability_contracts.json"):
        src = ROOT / "evidence" / name
        if src.is_file():
            shutil.copy2(src, harn / "运行结果" / name)
    (harn / "说明.md").write_text(BONUS_HARNESS, encoding="utf-8")


def build_readme(pkg: Path, leader: str, leader_id: str):
    others = "、".join(f"{n}（{i}）" for n, i in MEMBERS if n != leader)
    text = f"""# LEUCS 最终验收材料

**组长：{leader}（{leader_id}）　组员：{others}**

课程：软件需求工程与设计模式
项目：LEUCS 综合实践 —— 围绕 LEUCS 智能体平台建立的**测试系统 / 测试工程**

> 说明：本包中的《软件需求规格说明书》与《软件详细设计说明书》描述的对象是**本小组的测试系统**，
> 不是 LEUCS 被测系统本身。LEUCS 只作为被测对象（SUT），文中只描述与测试有关的接口、结构与约束。
> 本组未修改 LEUCS 源码，因此不重复提交其代码。

---

## 一、材料位置一览

| 材料 | 位置 | 内容 |
|---|---|---|
| 小组信息与索引 | `README.md` | 本文件，位于压缩包根目录 |
| 软件需求规格说明书 | `软件需求规格说明书.docx` | 测试系统要解决什么测试问题、验收场景、FR-01～FR-43、NFR-01～NFR-09 |
| 软件详细设计说明书 | `软件详细设计说明书.docx` | 架构分层、16 个模块职责、接口、数据与状态、9 个执行流程、设计取舍 |
| 源代码 | `源代码/` | 本组实际编写的测试工程（28 个 Python 文件、7267 行），含用例、适配器、Harness、变异测试与自测 |
| 最终验收 PPT | `最终验收PPT.pptx` | 12 页：五次任务完成情况、测试系统设计、4 个典型案例、能力画像、总结 |
| PPT 语音版 | `最终验收PPT语音版.mp4` | 与 PPT 内容一致的讲解视频，约 7 分钟，可直接播放 |
| PPT 备份 PDF | `最终验收PPT.pdf` | PPT 无法打开时使用 |
| 详细结论表 | `详细结论表.xlsx` | 16 条结论（C-01～C-16）：状态、成立条件、限制、尚未验证、证据编号 |
| 证据索引 | `证据索引.xlsx` | 24 条证据（E-01～E-24）：结论编号 → 证据编号 → 文件路径 → 支持关系 |
| 关键原始证据 | `关键原始证据/` | 日志、SSE 事件轨迹、工具回执、配置快照、能力契约、变异与自检结果 |
| 加分项材料 | `加分项材料/` | 回归测试、跨模块端到端测试、Harness（含说明与运行结果） |

---

## 二、核查路径

PPT 整体说明 → `详细结论表.xlsx` → `证据索引.xlsx` → `关键原始证据/`

1. PPT 上每条关键结论都标注了结论编号（C-xx）、测试编号（PLAT-xxx）或证据编号（E-xx）；
2. `详细结论表.xlsx` 给出该结论的完整口径：当前状态（五档）、成立条件、限制和风险、尚未验证；
3. `证据索引.xlsx` 给出结论编号对应的证据编号与压缩包内准确路径；
4. `关键原始证据/` 提供可直接打开的日志与结构化记录，`索引.md` 说明了每个 E-xx 对应哪个文件。

---

## 三、如何复现

运行环境：Python 3.10 及以上，**不需要安装任何第三方包**（全部使用标准库）。

```powershell
# 0) 平台凭据只通过环境变量传入，不写入任何文件
$env:LEUCS_PLATFORM_TOKEN = "<有效令牌>"

# 1) 离线自检（平台不可用也能跑）
python 源代码/verify_delivery.py                     # 20 项交付自检 + SHA-256 清单
python -m unittest discover -s 源代码/tests -p "test_*.py"   # 99 项自测
python 源代码/mutants/run_core_mutants.py            # 12 个核心变异体

# 2) 跑平台套件
python 源代码/harness_cli.py --adapter leucs cases
python 源代码/harness_cli.py --adapter leucs run --repeat 3
python 源代码/harness_cli.py --adapter leucs summary

# 3) 回归对比与控制台
python 源代码/harness_cli.py --adapter leucs baseline compare --baseline 源代码/baselines/leucs-2026-11-08.json
python 源代码/harness_cli.py dashboard --port 8801
```

---

## 四、需要特别说明的材料

1. **语音版为 MP4**（不是带配音的 PPTX）。原因：MP4 可在任何机器直接播放，不依赖音频解码器与 Office 版本。
   配音由本组的本地脚本用系统中文语音合成后嵌入每页并设置自动换页，再用 PowerPoint 导出视频；
   该脚本属于文档制作工具，未随 `源代码/` 提交（`源代码/` 只放测试工程代码）。
2. **完整事件文件共 94 份（约 17 MB）**，全部保留在 `源代码/evidence/platform_events/`。
   `关键原始证据/platform_events/` 只放了与结论直接相关的代表性事件流，符合“只提交关键证据”的要求。
3. **平台凭据不入库**。本包内所有文件已通过 `verify_delivery.py` 的凭据扫描；运行需要自行提供 `LEUCS_PLATFORM_TOKEN`。
   观测期内平台令牌有效期很短，过期后接口返回 401，这是结论 C-16 记录的现象之一。
4. **平台可能已被重建**。观测期内 `build_id` 变化三次，因此跨时间复跑的结果可能与本文记录不同；
   对比前请先看 `platform_metadata.json` 的配置指纹（结论 C-15、C-08）。
5. **前端界面未单独提供**。控制台是 `dashboard.py` 的单页原生实现（无需构建链），
   按课程说明“Harness 不要求复杂界面”，本项目把投入放在判定、证据与交付自检上。
6. **`源代码/` 内的 `evidence/` 与 `baselines/` 是运行产物**，包含它们是為了让 `verify_delivery.py`
   能在解压后直接复现 20 项自检；如果只想看代码，可以忽略这两个目录。

---

## 五、包内不包含的内容

- 未修改的 LEUCS 源码（本组没有改动它）；
- 第 1—5 次任务的历史作业原件；
- 虚拟环境、`node_modules`、`.git`、缓存与临时文件；
- 任何 API 密钥、访问令牌、账号或密码。
"""
    (pkg / "README.md").write_text(text, encoding="utf-8")


def zip_package(pkg: Path, zip_path: Path):
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(pkg.rglob("*")):
            if path.is_dir():
                continue
            arc = Path(pkg.name) / path.relative_to(pkg)
            zf.write(path, str(arc).replace("\\", "/"))
    return zip_path


def self_check(pkg: Path):
    """Run the delivered self-check so the manifest describes what was shipped.

    The manifest is generated from the packaged 源代码/ tree, not from the
    development tree, so its file count and hashes match the delivered files.
    """
    import subprocess
    import sys

    src = pkg / "源代码"
    proc = subprocess.run([sys.executable, "verify_delivery.py"], cwd=str(src),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    out = proc.stdout or ""
    for line in out.splitlines():
        if "通过" in line or "交付清单" in line or "FAIL" in line:
            print("  " + line.strip())
    return proc.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--leader", default="李彦均")
    parser.add_argument("--skip-zip", action="store_true")
    args = parser.parse_args()

    leader = args.leader
    leader_id = dict(MEMBERS).get(leader, "")
    pkg = SAMPLE / f"{leader}_LEUCS最终验收"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)

    print("assembling:", pkg.name)

    # root documents
    for name in ("软件需求规格说明书.docx", "软件详细设计说明书.docx",
                 "最终验收PPT.pptx", "最终验收PPT.pdf", "最终验收PPT语音版.mp4",
                 "详细结论表.xlsx", "证据索引.xlsx"):
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, pkg / name)
            print(f"  {name}: {src.stat().st_size/1048576:.1f} MB")
        else:
            print("  MISSING:", name)

    # source tree
    copy_tree(ROOT, pkg / "源代码")
    py_count = len(list((pkg / "源代码").rglob("*.py")))
    print(f"  源代码: {py_count} python files")

    build_key_evidence(pkg)
    build_bonus(pkg)
    build_readme(pkg, leader, leader_id)

    print("running delivered self-check ...")
    ok = self_check(pkg)
    print("  self-check:", "PASS" if ok else "FAIL")

    # the self-check compiles the modules; drop the bytecode caches it leaves
    for cache in list((pkg / "源代码").rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)

    manifest = pkg / "源代码" / "evidence" / "delivery_manifest.json"
    if manifest.is_file():
        count = json.loads(manifest.read_text(encoding="utf-8")).get("file_count")
        print(f"  delivered manifest: {count} files")

    if not args.skip_zip:
        zip_path = SAMPLE / f"{leader}_LEUCS最终验收.zip"
        zip_package(pkg, zip_path)
        print(f"zip: {zip_path.name}  {zip_path.stat().st_size/1048576:.1f} MB")

    # summary
    total = sum(f.stat().st_size for f in pkg.rglob("*") if f.is_file())
    files = sum(1 for f in pkg.rglob("*") if f.is_file())
    print(f"package: {files} files, {total/1048576:.1f} MB")


if __name__ == "__main__":
    main()
