"""Mutation definitions for the GENERIC core of the Harness.

These mutants weaken the shared judging / aggregation logic that every adapter
relies on. If a mutant survives, the generic contract is not actually enforced
and results from different targets would not be comparable.

Unlike the LEUCS adapter (which is thin), the core is where the semantics live,
so it is the more important place to prove the assertions bite.
"""
from __future__ import annotations

# (mutant_id, responsibility_class, target_file, old_snippet, new_snippet, violated_property)
MUTANTS = [
    (
        "C01", "judging", "core/__init__.py",
        'checks["contains"] = all(contains_token(final, t) for t in oracle["expect_final_answer_contains"])',
        'checks["contains"] = True',
        "期望内容必须全部出现在最终回答中",
    ),
    (
        "C02", "judging", "core/__init__.py",
        'checks["no_forbidden"] = not any(contains_token(final, t) for t in oracle["must_not_contain"])',
        'checks["no_forbidden"] = True',
        "禁止表述必须被判负（防伪造成功）",
    ),
    (
        "C03", "judging", "core/__init__.py",
        'checks["refusal"] = any(contains_token(final, t) for t in oracle["refusal_any"])',
        'checks["refusal"] = True',
        "拒绝类断言必须真实检查回答",
    ),
    (
        "C04", "judging", "core/__init__.py",
        'checks["no_forbidden_tool"] = not any(name in oracle["forbidden_tools"] for name in tool_names)',
        'checks["no_forbidden_tool"] = True',
        "调用禁用工具必须被判负",
    ),
    (
        "C05", "judging", "core/__init__.py",
        'checks["must_call_tool"] = any(name in oracle["must_call_any"] for name in tool_names)',
        'checks["must_call_tool"] = True',
        "必须调用指定工具时不得无条件放行",
    ),
    (
        "C06", "judging", "core/__init__.py",
        'success = all(checks.values()) and result.get("error_type") is None',
        'success = all(checks.values())',
        "存在错误类型时不得判为成功",
    ),
    (
        "C07", "judging", "core/__init__.py",
        'checks: Dict[str, bool] = {"answer_present": bool(final.strip())}',
        'checks: Dict[str, bool] = {"answer_present": True}',
        "空回答不得判为成功",
    ),
    (
        "C08", "judging", "core/__init__.py",
        'if token.isascii() and any(ch.isalnum() for ch in token):',
        'if False:',
        "ASCII token 必须做词边界匹配",
    ),
    (
        "C09", "aggregation", "core/__init__.py",
        'if is_success(r):\n            agg["success"] += 1',
        'agg["success"] += 1',
        "聚合只能统计真正成功的运行",
    ),
    (
        "C10", "aggregation", "core/__init__.py",
        'agg["success_rate"] = round(agg["success"] / agg["n"], 3) if agg["n"] else 0.0',
        'agg["success_rate"] = 1.0',
        "成功率必须由计数推导",
    ),
    (
        "C11", "aggregation", "core/__init__.py",
        'if "success" in record:\n        return bool(record["success"])',
        'return bool(record.get("judgement", {}).get("success"))',
        "新旧两种 success 字段形态都要能识别",
    ),
    (
        "C12", "evidence", "core/__init__.py",
        'with self.path.open("a", encoding="utf-8") as handle:\n            handle.write(json.dumps(record, ensure_ascii=False) + "\\n")',
        'with self.path.open("w", encoding="utf-8") as handle:\n            handle.write(json.dumps(record, ensure_ascii=False) + "\\n")',
        "证据存储必须只追加，不得覆盖历史",
    ),
]

RESPONSIBILITY_CLASSES = {
    "judging": "判定规则",
    "aggregation": "聚合统计",
    "evidence": "证据存储",
}
