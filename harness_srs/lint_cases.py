#!/usr/bin/env python
"""Lint case definitions before they are spent on real platform calls.

A malformed case silently wastes budget and pollutes evidence: a missing
`case_id` makes runs unattributable, an empty oracle makes every run "pass",
a `must_contain` token that can never appear produces a guaranteed false fail.

This linter checks the *shape and the semantics* of the oracle, offline.

Usage:
    python harness_srs/lint_cases.py
    python harness_srs/lint_cases.py --cases harness_srs/platform_cases
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent

VALID_ORACLE_KEYS = {
    "expect_final_answer_contains",
    "must_not_contain",
    "refusal_any",
    "forbidden_tools",
    "must_call_any",
    "expect_no_error",
}
TOKEN_RE = re.compile(r"^[\w一-鿿 \u3000-\u303f\.\-_/\\\\:@#]+$", re.UNICODE)


def lint_case(case: Dict[str, Any], known_tools: List[str]) -> List[Tuple[str, str]]:
    """Return a list of (severity, message) for one case."""
    issues: List[Tuple[str, str]] = []
    cid = case.get("case_id")

    if not cid or not isinstance(cid, str):
        issues.append(("error", "case_id 缺失或不是字符串"))
    else:
        if not re.match(r"^[A-Za-z0-9_\-]+$", cid):
            issues.append(("warn", f"case_id {cid!r} 含非常规字符，可能影响排序与文件名"))
    if not case.get("title"):
        issues.append(("warn", f"{cid}: 缺少 title"))
    if not case.get("category"):
        issues.append(("info", f"{cid}: 缺少 category，统计时会归入未分类"))
    if not case.get("message"):
        issues.append(("error", f"{cid}: 缺少 message（没有输入就没有可测对象）"))

    repeat = case.get("repeat", 3)
    if not isinstance(repeat, int) or repeat < 1:
        issues.append(("error", f"{cid}: repeat 必须是不小于 1 的整数"))
    elif repeat == 1:
        issues.append(("warn", f"{cid}: repeat=1 无法区分稳定失败与随机波动"))

    oracle = case.get("oracle")
    if not isinstance(oracle, dict) or not oracle:
        issues.append(("error", f"{cid}: oracle 缺失或为空（任何运行都会被判为通过）"))
        return issues

    unknown = set(oracle) - VALID_ORACLE_KEYS
    for key in sorted(unknown):
        issues.append(("warn", f"{cid}: 未知 oracle 键 {key!r}（会被忽略）"))

    for key in ("expect_final_answer_contains", "must_not_contain", "refusal_any"):
        value = oracle.get(key)
        if value is None:
            continue
        if not isinstance(value, list) or not value:
            issues.append(("error", f"{cid}: {key} 必须是非空列表"))
            continue
        for token in value:
            if not isinstance(token, str) or not token.strip():
                issues.append(("error", f"{cid}: {key} 含空或非字符串 token"))
            elif not TOKEN_RE.match(token):
                issues.append(("warn", f"{cid}: {key} 的 token {token!r} 含非常规字符"))

    if oracle.get("expect_final_answer_contains") and oracle.get("must_not_contain"):
        expected = set(oracle["expect_final_answer_contains"])
        forbidden = set(oracle["must_not_contain"])
        overlap = expected & forbidden
        if overlap:
            issues.append(("error", f"{cid}: 期望包含与禁止包含存在交集 {sorted(overlap)}，该用例永远无法通过"))

    if oracle.get("refusal_any") and oracle.get("must_not_contain"):
        overlap = set(oracle["refusal_any"]) & set(oracle["must_not_contain"])
        if overlap:
            issues.append(("error", f"{cid}: refusal_any 与 must_not_contain 存在交集 {sorted(overlap)}"))

    for key in ("forbidden_tools", "must_call_any"):
        value = oracle.get(key)
        if value is None:
            continue
        if not isinstance(value, list) or not value:
            issues.append(("error", f"{cid}: {key} 必须是非空列表"))
            continue
        for tool in value:
            if not isinstance(tool, str) or not tool.strip():
                issues.append(("error", f"{cid}: {key} 含空或非字符串工具名"))
            elif known_tools and tool not in known_tools:
                issues.append(("warn", f"{cid}: {key} 的工具 {tool!r} 不在已知工具清单中（可能被写错）"))

    if "expect_no_error" in oracle and not isinstance(oracle["expect_no_error"], bool):
        issues.append(("error", f"{cid}: expect_no_error 必须是布尔值"))

    if case.get("requires_mount") and not case.get("follow_up"):
        issues.append(("info", f"{cid}: 挂载用例必须在挂载会话中执行，运行时需加 --use-mount"))

    return issues


def load_cases(directory: Path) -> List[Dict[str, Any]]:
    cases = []
    for path in sorted(directory.glob("*.json")):
        try:
            cases.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            cases.append({"__invalid__": True, "case_id": path.name, "message": str(exc)})
    return cases


def known_tool_names() -> List[str]:
    """Best-effort tool list for typo checking.

    Sources, in order of authority:
      1. the browser-mount contract (declares the file/Git tools the platform
         advertises) — captured in evidence/platform_mount_contract.json;
      2. tool names actually observed in recorded runs.
    """
    names = set()

    contract_path = ROOT / "evidence" / "platform_mount_contract.json"
    if contract_path.is_file():
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            tools = (contract.get("contract") or {}).get("tools") or []
            names.update(str(t) for t in tools)
        except json.JSONDecodeError:
            pass

    runs = ROOT / "evidence" / "platform_runs.jsonl"
    if runs.is_file():
        for line in runs.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            for name in record.get("tool_names") or []:
                names.add(str(name))
    return sorted(names)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Lint Harness case definitions")
    parser.add_argument("--cases", default=str(ROOT / "platform_cases"))
    parser.add_argument("--known-tools", default="auto", help="'auto' 或逗号分隔的工具名清单")
    args = parser.parse_args(argv)

    directory = Path(args.cases)
    if not directory.is_dir():
        print(f"ERROR: not a directory: {directory}", file=sys.stderr)
        return 2

    if args.known_tools == "auto":
        tools = known_tool_names()
    else:
        tools = [t.strip() for t in args.known_tools.split(",") if t.strip()]

    cases = load_cases(directory)
    seen: Dict[str, int] = {}
    total_errors = 0
    total_warns = 0
    print(f"检查 {len(cases)} 个用例（目录：{directory}）")
    print(f"已知工具名 {len(tools)} 个（用于拼写检查）\n")

    for case in cases:
        cid = str(case.get("case_id", "?"))
        if case.get("__invalid__"):
            print(f"[error] {cid}: JSON 解析失败：{case.get('message')}")
            total_errors += 1
            continue
        seen[cid] = seen.get(cid, 0) + 1
        issues = lint_case(case, tools)
        if not issues:
            print(f"[ok]   {cid}")
            continue
        for severity, message in issues:
            print(f"[{severity:5s}] {message}")
            if severity == "error":
                total_errors += 1
            elif severity == "warn":
                total_warns += 1

    duplicates = {cid: n for cid, n in seen.items() if n > 1}
    for cid, n in duplicates.items():
        print(f"[error] case_id {cid!r} 重复 {n} 次（run_id 与证据会混淆）")
        total_errors += 1

    print(f"\n结果：{total_errors} 个错误，{total_warns} 个警告，{len(cases)} 个用例")
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
