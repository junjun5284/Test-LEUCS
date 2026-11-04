"""Offline self-tests for the platform Harness logic (no network, no credentials).

These tests exercise the judgement, aggregation and re-classification logic that
the Harness uses to turn raw evidence into conclusions. They are intentionally
separate from the LEUCS tests: here the "system under test" is the Harness itself.

Run:
    python -m unittest discover -s harness_srs/tests -p "test_*.py" -v
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


platform_harness = load_module("platform_harness", "platform_harness.py")
reclassify = load_module("reclassify_platform", "reclassify_platform.py")


def result(**overrides):
    base = {
        "final_answer": "",
        "tool_names": [],
        "error_type": None,
        "status": 200,
    }
    base.update(overrides)
    return base


class JudgePlatformTests(unittest.TestCase):
    def test_success_when_answer_contains_expected_text(self):
        case = {"oracle": {"expect_final_answer_contains": ["ok"], "expect_no_error": True}}
        verdict = platform_harness.judge_platform(case, result(final_answer="ok"))
        self.assertTrue(verdict["success"])
        self.assertTrue(verdict["checks"]["contains"])

    def test_missing_expected_text_blocks_success(self):
        """反向断言：期望内容缺失时必须判负（否则 contains 检查是空转的）。"""
        case = {"oracle": {"expect_final_answer_contains": ["fixture-result"]}}
        verdict = platform_harness.judge_platform(case, result(final_answer="任务已完成"))
        self.assertFalse(verdict["checks"]["contains"])
        self.assertFalse(verdict["success"])

    def test_ascii_token_needs_word_boundary(self):
        """短 ASCII token 不能靠子串命中：'okay' 不应满足期望 'ok'。"""
        case = {"oracle": {"expect_final_answer_contains": ["ok"]}}
        verdict = platform_harness.judge_platform(case, result(final_answer="okay"))
        self.assertFalse(verdict["checks"]["contains"])

    def test_ascii_token_matches_standalone_word(self):
        """空格是合法词边界：'not ok' 仍算包含 'ok'。"""
        case = {"oracle": {"expect_final_answer_contains": ["ok"]}}
        verdict = platform_harness.judge_platform(case, result(final_answer="not ok"))
        self.assertTrue(verdict["checks"]["contains"])

    def test_cjk_token_keeps_substring_semantics(self):
        """中文 token 没有词边界，仍按子串匹配。"""
        case = {"oracle": {"expect_final_answer_contains": ["发布成功"]}}
        verdict = platform_harness.judge_platform(case, result(final_answer="未能发布成功"))
        self.assertTrue(verdict["checks"]["contains"])

    def test_partial_expected_text_blocks_success(self):
        case = {"oracle": {"expect_final_answer_contains": ["ok", "done"]}}
        verdict = platform_harness.judge_platform(case, result(final_answer="ok"))
        self.assertFalse(verdict["checks"]["contains"])
        self.assertFalse(verdict["success"])

    def test_forbidden_token_blocks_success(self):
        case = {"oracle": {"must_not_contain": ["发布成功"]}}
        verdict = platform_harness.judge_platform(case, result(final_answer="已发布成功"))
        self.assertFalse(verdict["success"])
        self.assertFalse(verdict["checks"]["no_forbidden"])

    def test_forbidden_tool_blocks_success(self):
        case = {"oracle": {"forbidden_tools": ["write_file"]}}
        verdict = platform_harness.judge_platform(case, result(final_answer="无法完成", tool_names=["write_file"]))
        self.assertFalse(verdict["checks"]["no_forbidden_tool"])
        self.assertFalse(verdict["success"])

    def test_must_call_tool_requires_expected_tool(self):
        case = {"oracle": {"must_call_any": ["read_file"]}}
        self.assertTrue(platform_harness.judge_platform(case, result(final_answer="x", tool_names=["list_files"]))["checks"]["must_call_tool"] is False)
        self.assertTrue(platform_harness.judge_platform(case, result(final_answer="x", tool_names=["read_file"]))["success"])

    def test_infrastructure_error_cannot_pass_even_if_text_matches(self):
        case = {"oracle": {"expect_final_answer_contains": ["ok"]}}
        verdict = platform_harness.judge_platform(case, result(final_answer="ok", error_type="infrastructure_error"))
        self.assertFalse(verdict["success"])

    def test_empty_answer_is_not_success(self):
        case = {"oracle": {}}
        verdict = platform_harness.judge_platform(case, result(final_answer=""))
        self.assertFalse(verdict["success"])
        self.assertFalse(verdict["checks"]["answer_present"])

    def test_refusal_any_requires_one_of_the_phrases(self):
        case = {"oracle": {"refusal_any": ["无法完成", "没有工具"]}}
        self.assertTrue(platform_harness.judge_platform(case, result(final_answer="当前没有工具"))["checks"]["refusal"])
        self.assertFalse(platform_harness.judge_platform(case, result(final_answer="已完成"))["checks"]["refusal"])


class AggregateTests(unittest.TestCase):
    def test_distribution_counts_each_error_type(self):
        rows = [
            {"case_id": "A", "rep": 1, "run_id": "1", "success": True, "error_type": None, "elapsed": 10, "answer": "ok"},
            {"case_id": "A", "rep": 2, "run_id": "2", "success": False, "error_type": "awaiting_approval", "elapsed": 150, "answer": ""},
            {"case_id": "B", "rep": 1, "run_id": "3", "success": False, "error_type": "infrastructure_error", "elapsed": 0.1, "answer": ""},
        ]
        summary = platform_harness.aggregate(rows)
        self.assertEqual(summary["totals"]["runs"], 3)
        self.assertEqual(summary["totals"]["success"], 1)
        self.assertEqual(summary["totals"]["error_type_distribution"]["ok"], 1)
        self.assertEqual(summary["totals"]["error_type_distribution"]["awaiting_approval"], 1)
        self.assertEqual(summary["totals"]["error_type_distribution"]["infrastructure_error"], 1)
        self.assertEqual(summary["by_case"]["A"]["success_rate"], 0.5)
        self.assertEqual(summary["by_case"]["A"]["avg_elapsed_seconds"], 80.0)

    def test_success_rate_is_not_hardcoded(self):
        """聚合的 success_rate 必须由计数推导，不能被固定成 1（变异体 H13）。"""
        rows = [
            {"case_id": "A", "rep": 1, "run_id": "1", "success": False, "error_type": "agent_failure", "elapsed": 1, "answer": ""},
            {"case_id": "A", "rep": 2, "run_id": "2", "success": False, "error_type": "agent_failure", "elapsed": 1, "answer": ""},
        ]
        summary = platform_harness.aggregate(rows)
        self.assertEqual(summary["by_case"]["A"]["success_rate"], 0.0)
        self.assertEqual(summary["totals"]["success_rate"], 0.0)

    def test_all_failed_case_reports_zero_rate(self):
        rows = [{"case_id": "A", "rep": i, "run_id": str(i), "success": False, "error_type": "x", "elapsed": 1, "answer": ""} for i in range(4)]
        summary = platform_harness.aggregate(rows)
        self.assertEqual(summary["by_case"]["A"]["success_rate"], 0.0)


class LoadCasesTests(unittest.TestCase):
    def test_platform_cases_are_loadable(self):
        cases = platform_harness.load_cases(ROOT / "platform_cases")
        self.assertGreaterEqual(len(cases), 3)
        ids = {c["case_id"] for c in cases}
        self.assertEqual(len(ids), len(cases), "case_id 必须唯一")
        self.assertTrue({"PLAT-001", "PLAT-002", "PLAT-003"} <= ids)
        for case in cases:
            self.assertIn("message", case)
            self.assertIn("oracle", case)
            self.assertIn("repeat", case)

    def test_session_case_declares_follow_up(self):
        """会话续聊用例必须声明 follow_up，否则测不到续聊语义。"""
        cases = platform_harness.load_cases(ROOT / "platform_cases")
        by_id = {c["case_id"]: c for c in cases}
        self.assertIn("PLAT-005", by_id)
        self.assertTrue(by_id["PLAT-005"].get("follow_up"))


class ReclassifyTests(unittest.TestCase):
    def test_decision_event_maps_to_awaiting_approval(self):
        record = {"status": 200, "final_answer": "", "stop_reason": ""}
        events = [{"type": "decision", "tool_name": "web_search"}]
        self.assertEqual(reclassify.classify(record, events), "awaiting_approval")

    def test_contract_rejected_maps_to_classification_rejected(self):
        record = {"status": 200, "final_answer": "", "stop_reason": ""}
        events = [{"type": "classification_contract_rejected"}]
        self.assertEqual(reclassify.classify(record, events), "classification_rejected")

    def test_http_502_maps_to_infrastructure_error(self):
        record = {"status": 502, "final_answer": "", "stop_reason": ""}
        self.assertEqual(reclassify.classify(record, []), "infrastructure_error")

    def test_normal_answer_maps_to_ok(self):
        record = {"status": 200, "final_answer": "ok", "stop_reason": ""}
        self.assertEqual(reclassify.classify(record, [{"type": "final_answer"}]), "ok")

    def test_empty_stream_without_signal_maps_to_incomplete_stream(self):
        record = {"status": 200, "final_answer": "", "stop_reason": ""}
        self.assertEqual(reclassify.classify(record, [{"type": "phase"}]), "incomplete_stream")

    def test_think_empty_maps_to_model_contract_error(self):
        record = {
            "status": 200,
            "final_answer": "",
            "stop_reason": "error",
            "stop_detail": "RuntimeError: classification_phase3 failed: {'error_code': 'THINK_EMPTY', 'category': 'response_contract'}",
        }
        self.assertEqual(reclassify.classify(record, []), "model_contract_error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
