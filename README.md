# Test-LEUCS

LEUCS 智能体平台（SUT）的**测试系统 / 测试工程**。被测对象是 LEUCS，本仓库提交的是本组编写的测试代码与证据。

## 目录

| 路径 | 内容 |
|---|---|
| `harness_srs/` | 测试工程本体：内核、适配器、平台层执行器、探针、回归判定、变异测试与证据 |
| `harness_srs/README.md` | 工程说明与快速开始 |
| `harness_srs/01_SRS_LEUCS_Testing_Agent_Harness.md` | 软件需求规格说明书源文件（FR-01～FR-43） |
| `harness_srs/02_current_issue_list_and_prompt_methods.md` | 问题列表（ISSUE-001～033）与 Prompt 方法 |
| `harness_srs/docs/ADAPTER_GUIDE.md` | 适配器开发指南 |
| `harness_srs/docs/答辩稿.md` | 答辩讲解稿 |
| `harness_srs/tests/` | 99 项自测 |
| `harness_srs/mutants/` | 对测试器自身的变异测试（核心 12 + 平台层 14） |

## 最终验收材料

| 材料 | 文件 |
|---|---|
| 软件需求规格说明书 | `harness_srs/软件需求规格说明书.docx` |
| 软件详细设计说明书 | `harness_srs/软件详细设计说明书.docx` |
| 最终验收 PPT | `harness_srs/最终验收PPT.pptx` |
| 最终验收 PPT（PDF 备份） | `harness_srs/最终验收PPT.pdf` |
| 详细结论表（16 条结论） | `harness_srs/详细结论表.xlsx` |
| 证据索引（24 条证据） | `harness_srs/证据索引.xlsx` |

语音版（`最终验收PPT语音版.mp4`）体积较大，未纳入 git；它与 PPT 一并随验收压缩包提交。

## 快速开始

```bash
python harness_srs/harness_cli.py adapters
python harness_srs/harness_cli.py --adapter leucs cases
python harness_srs/verify_delivery.py          # 20 项交付自检（离线）
python -m unittest discover -s harness_srs/tests -p "test_*.py"
```

运行平台层测试需要设置环境变量 `LEUCS_PLATFORM_TOKEN`。仓库中不含任何凭据。

## 文档生成

`build_design_doc.py`、`build_srs_doc.py`、`build_ppt.py`、`build_acceptance_sheets.py`
从仓库中的源数据重新生成对应交付物；`assemble_package.py` 组装最终验收压缩包。
