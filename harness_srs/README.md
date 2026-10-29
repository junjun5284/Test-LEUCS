# LEUCS 测试系统（Harness）

面向 LEUCS 智能体平台的独立测试支撑项目：组织用例、驱动运行、采集证据、判定结果、沉淀问题。

- 不修改被测系统源码
- 证据以 `run_id` 串联：用例 → 运行 → 事件 → 判定 → 问题
- 覆盖两层被测对象：模型层（AgentLoop + Provider）与平台层（网站 API + SSE）

## 目录

```text
harness_srs/
  01_SRS_LEUCS_Testing_Agent_Harness.md   SRS v4.0（含平台层接口需求）
  02_current_issue_list_and_prompt_methods.md  问题列表 v4.0（ISSUE-001~020）
  03_合并版问题列表与SRS修订建议.md        早期合并稿（历史参考）
  04_harness_implementation_design_note.md 实现设计笔记
  minimal_harness.py   最小可运行 Harness（mock，无需凭据）
  real_harness.py      模型层真实适配（AgentLoop + 真实 Provider）
  platform_harness.py  平台层适配（health/list/conversation/events/feed/run/suite/decision）
  reclassify_platform.py  从不可变证据离线重算失败分层
  report_platform.py   从证据离线生成 Markdown 报告
  tests/test_harness_logic.py  Harness 自身逻辑自测（离线，13 项）
  cases/               模型层示例用例
  cases_real/          模型层真实用例
  platform_cases/      平台层用例（PLAT-001~003）
  evidence/            运行证据（JSONL / JSON / SSE 事件 / Markdown 报告）
```

## 快速开始（离线，无需凭据）

```powershell
python harness_srs\minimal_harness.py harness_srs\cases\sample_publish.json
```

输出：`harness_srs/evidence/runs.jsonl` 与 `summary.json`。

## 模型层（可选，需要模型凭据）

环境变量：`STUDENT_AGENT_API_KEY`、`LEUCS_BASE_URL`、`LEUCS_MODEL`

```powershell
python harness_srs\real_harness.py harness_srs\cases_real\sample_publish_real.json
```

## 平台层（可选，需要平台会话令牌）

环境变量：`LEUCS_PLATFORM_BASE`、`LEUCS_PLATFORM_TOKEN`

```powershell
python harness_srs\platform_harness.py health
python harness_srs\platform_harness.py run --text "请只回复两个字：ok"
python harness_srs\platform_harness.py suite --cases harness_srs\platform_cases --run-timeout 150
```

审批决策：遇到 `decision` 事件时，默认 `--decision none`（只记录为 `awaiting_approval`）；
`--decision deny` 会自动调用 `POST /api/leucs/decision` 拒绝，`--decision approve` 则批准（仅在明确需要时使用）。

平台运行证据写入 `evidence/platform_runs.jsonl`，完整 SSE 事件写入 `evidence/platform_events/`。

## Harness 自测（离线，无凭据）

```powershell
python -m unittest discover -s harness_srs/tests -p "test_*.py" -v
python harness_srs\report_platform.py
```

自测覆盖：oracle 判定（文本/工具/工具禁止/错误分层）、套件聚合、用例加载、失败分层重算。
报告写入 `evidence/platform_report.md`。

## 判定与失败分层

- `ok`：正常完成
- `awaiting_approval`：工具审批挂起，SSE 未给最终答案
- `classification_rejected`：分类契约被拒
- `incomplete_stream` / `timeout`：流中断或超时
- `infrastructure_error`：上游 5xx、连接失败等，不计入 Agent 行为失败率
- `agent_failure`：平台正常返回但行为失败

## 安全

- 凭据只从环境变量读取，不写入代码、日志或证据
- 提交目录不含任何令牌；如曾泄露，请在服务端轮换
- 平台地址与测试账号信息按课程要求脱敏使用

## 当前状态（2026-10）

- 平台层套件：9 次运行，成功 3 次；失败分布见 `evidence/platform_suite_summary_v2.json`
- 已记录问题 20 条，详见 `02_current_issue_list_and_prompt_methods.md`
