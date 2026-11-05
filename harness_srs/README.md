# LEUCS 测试系统（Harness）

面向 Agent 平台的独立测试支撑项目：组织用例、驱动运行、采集证据、判定结果、沉淀问题。

- 不修改被测系统源码
- 证据以 `run_id` 串联：用例 → 运行 → 事件 → 判定 → 问题
- **目标无关**：核心层不含任何平台知识，平台差异收敛在适配器
- **可观察**：内置 Web 控制台，可看总览、运行详情、事件轨迹，并实时推送结果

## 快速开始

```powershell
# 1) 离线最小演示（无需任何凭据）
python harness_srs\minimal_harness.py harness_srs\cases\sample_publish.json

# 2) Web 控制台（推荐的可视化入口）
python harness_srs\dashboard.py --port 8801
#    浏览器打开 http://127.0.0.1:8801

# 3) 统一 CLI
python harness_srs\harness_cli.py adapters      # 列出可用适配器
python harness_srs\harness_cli.py cases         # 列出用例
python harness_srs\harness_cli.py run           # 运行套件
python harness_srs\harness_cli.py summary       # 汇总历史证据
```

## 目录

```text
harness_srs/
  core/__init__.py          通用核心：oracle 判定 / 聚合 / 证据存储 / 适配器注册
  adapters/__init__.py      LEUCS 适配器（平台知识全部在这里）
  dashboard.py              Web 控制台（总览 / 运行列表 / 详情 / 事件轨迹 / 实时流）
  harness_cli.py            统一命令行入口
  docs/ADAPTER_GUIDE.md     如何为别的平台写适配器
  01_SRS_LEUCS_Testing_Agent_Harness.md   SRS v6.0
  02_current_issue_list_and_prompt_methods.md  问题列表 v5.2（ISSUE-001~030）
  minimal_harness.py   最小可运行 Harness（mock，无需凭据）
  real_harness.py      模型层真实适配（AgentLoop + 真实 Provider）
  platform_harness.py  平台层适配（health/list/conversation/events/feed/run/suite/decision/mount）
  platform_probe.py    平台健康探针（9 个只读端点 + 基线比对）
  run_all.py           统一回归入口（探针 → 平台层 → 模型层）
  diagnose_think_empty.py  跨边界缺陷定位（直连模型服务做参数扫描对照）
  reclassify_platform.py  从不可变证据离线重算失败分层
  report_platform.py   从证据离线生成 Markdown 报告
  mutants/             对通用核心与平台层判定的变异测试
  tests/               自测（离线，52 项）
  cases/               模型层示例用例
  cases_real/          模型层真实用例
  platform_cases/      平台层用例（PLAT-001~007：正常/工具边界/否定式约束/审批挂起/会话续聊/挂载读写/挂载执行拒绝）
  evidence/            运行证据（JSONL / JSON / SSE 事件 / Markdown 报告 / 变异结果 / 根因量化）
```

## Web 控制台

```powershell
python harness_srs\dashboard.py --port 8801
```

打开 http://127.0.0.1:8801 可以看到：

| 区域 | 内容 |
|---|---|
| 总览 | 运行总数、成功率、基础设施错误数、超时数、证据文件数 |
| 运行记录 | 可按用例 / 类型 / 判定筛选，点击查看详情 |
| 用例统计 | 每个用例的 n、成功数、成功率条、平均耗时 |
| 运行详情 | 每个断言的通过情况、最终回答、错误信息、用量、工具发现分析、**完整事件轨迹** |

运行套件时，新结果通过 SSE **实时推送**，无需刷新页面。

## 接入其他被测系统

Harness 的核心不认识 LEUCS，只认识"用例 → 运行 → 判定 → 证据"。
新增目标只需写一个适配器（四个方法），即可自动获得判定、聚合、
不可变证据、Web 控制台、回归入口、自测与变异测试。

详见 `docs/ADAPTER_GUIDE.md`。

```python
class MyAdapter:
    name = "my-target"
    def describe(self): ...
    def list_cases(self): ...
    def run_case(self, case, repetition): ...
    def list_runs(self): ...
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
python harness_srs\platform_harness.py suite --cases harness_srs\platform_cases --use-mount
```

审批决策：遇到 `decision` 事件时，默认 `--decision none`（只记录为 `awaiting_approval`）；
`--decision deny` 会自动调用 `POST /api/leucs/decision` 拒绝，`--decision approve` 则批准（仅在明确需要时使用）。

**挂载感知**：浏览器挂载与**单个会话**强绑定，因此挂载类用例必须声明
`requires_mount: true`，并用 `--use-mount` 让 Harness 自动在挂载所在会话中执行；
无挂载时这类用例会被**跳过**而非误判为失败。

平台运行证据写入 `evidence/platform_runs.jsonl`，完整 SSE 事件写入 `evidence/platform_events/`。

## 挂载能力契约（需要平台令牌）

```powershell
python harness_srs\platform_harness.py mount
```

读取浏览器挂载端的**能力清单**与服务端预算策略，并自动判定关键能力边界
（例如：工具清单是否含代码执行工具）。该判定不依赖 Agent 运行，
因此不会被上游故障掩盖。已用于确认 ISSUE-026：浏览器挂载的 14 个工具
全部是文件与 Git 操作，**不含任何代码执行能力**。

## 平台健康探针（需要平台令牌）

```powershell
python harness_srs\platform_probe.py                      # 9 个只读端点
python harness_srs\platform_probe.py --save-baseline      # 保存基线
python harness_srs\platform_probe.py --compare-baseline   # 与基线比对，输出漂移项
```

只读、不触发 Agent 运行、不产生会话副作用。**注意**：健康端点在令牌过期时仍返回 200，
所以探针覆盖了 8 个业务端点而不是只看 health。

## 跨边界缺陷定位（需要模型凭据）

```powershell
$env:STUDENT_AGENT_API_KEY = "..."
$env:LEUCS_BASE_URL = "https://maas.bit.edu.cn/v1"
$env:LEUCS_MODEL = "deepseek-v4-flash"
python harness_srs\diagnose_think_empty.py --tokens 412,512,1024,2048 --trials 8
```

用**同一提示词**直连模型服务，扫描 `max_tokens`，区分"模型故障 / 提示词错误 / 平台解析错误 /
平台预算缺陷"。已用于定位 ISSUE-025（平台分类阶段输出预算固定 412 tokens，
导致约 50%–75% 的请求把预算耗尽在 reasoning 上，`content` 为空 → `THINK_EMPTY`）。
证据：`evidence/think_empty_diagnosis.json`。

## 统一回归入口

```powershell
python harness_srs\run_all.py --platform-only --reps 3 --probe
python harness_srs\run_all.py --model-only
```

串联健康探针 → 平台层套件 → 模型层，产出 `evidence/regression_report.md` 与
`evidence/regression_report.json`。
## 自测与变异测试（离线，无凭据）

```powershell
python -m unittest discover -s harness_srs/tests -p "test_*.py" -v
python harness_srs\mutants\run_core_mutants.py       # 通用核心 12 个变异体
python harness_srs\mutants\run_harness_mutants.py   # 平台层判定 14 个变异体
```

变异测试对**判定逻辑**施加单一逻辑变异，检验"断言是否真的在断言"；
存活变异体即自测缺口。结果写入 `evidence/core_mutants.json` 与
`evidence/harness_mutants.json`。

## 判定与失败分层

- `ok`：正常完成
- `awaiting_approval`：工具审批挂起，SSE 未给最终答案（`--decision` 可自动应答）
- `classification_rejected`：分类契约被拒
- `model_contract_error`：模型响应契约异常（如 `THINK_EMPTY`）
- `tool_discovery_loop`：工具发现阶段无界循环（同一工具反复调用且无实质动作）
- `incomplete_stream` / `timeout`：流中断或超时
- `infrastructure_error`：上游 5xx、连接失败、401 等，不计入 Agent 行为失败率
- `agent_failure`：平台正常返回但行为失败

## 安全

- 凭据只从环境变量读取，不写入代码、日志或证据
- 提交目录不含任何令牌；如曾泄露，请在服务端轮换
- 平台地址与测试账号信息按课程要求脱敏使用

## 当前状态（2026-11-05）

- 自测 52 项全部通过；变异测试：通用核心 12/12、平台层判定 14/14 全部被识别
- 平台层用例 7 个（PLAT-001~007），覆盖正常任务、工具边界、否定式约束、审批挂起、会话续聊、挂载读写、挂载执行拒绝
- 平台健康探针 9/9 通过，已保存基线
- Web 控制台可用：总览 / 运行列表 / 详情 / 事件轨迹 / SSE 实时流 / 界面触发运行
- 核心层与平台层已分离，适配器契约见 `docs/ADAPTER_GUIDE.md`
- **ISSUE-025 已闭环**：平台把分类阶段输出预算从 412 提到 1024 后症状消失
- 已确认 ISSUE-026（挂载无执行能力）、ISSUE-029（挂载与会话强绑定）
- 已定位 ISSUE-028（工具发现无界循环）、ISSUE-030（因果修复门禁自指死锁）
- 已记录问题 30 条，详见 `02_current_issue_list_and_prompt_methods.md`
- 当前主要阻断：ISSUE-030 使挂载类用例在**挂载会话内**仍无法完成首次写入
