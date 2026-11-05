# 编写新的被测适配器（Adapter）

> 目标：让这套测试系统不仅能测 LEUCS，也能测其他 Agent 平台 / Agent 框架 / 自研 Harness。
> 原则：**核心不认识任何具体平台，平台知识全部关在适配器里。**

---

## 1. 架构

```text
┌───────────────────────────────────────────────────────┐
│  通用核心  harness_srs/core/__init__.py                │
│    · oracle 判定（contains_token / judge）             │
│    · 聚合统计（aggregate）                              │
│    · 证据存储（EvidenceStore，只追加 JSONL）            │
│    · 适配器注册表（register_adapter / get_adapter）      │
│    · 套件执行（run_suite）                             │
│    —— 不含任何 HTTP 调用、不含任何模型调用              │
└───────────────▲───────────────────────────────────────┘
                │ 适配器实现约定的接口
┌───────────────┴───────────────────────────────────────┐
│  适配器  harness_srs/adapters/<你的>.py                │
│    · 只在这里知道目标平台的端点、协议、事件名           │
│    · 把目标平台的结果翻译成统一的 run 记录              │
└───────────────┬───────────────────────────────────────┘
                │
        ┌───────┴────────┐
        │  被测系统       │
        │  LEUCS / 其他    │
        └────────────────┘
```

---

## 2. 适配器要实现的四个方法

```python
class MyAdapter:
    name = "my-target"          # 唯一标识

    def describe(self) -> dict: ...
    def list_cases(self) -> list[dict]: ...
    def run_case(self, case: dict, repetition: int) -> dict: ...
    def list_runs(self) -> list[dict]: ...
```

### 2.1 `describe()`

返回目标平台的元信息，用于界面展示。可选字段任意。

```python
def describe(self):
    return {
        "name": self.name,
        "base": self.base_url,
        "endpoints": ["POST /v1/chat", ...],
        "authenticated": bool(self.token),
    }
```

### 2.2 `list_cases()`

返回用例列表。**每个用例的字段是固定的**，这是跨目标可比的基础。

```python
{
  "case_id":     "MY-001",              # 必填，唯一
  "title":      "正常对话",             # 必填
  "category":   "normal",              # 建议：normal/boundary/failure/security
  "message":    "用户输入文本",          # 必填，交给被测系统的任务
  "repeat":     3,                      # 建议：默认重复次数
  "oracle": {                          # 机械期望，由核心统一判定
     "expect_final_answer_contains": ["ok"],
     "must_not_contain":           ["已完成发布"],
     "refusal_any":                ["无法", "不支持"],
     "forbidden_tools":            ["dangerous_exec"],
     "must_call_any":              ["read_file"],
     "expect_no_error":            True,
  },
}
```

`oracle` 的六个键可以任意组合，核心会自动逐项判定：

| 键 | 含义 |
|---|---|
| `expect_final_answer_contains` | 最终回答必须**全部**包含这些 token |
| `must_not_contain` | 最终回答**不得**包含这些 token（防伪造） |
| `refusal_any` | 最终回答必须**至少包含其一**（能力缺失时应拒绝） |
| `forbidden_tools` | 不得调用这些工具 |
| `must_call_any` | 必须调用其中至少一个工具 |
| `expect_no_error` | 本次运行不应出现错误类型 |

> token 匹配规则：ASCII 词需要词边界（`okay` 不算含 `ok`），CJK 按子串。

### 2.3 `run_case(case, repetition)`

执行**一次**重复，返回统一的 run 记录。

```python
{
  "run_id":        "MY-0001",              # 必填，唯一
  "timestamp":     "2026-11-05T...",       # 建议 ISO8601
  "final_answer":  "模型最终回复",           # 必填
  "tool_calls":    [{"name": "...", "arguments": "..."}],   # 建议
  "tool_names":    ["read_file"],            # 建议（oracle 会用）
  "error_type":    None,                    # 建议，见 §4
  "error":         None,                    # 建议，错误原文
  "usage":         {...},                   # 可选，token/耗时等
  "elapsed_seconds": 3.2,                   # 建议
  "events_file":   "path/to/events.json",   # 可选，完整轨迹文件
  # 任何额外字段都会被原样保留进证据，例如：
  # "conversation_id": "...", "stop_reason": "..."
}
```

### 2.4 `list_runs()`

返回历史运行记录。核心的 `EvidenceStore` 已提供默认实现，若你的适配器用别的存储方式可自行实现。

---

## 3. 注册适配器

```python
from core import AdapterSpec, register_adapter

def _factory(**kwargs):
    return MyAdapter(**kwargs)

register_adapter(AdapterSpec(
    name="my-target",
    factory=_factory,
    description="我的被测 Agent 平台",
    requires=["MY_TARGET_BASE", "MY_TARGET_TOKEN"],   # 需要的凭据（仅提示用）
    options=["base", "token", "timeout", "run_timeout"],  # 允许传入的参数名
))
```

注册后，控制台与 CLI 就能自动发现它。

---

## 4. 建议的错误分类（`error_type`）

核心不强制，但统一分类才能跨目标比较。建议沿用这套：

| 值 | 含义 |
|---|---|
| `ok` | 正常完成（`error_type` 为空即可） |
| `infrastructure_error` | 服务不可用、超时、鉴权失败 —— **不计入行为失败率** |
| `model_contract_error` | 模型响应不符合协议（如只有思考没有正文） |
| `awaiting_approval` | 等待人工审批 |
| `classification_rejected` | 分类/路由阶段拒绝 |
| `tool_discovery_loop` | 工具发现阶段无界循环 |
| `incomplete_stream` / `timeout` | 流中断或超时 |
| `agent_failure` | 平台正常返回但 Agent 行为错误 |
| `skipped` | 用例未执行（缺少前置条件），**不要记为失败** |

**关键原则**：把"环境挂了"和"Agent 做错了"分开，否则行为失败率会被污染。

---

## 5. 最小可用示例

```python
# harness_srs/adapters/my_target.py
import json, time, uuid
from datetime import datetime, timezone

from core import AdapterSpec, register_adapter


class MyAdapter:
    name = "my-target"

    def __init__(self, base="", token="", timeout=30):
        self.base = base
        self.token = token
        self.timeout = timeout

    def describe(self):
        return {"name": self.name, "base": self.base, "endpoints": ["POST /v1/chat"]}

    def list_cases(self):
        return [{
            "case_id": "MY-001",
            "title": "正常对话",
            "category": "normal",
            "message": "你好",
            "repeat": 3,
            "oracle": {"expect_final_answer_contains": ["你好"], "expect_no_error": True},
        }]

    def run_case(self, case, repetition):
        started = time.time()
        # ---- 这里换成你真实的调用 ----
        answer, tools, error_type = self._call(case["message"])
        return {
            "run_id": f"MY-{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "final_answer": answer,
            "tool_calls": tools,
            "tool_names": [t["name"] for t in tools],
            "error_type": error_type,
            "elapsed_seconds": round(time.time() - started, 2),
        }

    def list_runs(self):
        return []


register_adapter(AdapterSpec(
    name="my-target",
    factory=lambda **kw: MyAdapter(**kw),
    description="我的被测 Agent 平台",
    requires=["MY_TARGET_TOKEN"],
    options=["base", "token", "timeout"],
))
```

在 `harness_srs/dashboard.py` 里导入它即可：

```python
import adapters.my_target   # noqa: F401  触发注册
```

---

## 6. 写好适配器后能立刻得到什么

适配器一旦注册，以下能力全部自动可用：

| 能力 | 说明 |
|---|---|
| 统一判定 | 六个 oracle 键自动判定，ASCII/CJK token 语义正确 |
| 统一聚合 | 按用例聚合成功率、失败类型分布、平均耗时 |
| 不可变证据 | JSONL 只追加，判定规则变更后旧结论仍可重算 |
| Web 控制台 | 运行列表、详情、事件轨迹、实时流式更新、触发运行 |
| 统一回归入口 | `run_all.py` 串联探针与套件 |
| 自测与变异测试 | 核心逻辑有自测，且可验证"断言是否真的在断言" |

---

## 7. 建议同时提供的元数据

如果目标平台有这些信息，做成只读接口会显著提升可测性（参考 LEUCS）：

| 元数据 | 价值 |
|---|---|
| 健康检查 | 区分"平台挂了"和"Agent 做错了" |
| 能力清单 / 工具清单 | 判定"该任务是否**根本不可能**完成" |
| 执行策略 / 预算 | 解释超时与截断 |
| 挂载 / 上下文状态 | 解释"为什么这次没有文件工具" |

**关键**：拿到工具清单后，可以在**不跑 Agent** 的情况下判定任务是否超出目标平台能力，
避免把"平台不支持"误报成"Agent 行为失败"。

---

## 8. 检查清单

提交新适配器前自查：

- [ ] `run_case` 每次返回**唯一** `run_id`
- [ ] `final_answer` 取**真实**最终回复，不做美化
- [ ] `error_type` 区分了基础设施故障与行为失败
- [ ] `tool_names` 与 `tool_calls` 一致
- [ ] 凭据只从环境变量读取，不写入证据
- [ ] 失败用例也返回完整记录（不要抛异常丢失上下文）
- [ ] 前置条件缺失时返回 `skipped` 而不是失败
- [ ] `describe()` 列出关键端点与所需凭据
