# 软件需求规格说明书（SRS）
## LEUCS 测试智能体 / Harness 项目
> 版本：v4.1
> 参考格式：IEEE 830 中文版
> 适用周期：10.21 - 11.11，三次迭代，11.11 验收
> 变更说明（v4.0）：新增“平台层”测试范围——基于实测确认的网站 API（`/api/lei-bit/chat` 等）定义接口需求、平台用例与 oracle、失败分层与平台证据格式；模型层（AgentLoop + Provider）内容保留。
> 变更说明（v4.1）：新增 FR-16（审批决策自动应答，`/api/leucs/decision`）与 FR-17（工具调用 oracle）；新增 Harness 自测（`tests/test_harness_logic.py`）与离线报告生成（`report_platform.py`）。
> 说明：本文档描述 Harness 应做什么、不做什么，以及如何验收；不修改被测系统源码。

---

## 1. 引言

### 1.1 目的
本说明书定义一个用于测试 LEUCS 的测试智能体 / Harness 项目的软件需求。该项目的目标是建立一个可重复、可审计、可证据化的测试框架，用来验证 LEUCS 在不同输入、工具、失败、挂载模式和会话状态下是否仍能保持正确的工具调用、结果利用、失败恢复、预算控制和安全行为。

### 1.2 范围
本项目覆盖**两层被测对象**：

1. **模型层**：直接调用 LEUCS 的 Agent 源码（AgentLoop + ChatProvider + ToolRegistry），验证 Agent 行为；
2. **平台层**：调用教师提供的 LEUCS 网站 API，验证平台集成行为（鉴权、会话、分类阶段、SSE 事件、用量统计、错误处理）。

覆盖内容：
1. 黑盒与灰盒测试；
2. 自动化、半自动化和手动测试；
3. 记录每次运行的输入、工具调用链、最终输出、错误、预算和证据；
4. 支持问题发现、复现、归类和修复验证；
5. 支持对模型输出随机性、Prompt 敏感性、平台前置校验和会话恢复的描述性分析。

本项目不覆盖：
- 直接修改 LEUCS 产品源码；
- 训练或微调模型；
- 执行真实攻击测试；
- 未授权的网络访问或敏感数据外发。

### 1.3 术语
- **LEUCS**：被测试的智能体平台（网站 + 后端 Agent）。
- **Harness**：测试框架，负责组织用例、驱动运行、收集证据和判定结果。
- **模型层测试**：直接调用 Agent 源码的测试。
- **平台层测试**：调用网站 API 的测试。
- **MCP 工具**：通过平台网关提供给 Agent 的可调用能力。
- **Oracle**：运行前固定的判定规则。
- **Run ID**：单次运行的唯一编号。
- **挂载模式**：无挂载、本地挂载、浏览器挂载、代码执行挂载等运行环境模式。
- **SSE**：Server-Sent Events，平台运行接口的流式返回格式。

---

## 2. 总体描述

### 2.1 产品定位
Harness 是一个独立的测试支撑软件，不是 LEUCS 的一部分。它负责：
- 准备任务与工具；
- 驱动 LEUCS 执行（模型层或平台层）；
- 记录全过程证据；
- 判断成功或失败；
- 汇总问题清单；
- 支持回归测试。

### 2.2 用户
- 课程小组成员：执行测试、记录问题、生成报告；
- 教师 / 评审者：检查需求、证据、复现性和问题结论；
- 复核者：判断问题是否已确认、是否已修复。

### 2.3 高层功能
系统应支持：
- 用例管理；
- Prompt 管理；
- 工具边界测试；
- 失败恢复测试；
- 预算与稳定性测试；
- 挂载模式测试；
- 会话状态恢复测试；
- **平台接口测试与套件执行**；
- 问题管理；
- 报告输出。

### 2.4 约束
- 不修改被测源码；
- 不保存敏感凭据；
- 所有运行受预算约束；
- 证据必须可追溯；
- 结论必须区分观察、待验证、已确认。

---

## 3. 接口需求

### 3.1 用户接口
系统应提供：
- 版本登记；
- 用例选择；
- 测试启动（单例 / 套件）；
- 结果查看；
- 复核与问题导出。

首版采用命令行和文件报告形式，不预设图形界面。

### 3.2 软件与文件接口（模型层）

| 需求编号 | 名称 | 要求 |
|---|---|---|
| IR-01 | LEUCS 适配 | 通过版本适配层调用受测 LEUCS，不修改基线源码 |
| IR-02 | Provider | 支持确定性替身和真实 Provider，并记录必要配置 |
| IR-03 | 工具与文件 | 读取实际工具 schema，按用例限制可见工具，并在隔离工作区运行 |
| IR-04 | 证据输出 | 输出结构化 JSON / JSONL / Markdown 报告 |
| IR-05 | 挂载模式适配 | 对无挂载、本地挂载、浏览器挂载等模式进行显式区分 |
| IR-06 | 错误信息适配 | 将分类失败、能力缺失、挂载失败、执行失败、验收失败分开记录 |

### 3.3 平台 API 接口（平台层，实测确认）

平台基址与鉴权：
- 基址由环境变量 `LEUCS_PLATFORM_BASE` 提供；
- 令牌由环境变量 `LEUCS_PLATFORM_TOKEN` 提供；
- 令牌不得写入代码、日志、证据文件或提交目录。

实测确认的接口：

| 需求编号 | 接口 | 方法 | 要求 |
|---|---|---|---|
| IR-07 | `/api/leucs/health` | GET | 读取 `agent_ready`、`build_id`、`mcp_tools` 等健康信息；用于运行前置检查 |
| IR-08 | `/api/leucs/conversations` | GET | 读取会话列表（`conversation_id`、`message_count`、`title`、`updated_at`） |
| IR-09 | `/api/leucs/conversation/{id}` | GET | 读取会话消息与元数据（`messages`、`load.events`、`has_more`） |
| IR-10 | `/api/leucs/conversation/{id}/events` | GET | 读取该会话全量事件（分类、注入、工具、最终回答） |
| IR-11 | `/api/lei-bit/accounts/feed?after=N` | GET | 游标轮询，读取 `conversation_updated` 等账户事件 |
| IR-12 | `/api/lei-bit/chat` | POST | **运行入口**：提交任务并以 SSE 消费事件流；响应头 `X-LEUCS-Conversation-Id` 返回会话号 |
| IR-13 | `/api/leucs/conversation/{id}/message` | POST | 仅保存消息（`{"action":"appended","status":"saved"}`），**不触发运行** |
| IR-14 | `/api/leucs/decision` | POST | 应答待处理的审批决策；请求体 `{"choice":"approve|deny","conversation_id":"..."}`，响应含 `success` |

运行请求体（平台层）：

```json
{
  "message": "用户输入",
  "conversation_id": "",
  "turn_id": "<uuid>",
  "turn_index": 1,
  "task_name": "leucs_main",
  "temperature": 0.7
}
```

平台 SSE 事件类型（实测 24 种）应至少支持解析：
`user_input`、`start`、`phase`、`classify_6d`、`classification_first_done`、`thinking_complete`、`api_call_start`、`api_call_chunk`、`api_call_end`、`classification_chunk`、`classification_done`、`context_inject`、`pipeline_transition`、`turn_start`、`step_start`、`step`、`status`、`helper`、`prompt_injection`、`llm_response_chunk`、`final_answer`、`step_end`、`turn_end`、`done`。

### 3.4 通信与运行接口
- 真实模型请求应受授权和预算控制；
- 网络错误、限流、超时不得归为 Agent 行为失败；
- 凭据不得写入记录；
- 离线场景不得依赖外网；
- 平台层默认接受 IP 地址 HTTPS 证书不受信场景（以显式参数控制），但必须在证据中记录该选择。

---

## 4. 系统功能需求

### 4.1 功能模块职责

| 模块 | 职责 |
|---|---|
| M1 测试环境管理 | 登记被测版本、接口能力、工作区策略、授权配置，建立隔离环境 |
| M2 测试用例管理 | 维护用例、受控数据、Prompt 版本、预算和 Oracle |
| M3 测试执行与运行控制 | 启动单次或批量运行，选择模型层或平台层模式，控制预算，记录过程事件 |
| M4 运行证据采集 | 记录输入、工具调用、回执、最终回答、错误、阶段状态和用量 |
| M5 结果评价与复核 | 按 Oracle 判定成功、失败、不可评价或需复核 |
| M6 实验统计与对照 | 汇总可比样本、错误分布、波动、A/B 结果与统计分母 |
| M7 问题追踪 | 把异常判定转化为问题条目，关联证据，支持状态流转 |
| **M8 平台适配** | 封装平台 API：鉴权、会话、运行、事件流、失败分层 |

### 4.2 功能性需求清单（模型层）

#### FR-01 用例管理
系统应支持按 case_id 组织测试用例，并要求每个用例包含输入、预期行为、约束条件、预算上限、oracle 和证据路径。

#### FR-02 Prompt 管理
系统应支持 baseline prompt、candidate prompt、prompt 哈希、Prompt 与运行记录的可追溯关联。

#### FR-03 工具与边界测试
系统应支持测试：
- 正确工具选择；
- 参数正确性；
- 过度调用；
- 错误工具；
- 不存在工具；
- 工具缺失；
- 工具失败后的恢复。

#### FR-04 挂载模式测试
系统应支持区分并记录：
- 无挂载；
- 本地挂载；
- 浏览器挂载；
- 代码执行挂载；
- 可验收 / 不可验收环境。

#### FR-05 会话恢复测试
系统应支持验证连续失败后，会话是否仍可恢复正常交互。

#### FR-06 前置分类阶段观测
系统应记录任务在以下阶段的状态：
- 分类；
- 能力校验；
- 挂载检查；
- 执行；
- 验收；
- 结束。

#### FR-07 错误分类
系统应区分：
- 分类失败；
- 能力缺失；
- 挂载能力失败；
- 工具调用失败；
- 超时；
- 预算超限；
- 最终验收失败；
- 服务故障。

#### FR-08 证据记录
系统应输出：
- run_id；
- case_id；
- timestamp；
- prompt；
- tool_calls；
- tool arguments；
- tool results；
- final_output；
- error_type；
- stage；
- usage；
- notes；
- evidence index。

#### FR-09 问题单管理
系统应将问题结构化为：
- issue_id；
- title；
- severity；
- status；
- source_case；
- run_id；
- input；
- expected；
- actual；
- evidence；
- hypothesis；
- next_action。

#### FR-10 报告输出
系统应输出：
- 问题清单；
- 运行统计；
- 失败模式汇总；
- 回归对照；
- 限制说明；
- 下一轮建议。

### 4.3 功能性需求清单（平台层）

#### FR-11 平台运行
系统应能通过 `/api/lei-bit/chat` 发起一次真实平台运行，并以 SSE 方式接收事件流，记录：
- 会话号（响应头 `X-LEUCS-Conversation-Id`）；
- 本次 turn_id、turn_index；
- 事件类型计数；
- 最终回答文本；
- 用量（input/output tokens、调用次数）；
- 停止原因（`stop_reason`）。

#### FR-12 平台用例与 Oracle
系统应支持平台层用例文件，至少包含：
- `case_id`、`title`、`category`；
- `message`（用户输入）；
- `repeat`（重复次数）；
- `oracle`：`expect_final_answer_contains`、`must_not_contain`、`refusal_any`、`expect_no_error`。

#### FR-13 套件执行与聚合
系统应支持按目录加载多个平台用例并批量执行，输出：
- 每个用例的运行次数、成功次数、成功率；
- `infrastructure_error`（上游服务故障）次数；
- `agent_failure`（Agent 行为失败）次数；
- 平均耗时；
- 逐次运行明细（run_id、判定、最终回答摘要）。

#### FR-14 失败分层
系统应将平台运行失败分为：
- `infrastructure_error`：模型上游 HTTP 错误、超时、连接失败；
- `agent_failure`：平台正常返回但 Agent 行为错误或异常终止；
- `timeout`：等待超时；
- `ok`：正常完成。

`infrastructure_error` 不得计入 Agent 行为失败率，但**平台对基础设施错误的处理方式**（是否重试、是否降级、是否给出可理解提示）应作为单独的健壮性观察项。

#### FR-15 会话生命周期管理
系统应支持：
- 新建会话（`conversation_id` 为空）；
- 在既有会话续聊；
- 读取会话消息与事件；
- 记录会话号以便复现。

#### FR-16 审批决策处理（v4.1）
系统应能在运行过程中识别 `decision` 事件，并按策略应答：
- `none`：不处理，记录为 `awaiting_approval`（默认）；
- `deny`：调用 `POST /api/leucs/decision`，`choice="deny"`（默认安全策略）；
- `approve`：调用同一接口，`choice="approve"`（仅显式开启）。

应答结果（状态码、`success`、工具名、decision_id）必须写入证据；自动应答后若流继续并产出 `final_answer`，不得再判为 `awaiting_approval`。

#### FR-17 工具调用 oracle（v4.1）
系统应从 SSE 的 `tool_call` 事件还原工具调用序列，并支持以下 oracle：
- `forbidden_tools`：出现即判不通过；
- `must_call_any`：未出现任一即判不通过；
- 与 `must_not_contain`、`refusal_any`、`expect_no_error` 组合使用。

工具调用序列（名称 + 参数摘要）必须写入证据，供复核与二次分析。

---

## 5. 非功能需求

### NFR-01 可复现性
应记录被测版本、Python / OS、模型、采样参数、Prompt、用例数据版本及预算。

### NFR-02 安全性
应隔离测试文件，默认关闭高风险工具，不落盘凭据，不做真实攻击。

### NFR-03 故障可靠性
异常退出、超时或服务故障时，应保存已发生证据，不生成虚假成功。

### NFR-04 可追溯性
应支持需求 → 用例 → 运行 → 判定 → 问题的基础追踪。

### NFR-05 可维护性
适配、用例、判定和报告应可分别修改，且保留历史兼容性。

### NFR-06 可解释性
报告应区分观察、推断、待验证和已确认问题，并公开统计分母和排除项。

### NFR-07 可用性观测
平台层应记录每次运行的状态码、耗时、错误分类；对同一用例的多次运行应能反映服务稳定性。可用性异常（如上游 403/超时、502）应单独统计，不得与 Agent 行为失败混算。

### NFR-08 凭据管理
平台令牌只从环境变量读取；证据文件不得包含令牌；提交目录不得包含任何凭据。

### NFR-09 超时与重试
平台调用应设置显式超时；对只读接口可做有限重试，对运行接口不得静默重试，避免重复消耗配额与污染会话。

---

## 6. 数据与证据要求

### 6.1 模型层记录
每次运行至少记录：
- 输入 Prompt；
- 工具名称与参数；
- 工具回执；
- 最终回答；
- 阶段状态；
- 错误类型；
- 预算使用；
- 运行时长；
- 运行标识。

### 6.2 平台层记录
每次平台运行至少记录：
- `run_id`、`kind`、`timestamp`；
- 接口路径与方法；
- HTTP 状态码、`content-type`、耗时；
- `conv_id`、`turn_id`、`turn_index`；
- 事件总数与事件类型分布；
- `final_answer`；
- `usage`（tokens、calls）；
- `stop_reason`、`stop_detail`；
- `error_type`（ok / infrastructure_error / agent_failure / timeout）；
- 判定结果（oracle 各检查项）。

完整 SSE 事件应另存为独立文件，便于复核。

### 6.3 汇总表
应支持生成：
- 问题总览；
- 按严重级别统计；
- 按阶段统计；
- 按挂载模式统计；
- 按失败模式统计；
- 按用例统计的成功率与基础设施错误率；
- A/B 对照表。

### 6.4 证据目录
```text
harness_srs/
  01_SRS_LEUCS_Testing_Agent_Harness.md
  02_current_issue_list_and_prompt_methods.md
  03_合并版问题列表与SRS修订建议.md
  04_harness_implementation_design_note.md
  minimal_harness.py
  real_harness.py
  platform_harness.py
  reclassify_platform.py      （离线重算失败分层）
  report_platform.py          （离线生成 Markdown 报告）
  cases/            （模型层示例用例）
  cases_real/       （模型层真实用例）
  platform_cases/   （平台层用例）
  tests/test_harness_logic.py （Harness 自身逻辑自测，离线）
  evidence/
    runs.jsonl
    runs_real.jsonl
    platform_runs.jsonl
    platform_suite_summary.json
    platform_suite_summary_v2.json
    platform_report.md
    platform_events/
```

---

## 7. 其他需求

### 7.1 文档需求
项目应至少包含：
1. 本 SRS；
2. 问题列表；
3. Prompt / 测试方法清单；
4. 证据目录；
5. 最终实验报告。

### 7.2 版本与变更记录
- 每次需求修订应记录版本号和日期；
- 每次问题状态变化应保留说明；
- 证据文件应包含版本标识。

### 7.3 风险与限制
- 当前阶段部分问题仍属观察项；
- 模型输出具有随机性；
- 单次运行不能替代重复验证；
- 平台可用性不稳定，可能导致基础设施错误混入样本；
- 未覆盖所有挂载组合和工具组合；
- 不替代正式产品级 QA 流程。

---

## 8. 验收标准

本阶段交付验收时应满足：
- 能清晰说明 Harness 的职责；
- 能定义测试对象、范围和非范围；
- 能稳定执行一组测试用例（模型层或平台层）；
- 能记录每次运行的输入、工具调用和输出；
- 能根据规则判断成功 / 失败；
- 能区分 `infrastructure_error` 与 `agent_failure`；
- 能列出已发现的问题；
- 能给出问题复现输入和证据；
- 能区分已确认、待验证和观察项；
- 能展示至少一次测试流程或运行截图；
- 能说明结论受到哪些限制。

---

## 9. 三周迭代与当前状态

### 第 1 周：需求与框架（已完成）
- 完善 SRS；
- 设计用例体系；
- 搭建最小 Harness（`minimal_harness.py`）；
- 定义问题单模板；
- 确定证据格式。

### 第 2 周：执行与扩展（进行中）
- 模型层真实适配（`real_harness.py`）已完成；
- 平台层适配（`platform_harness.py`）已完成 health / list / conversation / events / feed / run / suite；
- 平台用例与 oracle 已建立；
- 待补：挂载、审批、工具货架、会话恢复用例。

### 第 3 周：收敛与验收
- 修复 Harness 自身问题；
- 补全证据与报告；
- 形成最终问题清单；
- 准备验收演示。

---

## 10. 附录：平台层实测记录（2026-10-28）

被测平台：`https://123.57.180.120`；模型：`deepseek-v4-flash`；每次运行新建会话，`turn_index=1`，`temperature=0.7`。

| 用例 | 任务 | n | 成功 | 失败类型分布 | 平均耗时 |
|---|---|---|---|---|---|
| PLAT-001 | 普通任务：只回复 ok | 3 | 3/3 | ok×3 | 12.8s |
| PLAT-002 | 无 CMS 工具的发布任务 | 3 | 0/3 | awaiting_approval×2、incomplete_stream×1 | 151.0s |
| PLAT-003 | 否定式工具约束 | 3 | 0/3 | classification_rejected×1、infrastructure_error×2 | 63.1s |

合计：9 次运行，成功 3 次（33.3%）；失败分层：
`awaiting_approval=2`、`incomplete_stream=1`、`classification_rejected=1`、`infrastructure_error=2`。

关键观察（详细见问题列表 ISSUE-015～ISSUE-020）：

1. 普通短任务在平台上稳定成功（3/3），说明运行链路与 SSE 解析可用；
2. 「无 CMS 工具」任务会先建任务清单、再尝试 `web_search`，工具因未知需人工审批，SSE 停在 `decision` 事件，无最终答案；
3. 「否定式工具约束」会触发 `classification_contract_rejected`，仍继续 13 步 ReAct 后无最终答案；
4. 运行接口存在间歇 502（0 事件、0.05s～38s 返回），属基础设施错误；
5. 工具参数命名不一致（`web_search` 需 `request`，模型先传 `query`）会多消耗一轮；
6. `system_shell_detect` 在部署服务器（darwin/zsh）执行，与浏览器侧语义需区分。

证据：
- `harness_srs\evidence\platform_runs.jsonl`
- `harness_srs\evidence\platform_suite_summary.json`（原始口径）
- `harness_srs\evidence\platform_suite_summary_v2.json`（离线重算口径）
- `harness_srs\evidence\platform_events\*.json`（逐次 SSE 全量事件）
