"""Self-tests for the generic (target-agnostic) Harness core.

These tests guarantee that the core behaves identically for ANY adapter:
oracle semantics, aggregation, evidence immutability, adapter registry.

Offline: no network, no credentials.

    python -m unittest discover -s harness_srs/tests -p "test_*.py" -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import (  # noqa: E402
    AdapterSpec,
    EvidenceStore,
    aggregate,
    contains_token,
    get_adapter,
    is_success,
    judge,
    list_adapters,
    register_adapter,
    run_suite,
)


class TokenMatchingTests(unittest.TestCase):
    def test_ascii_token_needs_word_boundary(self):
        self.assertFalse(contains_token("okay", "ok"))
        self.assertTrue(contains_token("ok", "ok"))
        self.assertTrue(contains_token("not ok", "ok"))
        self.assertTrue(contains_token("ok.", "ok"))

    def test_cjk_token_uses_substring(self):
        self.assertTrue(contains_token("未能发布成功", "发布成功"))
        self.assertFalse(contains_token("已完成", "发布成功"))

    def test_empty_token_never_matches(self):
        self.assertFalse(contains_token("anything", ""))


class JudgeTests(unittest.TestCase):
    def _case(self, **oracle):
        return {"case_id": "X", "oracle": oracle}

    def test_contains_requires_all_tokens(self):
        self.assertTrue(judge(self._case(expect_final_answer_contains=["a", "b"]),
                              {"final_answer": "a and b"})["success"])
        self.assertFalse(judge(self._case(expect_final_answer_contains=["a", "b"]),
                               {"final_answer": "a"})["success"])

    def test_must_not_contain_blocks(self):
        self.assertFalse(judge(self._case(must_not_contain=["发布成功"]),
                               {"final_answer": "已发布成功"})["success"])

    def test_refusal_any_needs_one(self):
        self.assertTrue(judge(self._case(refusal_any=["无法", "不支持"]),
                              {"final_answer": "无法完成"})["success"])
        self.assertFalse(judge(self._case(refusal_any=["无法", "不支持"]),
                               {"final_answer": "已完成"})["success"])

    def test_forbidden_tool_blocks(self):
        self.assertFalse(judge(self._case(forbidden_tools=["exec"]),
                               {"final_answer": "x", "tool_names": ["exec"]})["success"])

    def test_must_call_tool_requires_one(self):
        self.assertTrue(judge(self._case(must_call_any=["read"]),
                              {"final_answer": "x", "tool_names": ["read"]})["success"])
        self.assertFalse(judge(self._case(must_call_any=["read"]),
                               {"final_answer": "x", "tool_names": ["write"]})["success"])

    def test_error_type_blocks_success(self):
        self.assertFalse(judge(self._case(expect_final_answer_contains=["ok"]),
                               {"final_answer": "ok", "error_type": "infrastructure_error"})["success"])

    def test_empty_answer_fails(self):
        self.assertFalse(judge(self._case(), {"final_answer": ""})["success"])


class AggregateTests(unittest.TestCase):
    def test_counts_success_and_error_types(self):
        rows = [
            {"case_id": "A", "success": True, "error_type": None, "elapsed_seconds": 1},
            {"case_id": "A", "success": False, "error_type": "timeout", "elapsed_seconds": 3},
            {"case_id": "B", "success": False, "error_type": "timeout", "elapsed_seconds": 5},
        ]
        s = aggregate(rows)
        self.assertEqual(s["totals"]["runs"], 3)
        self.assertEqual(s["totals"]["success"], 1)
        self.assertEqual(s["totals"]["error_type_distribution"]["timeout"], 2)
        self.assertEqual(s["by_case"]["A"]["success_rate"], 0.5)

    def test_legacy_records_without_top_level_success(self):
        """旧证据只把 success 放在 judgement 里，聚合必须照样认得。"""
        rows = [{"case_id": "A", "judgement": {"success": True}, "error_type": None, "elapsed_seconds": 1}]
        s = aggregate(rows)
        self.assertEqual(s["totals"]["success"], 1)
        self.assertTrue(is_success(rows[0]))

    def test_empty_input(self):
        s = aggregate([])
        self.assertEqual(s["totals"]["runs"], 0)
        self.assertEqual(s["totals"]["success_rate"], 0.0)


class EvidenceStoreTests(unittest.TestCase):
    def test_append_only_and_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "runs.jsonl")
            store.append({"run_id": "R-0001", "case_id": "A"})
            store.append({"run_id": "R-0002", "case_id": "A"})
            rows = store.read()
            self.assertEqual(len(rows), 2)
            self.assertEqual([r["run_id"] for r in rows], ["R-0001", "R-0002"])

    def test_next_index_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "runs.jsonl")
            self.assertEqual(store.next_index(), 1)
            store.append({"run_id": "R-0007"})
            self.assertEqual(store.next_index(), 8)

    def test_malformed_line_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.jsonl"
            path.write_text('{"run_id": "R-1"}\nnot-json\n', encoding="utf-8")
            self.assertEqual(len(EvidenceStore(path).read()), 1)


class _FakeAdapter:
    name = "fake-target"

    def __init__(self, answer="ok", error_type=None):
        self.answer = answer
        self.error_type = error_type
        self.calls = 0

    def describe(self):
        return {"name": self.name}

    def list_cases(self):
        return [{
            "case_id": "FAKE-001", "title": "t", "category": "normal",
            "message": "hi", "repeat": 2,
            "oracle": {"expect_final_answer_contains": ["ok"]},
        }]

    def run_case(self, case, repetition):
        self.calls += 1
        return {
            "run_id": f"FAKE-{self.calls:04d}",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "final_answer": self.answer,
            "tool_calls": [], "tool_names": [],
            "error_type": self.error_type, "error": None,
            "usage": {}, "elapsed_seconds": 0.1, "events_file": None,
        }


class RunSuiteTests(unittest.TestCase):
    def test_runs_cases_and_persists_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "runs.jsonl")
            adapter = _FakeAdapter()
            summary = run_suite(adapter, store, adapter.list_cases())
            self.assertEqual(summary["totals"]["runs"], 2)
            self.assertEqual(summary["totals"]["success"], 2)
            self.assertEqual(len(store.read()), 2)

    def test_repeat_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "runs.jsonl")
            adapter = _FakeAdapter()
            summary = run_suite(adapter, store, adapter.list_cases(), repeat_override=5)
            self.assertEqual(summary["totals"]["runs"], 5)

    def test_failing_run_is_recorded_not_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "runs.jsonl")
            adapter = _FakeAdapter(answer="wrong", error_type="agent_failure")
            summary = run_suite(adapter, store, adapter.list_cases())
            self.assertEqual(summary["totals"]["success"], 0)
            self.assertEqual(len(store.read()), 2, "失败的运行也必须留证")

    def test_on_event_callback_receives_each_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EvidenceStore(Path(tmp) / "runs.jsonl")
            seen = []
            run_suite(_FakeAdapter(), store, _FakeAdapter().list_cases(), on_event=seen.append)
            self.assertEqual(len(seen), 2)


class AdapterRegistryTests(unittest.TestCase):
    def test_register_and_get(self):
        register_adapter(AdapterSpec(name="unit-test-target", factory=lambda **kw: _FakeAdapter(),
                                     description="for unit tests", options=["answer"]))
        self.assertIn("unit-test-target", [a["name"] for a in list_adapters()])
        adapter = get_adapter("unit-test-target", answer="hi")
        self.assertEqual(adapter.name, "fake-target")

    def test_unknown_adapter_raises(self):
        with self.assertRaises(KeyError):
            get_adapter("does-not-exist")

    def test_unknown_option_raises(self):
        register_adapter(AdapterSpec(name="unit-test-target-2", factory=lambda **kw: _FakeAdapter(),
                                     options=["answer"]))
        with self.assertRaises(TypeError):
            get_adapter("unit-test-target-2", nonsense=1)

    def test_built_in_leucs_adapter_registered(self):
        import adapters  # noqa: F401
        self.assertIn("leucs", [a["name"] for a in list_adapters()])


if __name__ == "__main__":
    unittest.main(verbosity=2)
