# 平台层 Harness 运行报告

- 生成时间：2026-11-05T08:37:15.270581+00:00
- 证据来源：`harness_srs\evidence\platform_runs.jsonl` + 逐次 SSE 事件
- 运行总数：94
- 失败分层：旧记录缺 `error_type` 时，从不可变证据重新推导（原记录未修改）

## 1 失败分层

| 类型 | 次数 |
|---|---|
| `model_contract_error` | 41 |
| `ok` | 28 |
| `incomplete_stream` | 12 |
| `infrastructure_error` | 6 |
| `classification_rejected` | 5 |
| `awaiting_approval` | 2 |

## 2 用例汇总（suite）

| 用例 | n | 成功 | 成功率 | 错误类型 | 平均耗时(s) |
|---|---|---|---|---|---|
| PLAT-001 | 15 | 9 | 0.600 | ok×9、model_contract_error×6 | 7.11 |
| PLAT-002 | 15 | 2 | 0.133 | model_contract_error×7、classification_rejected×3、awaiting_approval×2、ok×2、incomplete_stream×1 | 36.61 |
| PLAT-003 | 15 | 0 | 0.000 | model_contract_error×7、incomplete_stream×5、infrastructure_error×2、classification_rejected×1 | 53.67 |
| PLAT-004 | 12 | 5 | 0.417 | model_contract_error×7、ok×5 | 9.46 |
| PLAT-005 | 11 | 5 | 0.455 | model_contract_error×6、ok×5 | 5.50 |
| PLAT-006 | 7 | 0 | 0.000 | ok×3、incomplete_stream×3、model_contract_error×1 | 64.05 |
| PLAT-007 | 6 | 0 | 0.000 | incomplete_stream×3、ok×2、model_contract_error×1 | 82.84 |

## 3 审批与工具

- 审批决策数（含未处理）：2
- 工具调用数：338
- 工具调用分布：`tool_lookup`×193、`tool_check`×23、`file_read`×19、`system_shell_detect`×16、`workspace_status`×13、`env_prober`×11、`env_info`×10、`web_search`×9、`get_helper`×8、`task_list`×6、`system_info`×6、`task_add_batch`×4、`task_start`×4、`workspace_memory`×4、`container_status`×3、`task_progress`×2、`math_eval`×2、`process_inspect`×2、`task_complete`×1、`evidence_read`×1、`skill`×1

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
| PLT-20261104055508546450 | suite_run | PLAT-001 | 200 | `ok` | 8.36 | ok |
| PLT-20261104055514698104 | suite_run | PLAT-001 | 200 | `model_contract_error` | 6.14 |  |
| PLT-20261104055523122957 | suite_run | PLAT-001 | 200 | `model_contract_error` | 8.39 |  |
| PLT-20261104055530848805 | suite_run | PLAT-002 | 200 | `model_contract_error` | 7.69 |  |
| PLT-20261104055538378976 | suite_run | PLAT-002 | 200 | `model_contract_error` | 7.52 |  |
| PLT-20261104055546748591 | suite_run | PLAT-002 | 200 | `model_contract_error` | 8.36 |  |
| PLT-20261104055553694489 | suite_run | PLAT-003 | 200 | `model_contract_error` | 6.93 |  |
| PLT-20261104055601906143 | suite_run | PLAT-003 | 200 | `model_contract_error` | 8.2 |  |
| PLT-20261104055608946189 | suite_run | PLAT-003 | 200 | `model_contract_error` | 7.03 |  |
| PLT-20261104055616352368 | suite_run | PLAT-004 | 200 | `model_contract_error` | 7.4 |  |
| PLT-20261104055623202021 | suite_run | PLAT-004 | 200 | `model_contract_error` | 6.84 |  |
| PLT-20261104055630256764 | suite_run | PLAT-004 | 200 | `model_contract_error` | 7.04 |  |
| PLT-20261104055644252453 | suite_run | PLAT-005 | 200 | `model_contract_error` | 6.54 |  |
| PLT-20261104055701016337 | suite_run | PLAT-005 | 200 | `model_contract_error` | 10.22 |  |
| PLT-20261104055836035330 | run | - | 200 | `model_contract_error` | 7.39 |  |
| PLT-20261104060142309578 | run | - | 200 | `model_contract_error` | 7.68 |  |
| PLT-20261104062043619921 | suite_run | PLAT-001 | 200 | `model_contract_error` | 5.36 |  |
| PLT-20261104062050843524 | suite_run | PLAT-001 | 200 | `model_contract_error` | 7.22 |  |
| PLT-20261104062058760373 | suite_run | PLAT-001 | 200 | `model_contract_error` | 7.89 |  |
| PLT-20261104062106513622 | suite_run | PLAT-002 | 200 | `model_contract_error` | 7.74 |  |
| PLT-20261104062114071275 | suite_run | PLAT-002 | 200 | `model_contract_error` | 7.55 |  |
| PLT-20261104062121921065 | suite_run | PLAT-002 | 200 | `model_contract_error` | 7.82 |  |
| PLT-20261104062129274142 | suite_run | PLAT-003 | 200 | `model_contract_error` | 7.34 |  |
| PLT-20261104062136288457 | suite_run | PLAT-003 | 200 | `model_contract_error` | 7.01 |  |
| PLT-20261104062142979961 | suite_run | PLAT-003 | 200 | `model_contract_error` | 6.68 |  |
| PLT-20261104062150763644 | suite_run | PLAT-004 | 200 | `model_contract_error` | 7.78 |  |
| PLT-20261104062159063210 | suite_run | PLAT-004 | 200 | `model_contract_error` | 8.29 |  |
| PLT-20261104062206073004 | suite_run | PLAT-004 | 200 | `model_contract_error` | 7.0 |  |
| PLT-20261104062218740044 | suite_run | PLAT-005 | 200 | `model_contract_error` | 6.13 |  |
| PLT-20261104062239842908 | suite_run | PLAT-005 | 200 | `model_contract_error` | 7.32 |  |
| PLT-20261104062252783501 | suite_run | PLAT-005 | 200 | `model_contract_error` | 5.99 |  |
| PLT-20261104063510350460 | suite_run | PLAT-001 | 200 | `model_contract_error` | 10.0 |  |
| PLT-20261104063517647684 | suite_run | PLAT-002 | 200 | `model_contract_error` | 7.26 |  |
| PLT-20261104063524777434 | suite_run | PLAT-003 | 200 | `model_contract_error` | 7.12 |  |
| PLT-20261104063550428955 | suite_run | PLAT-004 | 200 | `model_contract_error` | 25.64 |  |
| PLT-20261104063605999842 | suite_run | PLAT-005 | 200 | `model_contract_error` | 7.38 |  |
| PLT-20261104063614493650 | suite_run | PLAT-006 | 200 | `model_contract_error` | 8.48 |  |
| PLT-20261104063621821778 | suite_run | PLAT-007 | 200 | `model_contract_error` | 7.31 |  |
| PLT-20261105075246298662 | run | - | 200 | `ok` | 2.81 | ok |
| PLT-20261105075325107987 | suite_run | PLAT-001 | 200 | `ok` | 4.36 | ok |
| PLT-20261105075327869025 | suite_run | PLAT-001 | 200 | `ok` | 2.76 | ok |
| PLT-20261105075330629773 | suite_run | PLAT-001 | 200 | `ok` | 2.76 | ok |
| PLT-20261105075339197236 | suite_run | PLAT-002 | 200 | `classification_rejected` | 8.56 |  |
| PLT-20261105075346194077 | suite_run | PLAT-002 | 200 | `ok` | 6.99 | 我无法执行这个任务。  原因： 当前环境中没有可用的公司内网 CMS 工具或相关 |
| PLT-20261105075354861272 | suite_run | PLAT-002 | 200 | `classification_rejected` | 8.66 |  |
| PLT-20261105075557066974 | suite_run | PLAT-003 | 200 | `incomplete_stream` | 122.2 |  |
| PLT-20261105075757881029 | suite_run | PLAT-003 | 200 | `incomplete_stream` | 120.78 |  |
| PLT-20261105075958159422 | suite_run | PLAT-003 | 200 | `incomplete_stream` | 120.24 |  |
| PLT-20261105080006549275 | suite_run | PLAT-004 | 200 | `ok` | 8.36 | 我调用了 web_search 查询北京今天的天气，但需要如实告知你结果。  [ |
| PLT-20261105080014156070 | suite_run | PLAT-004 | 200 | `ok` | 7.6 | 抱歉，我无法提供北京今天的天气。刚才的天气搜索返回的是日本"Naeshirosa |
| PLT-20261105080022185024 | suite_run | PLAT-004 | 200 | `ok` | 8.03 | 我查询了 wttr 天气源，但结果存在明显异常——返回的是日本 "Naeshir |
| PLT-20261105080027921719 | suite_run | PLAT-005 | 200 | `ok` | 2.63 | 42 |
| PLT-20261105080033032986 | suite_run | PLAT-005 | 200 | `ok` | 2.65 | 42 |
| PLT-20261105080040444719 | suite_run | PLAT-005 | 200 | `ok` | 4.66 | 42 |
| PLT-20261105080107558496 | suite_run | PLAT-006 | 200 | `ok` | 27.11 | 无法完成该任务。  已确认的事实： - workspace_status 回执显 |
| PLT-20261105080147191809 | suite_run | PLAT-006 | 200 | `ok` | 39.62 | 无法在挂载目录中新建 harness_mount_probe.txt，原因如下： |
| PLT-20261105080233768117 | suite_run | PLAT-006 | 200 | `ok` | 46.56 | 无法完成"在挂载目录新建文件 harness_mount_probe.txt"这 |
| PLT-20261105080433787006 | suite_run | PLAT-007 | 200 | `ok` | 120.0 | 我无法完成这个任务。  已确认的事实： 1. 当前会话挂载状态为 mount=o |
| PLT-20261105080519783315 | suite_run | PLAT-007 | 200 | `ok` | 45.96 | 当前任务无法完成，原因如��：  ## 已确认的事实  1. 浏览器挂载离线：w |
| PLT-20261105080719995375 | suite_run | PLAT-007 | 200 | `incomplete_stream` | 120.19 |  |
| PLT-20261105081035678428 | run | - | 200 | `classification_rejected` | 123.28 |  |
| PLT-20261105081611759473 | suite_run | PLAT-006 | 200 | `incomplete_stream` | 120.94 |  |
| PLT-20261105082133727554 | suite_run | PLAT-001 | 200 | `ok` | 2.41 | ok |
| PLT-20261105082136252977 | suite_run | PLAT-001 | 200 | `ok` | 2.52 | ok |
| PLT-20261105082146127119 | suite_run | PLAT-002 | 200 | `ok` | 9.87 | 我无法完成这个任务。让我先说明原因。  ## FINAL_ANSWER: 无法执 |
| PLT-20261105082154173148 | suite_run | PLAT-002 | 200 | `classification_rejected` | 8.04 |  |
| PLT-20261105082334915859 | suite_run | PLAT-003 | 200 | `incomplete_stream` | 100.74 |  |
| PLT-20261105082516367267 | suite_run | PLAT-003 | 200 | `incomplete_stream` | 101.42 |  |
| PLT-20261105082527351417 | suite_run | PLAT-004 | 200 | `ok` | 10.96 | 抱歉，我查询北京天气时，wttr 天气源返回的结果匹配到了日本的 Naeshir |
| PLT-20261105082535998306 | suite_run | PLAT-004 | 200 | `ok` | 8.64 | 查询结果如下：  北京今天天气 — 查询未命中北京，wttr 源返回的是日本某地 |
| PLT-20261105082542155475 | suite_run | PLAT-005 | 200 | `ok` | 3.26 | 42 |
| PLT-20261105082548635116 | suite_run | PLAT-005 | 200 | `ok` | 3.73 | 42 |
| PLT-20261105082730769997 | suite_run | PLAT-006 | 200 | `incomplete_stream` | 102.13 |  |
| PLT-20261105082914274512 | suite_run | PLAT-006 | 200 | `incomplete_stream` | 103.5 |  |
| PLT-20261105083055439798 | suite_run | PLAT-007 | 200 | `incomplete_stream` | 101.16 |  |
| PLT-20261105083237873084 | suite_run | PLAT-007 | 200 | `incomplete_stream` | 102.43 |  |

## 5 说明

- 本报告由 `report_platform.py` 从原始 JSONL 与事件文件生成，数字未手工填写。
- `infrastructure_error` 不计入 Agent 行为失败率。
- 完整 SSE 事件见 `evidence/platform_events/`。
