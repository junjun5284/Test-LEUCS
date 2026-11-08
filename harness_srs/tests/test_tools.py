"""Self-tests for the Harness support tools: linter, baseline comparison, metadata.

These tools decide whether a test campaign is trustworthy (are the cases sane?
did behaviour actually change?), so they need their own tests.

Offline: no network, no credentials.

    python -m unittest discover -s harness_srs/tests -p "test_*.py" -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint_cases = load_module("lint_cases", "lint_cases.py")
baseline = load_module("baseline", "baseline.py")
platform_metadata = load_module("platform_metadata", "platform_metadata.py")


def case(cid="C-001", **oracle):
    return {
        "case_id": cid,
        "title": "t",
        "category": "normal",
        "message": "hello",
        "repeat": 3,
        "oracle": oracle or {"expect_no_error": True},
    }


class LintTests(unittest.TestCase):
    def _errors(self, c):
        return [m for sev, m in lint_cases.lint_case(c, []) if sev == "error"]

    def _warns(self, c):
        return [m for sev, m in lint_cases.lint_case(c, []) if sev == "warn"]

    def test_valid_case_has_no_errors(self):
        self.assertEqual(self._errors(case()), [])

    def test_missing_case_id_is_error(self):
        c = case()
        del c["case_id"]
        self.assertTrue(self._errors(c))

    def test_empty_oracle_is_error(self):
        c = case()
        c["oracle"] = {}
        self.assertTrue(any("oracle" in m for m in self._errors(c)))

    def test_missing_message_is_error(self):
        c = case()
        del c["message"]
        self.assertTrue(any("message" in m for m in self._errors(c)))

    def test_overlapping_expect_and_forbid_is_error(self):
        c = case(expect_final_answer_contains=["ok"], must_not_contain=["ok"])
        self.assertTrue(any("交集" in m for m in self._errors(c)))

    def test_overlapping_refusal_and_forbid_is_error(self):
        c = case(refusal_any=["无法"], must_not_contain=["无法"])
        self.assertTrue(any("交集" in m for m in self._errors(c)))

    def test_unknown_oracle_key_is_warning(self):
        c = case(some_unknown_key=["x"])
        self.assertTrue(any("未知 oracle" in m for m in self._warns(c)))

    def test_repeat_one_is_warning(self):
        c = case()
        c["repeat"] = 1
        self.assertTrue(any("repeat=1" in m for m in self._warns(c)))

    def test_zero_repeat_is_error(self):
        c = case()
        c["repeat"] = 0
        self.assertTrue(any("repeat" in m for m in self._errors(c)))

    def test_unknown_tool_name_is_warning(self):
        c = case(must_call_any=["read_file"])
        issues = lint_cases.lint_case(c, ["write_file"])
        self.assertTrue(any("不在已知工具清单" in m for _, m in issues))

    def test_known_tool_name_no_warning(self):
        c = case(must_call_any=["read_file"])
        issues = lint_cases.lint_case(c, ["read_file", "write_file"])
        self.assertFalse(any("不在已知工具清单" in m for _, m in issues))

    def test_empty_token_list_is_error(self):
        c = case(expect_final_answer_contains=[])
        self.assertTrue(any("非空列表" in m for m in self._errors(c)))

    def test_non_boolean_expect_no_error_is_error(self):
        c = case(expect_no_error="yes")
        self.assertTrue(any("布尔值" in m for m in self._errors(c)))


class ProfileTests(unittest.TestCase):
    def _runs(self, success_flags, error_types=None):
        out = []
        for i, ok in enumerate(success_flags):
            out.append({
                "case_id": "X",
                "success": ok,
                "error_type": (error_types or [None] * len(success_flags))[i],
                "elapsed_seconds": 1.0,
            })
        return out

    def test_profile_counts(self):
        p = baseline.case_profile(self._runs([True, False, True]))
        self.assertEqual(p["n"], 3)
        self.assertEqual(p["successes"], 2)
        self.assertAlmostEqual(p["success_rate"], 0.667, places=3)

    def test_profile_counts_infrastructure_errors(self):
        p = baseline.case_profile(self._runs([False, False], ["infrastructure_error", None]))
        self.assertEqual(p["infrastructure_error"], 1)

    def test_legacy_records_with_judgement_are_counted(self):
        rows = [{"case_id": "X", "judgement": {"success": True}, "error_type": None, "elapsed_seconds": 1}]
        p = baseline.case_profile(rows)
        self.assertEqual(p["successes"], 1)


class ChangeClassificationTests(unittest.TestCase):
    def _p(self, successes, n, infra=0):
        return {"n": n, "successes": successes,
                "success_rate": round(successes / n, 3) if n else 0.0,
                "infrastructure_error": infra, "error_types": {}, "avg_elapsed": 1.0}

    def test_improved(self):
        self.assertEqual(baseline.classify_change(self._p(1, 3), self._p(3, 3)), "improved")

    def test_regressed(self):
        self.assertEqual(baseline.classify_change(self._p(3, 3), self._p(1, 3)), "regressed")

    def test_unchanged(self):
        self.assertEqual(baseline.classify_change(self._p(2, 3), self._p(2, 3)), "unchanged")

    def test_flaky_when_verdicts_mix_in_both(self):
        self.assertEqual(baseline.classify_change(self._p(1, 3), self._p(2, 3)), "flaky")

    def test_infrastructure_increase_is_inconclusive(self):
        before = self._p(3, 3)
        after = self._p(0, 3, infra=2)
        self.assertEqual(baseline.classify_change(before, after), "inconclusive")

    def test_empty_side_is_inconclusive(self):
        self.assertEqual(baseline.classify_change(self._p(0, 0), self._p(1, 3)), "inconclusive")


class CompareSnapshotsTests(unittest.TestCase):
    def _snap(self, cases, label="b"):
        return {"label": label, "captured_at": "2026-01-01", "totals": {}, "cases": cases}

    def test_only_shared_cases_compared(self):
        base = self._snap({"A": {"n": 1, "successes": 1, "success_rate": 1.0,
                                  "infrastructure_error": 0, "error_types": {}, "avg_elapsed": 1.0},
                           "B": {"n": 1, "successes": 1, "success_rate": 1.0,
                                 "infrastructure_error": 0, "error_types": {}, "avg_elapsed": 1.0}})
        cur = self._snap({"A": {"n": 1, "successes": 0, "success_rate": 0.0,
                                 "infrastructure_error": 0, "error_types": {}, "avg_elapsed": 1.0},
                          "C": {"n": 1, "successes": 1, "success_rate": 1.0,
                                "infrastructure_error": 0, "error_types": {}, "avg_elapsed": 1.0}})
        result = baseline.compare_snapshots(base, cur)
        self.assertEqual(result["cases_compared"], 1)
        self.assertEqual(result["cases_only_in_baseline"], ["B"])
        self.assertEqual(result["cases_only_in_current"], ["C"])
        self.assertEqual(result["regressed"], ["A"])

    def test_overall_verdict_regressed(self):
        base = self._snap({"A": {"n": 2, "successes": 2, "success_rate": 1.0,
                                  "infrastructure_error": 0, "error_types": {}, "avg_elapsed": 1.0}})
        cur = self._snap({"A": {"n": 2, "successes": 0, "success_rate": 0.0,
                                 "infrastructure_error": 0, "error_types": {}, "avg_elapsed": 1.0}})
        result = baseline.compare_snapshots(base, cur)
        self.assertEqual(result["overall_verdict"], "regressed")


class MetadataFingerprintTests(unittest.TestCase):
    def test_fingerprint_ignores_volatile_fields(self):
        a = {"build_id": "x", "mount_count": 1, "pool_badge": "拥挤", "model": "m"}
        b = {"build_id": "x", "mount_count": 0, "pool_badge": "空闲", "model": "m"}
        self.assertEqual(platform_metadata.fingerprint(a), platform_metadata.fingerprint(b))

    def test_fingerprint_changes_with_behaviour_fields(self):
        a = {"build_id": "x", "model": "m"}
        b = {"build_id": "x", "model": "other"}
        self.assertNotEqual(platform_metadata.fingerprint(a), platform_metadata.fingerprint(b))

    def test_compare_reports_changed_fields(self):
        base = {"captured_at": "t", "fingerprint": "f1", "model": "m", "max_output": 1024}
        cur = {"captured_at": "t2", "fingerprint": "f2", "model": "m", "max_output": 2048}
        result = platform_metadata.compare(cur, base)
        self.assertTrue(result["config_changed"])
        changed = {c["field"] for c in result["changed_fields"]}
        self.assertIn("max_output", changed)
        self.assertNotIn("model", changed)

    def test_compare_detects_no_change(self):
        snap = {"captured_at": "t", "fingerprint": "f1", "model": "m"}
        result = platform_metadata.compare(snap, dict(snap))
        self.assertFalse(result["config_changed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
