# LEUCS Harness 统一回归报告

- 生成时间：2026-11-04T06:20:36.873358+00:00
- 模式：platform-only

## 1 健康探针

- 结论：`healthy`
- 退出码：0

## 2 平台层

- 运行数：15
- 失败分层：`model_contract_error`×15

| 用例 | n | 成功 | 错误类型 |
|---|---|---|---|
| PLAT-001 | 3 | 0 | model_contract_error×3 |
| PLAT-002 | 3 | 0 | model_contract_error×3 |
| PLAT-003 | 3 | 0 | model_contract_error×3 |
| PLAT-004 | 3 | 0 | model_contract_error×3 |
| PLAT-005 | 3 | 0 | model_contract_error×3 |

## 3 模型层

- 退出码：None
- 新增记录：0

## 4 结论边界

- `infrastructure_error` 不计入 Agent 行为失败率。
- 本报告只覆盖本次执行的用例与配置，不外推到其他模型、挂载模式或工具组合。
- 平台不可用时模型层结论不具可比性，应先确认健康探针通过。

原始证据：`evidence/platform_runs.jsonl`、`evidence/platform_probe.jsonl`。
