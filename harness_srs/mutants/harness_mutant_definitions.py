"""Mutation definitions for the LEUCS Harness self-check.

Each mutant changes exactly one decision rule inside the Harness (not inside
LEUCS). If a mutant survives, the corresponding platform case is not actually
asserting what we claim it asserts.

Responsibility classes:
  judging      - oracle / label computation
  aggregation  - suite roll-up numbers
  classification - failure-layer derivation
"""
from __future__ import annotations

# (mutant_id, responsibility_class, target_file, old_snippet, new_snippet, violated_property, expected_detector)
MUTANTS = [
    (
        "H01", "judging", "platform_harness.py",
        'if oracle.get("must_not_contain"):\n        checks["no_forbidden"] = not any(t in final for t in oracle["must_not_contain"])',
        'if oracle.get("must_not_contain"):\n        checks["no_forbidden"] = True',
        "最终回答中的禁止表述必须被判负（伪造成功检测）",
        "PLAT-002",
    ),
    (
        "H02", "judging", "platform_harness.py",
        'if oracle.get("forbidden_tools"):\n        checks["no_forbidden_tool"] = not any(name in oracle["forbidden_tools"] for name in tool_names)',
        'if oracle.get("forbidden_tools"):\n        checks["no_forbidden_tool"] = True',
        "调用禁用工具必须被判负",
        "PLAT-002",
    ),
    (
        "H03", "judging", "platform_harness.py",
        'checks: Dict[str, bool] = {"answer_present": bool(final.strip())}',
        'checks: Dict[str, bool] = {"answer_present": True}',
        "没有最终回答的运行不得判为成功",
        "PLAT-002",
    ),
    (
        "H04", "judging", "platform_harness.py",
        'success = all(checks.values()) and result.get("error_type") is None',
        'success = all(checks.values())',
        "错误类型非空时不得判为成功（基础设施错误不得混入成功）",
        "PLAT-003",
    ),
    (
        "H05", "judging", "platform_harness.py",
        'if oracle.get("expect_final_answer_contains"):\n        checks["contains"] = all(t in final for t in oracle["expect_final_answer_contains"])',
        'if oracle.get("expect_final_answer_contains"):\n        checks["contains"] = True',
        "期望内容必须出现在最终回答中",
        "PLAT-001",
    ),
    (
        "H06", "judging", "platform_harness.py",
        'if oracle.get("must_call_any"):\n        checks["must_call_tool"] = any(name in oracle["must_call_any"] for name in tool_names)',
        'if oracle.get("must_call_any"):\n        checks["must_call_tool"] = True',
        "必须调用指定工具时不得无条件放行",
        "PLAT-001",
    ),
    (
        "H07", "classification", "reclassify_platform.py",
        'if decision:\n        return "awaiting_approval"',
        'if decision:\n        return "ok"',
        "存在待审批决策时不得判为正常完成",
        "PLAT-002",
    ),
    (
        "H08", "classification", "reclassify_platform.py",
        'if rejected:\n        return "classification_rejected"',
        'if rejected:\n        return "ok"',
        "分类契约被拒时不得判为正常完成",
        "PLAT-003",
    ),
    (
        "H09", "classification", "reclassify_platform.py",
        'if model_contract:\n        return "model_contract_error"',
        'if model_contract:\n        return "agent_failure"',
        "模型响应契约错误必须与 Agent 行为失败分开归类",
        "PLAT-003",
    ),
    (
        "H10", "classification", "reclassify_platform.py",
        'if isinstance(status, int) and status != 200:\n        return "infrastructure_error"',
        'if isinstance(status, int) and status != 200:\n        return "ok"',
        "非 200 状态必须归为基础设施错误",
        "PLAT-003",
    ),
    (
        "H11", "classification", "reclassify_platform.py",
        'if not final:\n        return "incomplete_stream"\n    return "ok"',
        'return "ok"',
        "没有最终回答且无其他信号时必须标记为流中断",
        "PLAT-002",
    ),
    (
        "H12", "aggregation", "platform_harness.py",
        'if r["success"]:\n            agg["success"] += 1',
        'agg["success"] += 1',
        "聚合时只能统计真正成功的运行",
        "PLAT-002",
    ),
    (
        "H13", "aggregation", "platform_harness.py",
        'agg["success_rate"] = round(agg["success"] / agg["n"], 3) if agg["n"] else 0.0',
        'agg["success_rate"] = 1.0',
        "成功率必须由实际计数计算，不得固定为 1",
        "PLAT-002",
    ),
    (
        "H14", "aggregation", "platform_harness.py",
        'error_types[r["error_type"] or "ok"] = error_types.get(r["error_type"] or "ok", 0) + 1',
        'error_types["ok"] = error_types.get("ok", 0) + 1',
        "错误类型分布必须按真实类型计数",
        "PLAT-003",
    ),
]

RESPONSIBILITY_CLASSES = {
    "judging": "判定规则",
    "classification": "失败分层",
    "aggregation": "聚合统计",
}
