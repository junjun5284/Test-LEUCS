# 平台层 Harness 运行报告

- 生成时间：2026-10-29T08:23:31.860471+00:00
- 证据来源：`harness_srs\evidence\platform_runs.jsonl` + 逐次 SSE 事件
- 运行总数：18
- 失败分层：旧记录缺 `error_type` 时，从不可变证据重新推导（原记录未修改）

## 1 失败分层

| 类型 | 次数 |
|---|---|
| `infrastructure_error` | 6 |
| `ok` | 4 |
| `model_contract_error` | 4 |
| `awaiting_approval` | 2 |
| `incomplete_stream` | 1 |
| `classification_rejected` | 1 |

## 2 用例汇总（suite）

| 用例 | n | 成功 | 成功率 | 错误类型 | 平均耗时(s) |
|---|---|---|---|---|---|
| PLAT-001 | 3 | 3 | 1.000 | ok×3 | 12.82 |
| PLAT-002 | 3 | 0 | 0.000 | awaiting_approval×2、incomplete_stream×1 | 151.04 |
| PLAT-003 | 3 | 0 | 0.000 | infrastructure_error×2、classification_rejected×1 | 63.13 |

## 3 审批与工具

- 审批决策数（含未处理）：2
- 工具调用数：36
- 工具调用分布：`system_shell_detect`×13、`web_search`×4、`task_add_batch`×3、`task_start`×3、`workspace_status`×2、`env_prober`×2、`tool_lookup`×2、`workspace_memory`×1、`task_progress`×1、`task_complete`×1、`get_helper`×1、`task_list`×1、`env_info`×1、`system_info`×1

## 4 运行明细

| run_id | 类型 | 用例 | status | error_type | 耗时(s) | 回答摘要 |
|---|---|---|---|---|---|---|
| PLT-20261027154510839064 | run | - | 200 | `infrastructure_error` | 31.33 |  |
| PLT-20261027154559904737 | run | - | 200 | `ok` | 21.38 | ok |
| PLT-20261028021540378914 | suite_run | PLAT-001 | 200 | `ok` | 10.29 | ok |
| PLT-20261028021555876300 | suite_run | PLAT-001 | 200 | `ok` | 15.48 | ok |
| PLT-20261028021608575119 | suite_run | PLAT-001 | 200 | `ok` | 12.69 | ok |
| PLT-20261028021840714532 | suite_run | PLAT-002 | 200 | `awaiting_approval` | 152.13 |  |
| PLT-20261028022111274641 | suite_run | PLAT-002 | 200 | `awaiting_approval` | 150.54 |  |
| PLT-20261028022341768733 | suite_run | PLAT-002 | 200 | `incomplete_stream` | 150.46 |  |
| PLT-20261028022612918355 | suite_run | PLAT-003 | 200 | `classification_rejected` | 151.1 |  |
| PLT-20261028022651214252 | suite_run | PLAT-003 | 502 | `infrastructure_error` | 38.25 |  |
| PLT-20261028022651268506 | suite_run | PLAT-003 | 502 | `infrastructure_error` | 0.05 |  |
| PLT-20261028022825532422 | run | - | None | `infrastructure_error` | 45.11 |  |
| PLT-20261028022856432740 | run | - | 502 | `infrastructure_error` | 0.06 |  |
| PLT-20261029080819545530 | run | - | 401 | `infrastructure_error` | 0.29 |  |
| PLT-20261029082144585361 | run | - | 200 | `model_contract_error` | 7.49 |  |
| PLT-20261029082204728237 | run | - | 200 | `model_contract_error` | 8.2 |  |
| PLT-20261029082223703442 | run | - | 200 | `model_contract_error` | 7.2 |  |
| PLT-20261029082239679016 | run | - | 200 | `model_contract_error` | 6.28 |  |

## 5 说明

- 本报告由 `report_platform.py` 从原始 JSONL 与事件文件生成，数字未手工填写。
- `infrastructure_error` 不计入 Agent 行为失败率。
- 完整 SSE 事件见 `evidence/platform_events/`。
