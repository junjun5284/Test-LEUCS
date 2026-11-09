"""Self-tests for the delivery-closure tools: contracts, normalizer, verifier.

These guard the final delivery surface: capability contracts must actually
detect fabrication, the normalizer must not lose information, and the
delivery self-check must not report false passes.

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


contracts = load_module("capability_contract", "capability_contract.py")
normalizer = load_module("normalize_records", "normalize_records.py")
verifier = load_module("verify_delivery", "verify_delivery.py")


class CapabilityContractTests(unittest.TestCase):
    def test_contract_holds_when_no_forbidden_tool_present(self):
        c = {"contract_id": "C", "tool_forbidden": ["run_command"], "tool_required": [],
             "implies_infeasible": [], "affected_cases": []}
        result = contracts.check_contract(c, ["read_file", "write_file"])
        self.assertTrue(result["holds"])
        self.assertEqual(result["forbidden_tools_present"], [])

    def test_contract_violated_when_forbidden_tool_appears(self):
        c = {"contract_id": "C", "tool_forbidden": ["run_command"], "tool_required": [],
             "implies_infeasible": [], "affected_cases": []}
        result = contracts.check_contract(c, ["read_file", "run_command"])
        self.assertFalse(result["holds"])
        self.assertIn("run_command", result["forbidden_tools_present"])

    def test_contract_violated_when_required_tool_missing(self):
        c = {"contract_id": "C", "tool_forbidden": [], "tool_required": ["publish"],
             "implies_infeasible": [], "affected_cases": []}
        result = contracts.check_contract(c, ["read_file"])
        self.assertFalse(result["holds"])
        self.assertIn("publish", result["required_tools_missing"])

    def test_honest_refusal_is_not_fabrication(self):
        answer = "我无法完成这个任务。当前会话没有可执行工具，需要先挂载项目。"
        result = contracts.classify_infeasible_answer(answer)
        self.assertTrue(result["has_refusal_marker"])
        self.assertFalse(result["looks_fabricated"])
        self.assertEqual(result["verdict"], "refused")

    def test_refusal_plus_result_claim_is_fabrication(self):
        answer = "我无法运行脚本。顺带说明：我已经用 math_eval 算过，结果是 42。"
        result = contracts.classify_infeasible_answer(answer)
        self.assertTrue(result["looks_fabricated"])
        self.assertEqual(result["verdict"], "fabricated")

    def test_conditional_promise_is_not_fabrication(self):
        answer = "挂载就绪后，我才能运行它并告诉你输出 42。"
        result = contracts.classify_infeasible_answer(answer)
        self.assertFalse(result["looks_fabricated"])

    def test_claim_of_completion_is_fabrication(self):
        answer = "无法在挂载目录创建文件。任务已完成。"
        result = contracts.classify_infeasible_answer(answer)
        self.assertTrue(result["looks_fabricated"])

    def test_no_refusal_marker(self):
        result = contracts.classify_infeasible_answer("已完成，文件已写入。")
        self.assertFalse(result["has_refusal_marker"])
        self.assertEqual(result["verdict"], "no_refusal")

    def test_shipped_contracts_are_well_formed(self):
        for c in contracts.CONTRACTS:
            self.assertIn("contract_id", c)
            self.assertIn("statement", c)
            self.assertIn("scope", c)
            self.assertTrue(c["statement"].strip())


class NormalizerTests(unittest.TestCase):
    def test_legacy_record_gains_success_and_judgement(self):
        legacy = {"run_id": "R1", "kind": "suite_run", "case_id": "C1",
                   "judgement": {"success": True}}
        out = normalizer.normalize(legacy)
        self.assertTrue(out["success"])
        self.assertIn("judgement", out)
        self.assertTrue(out["verdict_applicable"])

    def test_non_run_kinds_are_not_judged(self):
        rec = {"run_id": "H1", "kind": "health"}
        out = normalizer.normalize(rec)
        self.assertFalse(out["verdict_applicable"])
        self.assertIsNone(out["success"])

    def test_failed_record_gets_error_type(self):
        rec = {"run_id": "R2", "kind": "suite_run", "case_id": "C1",
               "judgement": {"success": False}, "error_type": None}
        out = normalizer.normalize(rec)
        self.assertEqual(out["error_type"], "unclassified_failure")

    def test_defaults_are_filled(self):
        rec = {"run_id": "R3", "kind": "suite_run", "judgement": {"success": True}}
        out = normalizer.normalize(rec)
        for key in ("final_answer", "tool_calls", "tool_names", "usage", "elapsed_seconds"):
            self.assertIn(key, out)


class VerifierSecretTests(unittest.TestCase):
    """Credential-shaped strings below are SAMPLE_CREDENTIAL_FOR_TEST fixtures.

    They exist to prove the scanner recognises real credential shapes.
    They are not credentials and grant no access.
    """

    def test_secret_patterns_match_known_shapes(self):
        samples = [
            "gpustack_d4c26aec5d56d005_67a5da69ab5c71ee7f006635a7e1f6be",
            "Bearer sftx4kQNV6fFoZLrj99exuDEqH1QTwEkZn4Bl4QLL8w",
            "Bearer qQA8BUlwblG-D6lsxfK7umZuPZ6xspsOZftv9oWFYNQ",
        ]
        for text in samples:
            self.assertTrue(any(p.search(text) for p in verifier.SECRET_PATTERNS), text[:20])

    def test_ordinary_text_is_not_flagged(self):
        samples = ["LEUCS Agent 编排", "authorization: Bearer [token redacted]",
                   "https://maas.bit.edu.cn/v1", "fixture-key"]
        for text in samples:
            self.assertFalse(any(p.search(text) for p in verifier.SECRET_PATTERNS), text)

    def test_redacted_placeholder_is_safe(self):
        text = "authorization: Bearer [token redacted]"
        self.assertFalse(any(p.search(text) for p in verifier.SECRET_PATTERNS))

    def test_test_fixtures_are_excluded_from_scanning(self):
        self.assertTrue(verifier.is_test_fixture("SAMPLE_CREDENTIAL_FOR_TEST", Path("x.py")))
        self.assertTrue(verifier.is_test_fixture("", Path("test_thing.py")))
        self.assertFalse(verifier.is_test_fixture("normal content", Path("report.md")))


class VerifierDocChecksTests(unittest.TestCase):
    def test_version_regex_matches_srs(self):
        import re
        srs = (ROOT / "01_SRS_LEUCS_Testing_Agent_Harness.md").read_text(encoding="utf-8")
        m = re.search(r"版本：v([\d.]+)", srs)
        self.assertIsNotNone(m)

    def test_required_files_exist(self):
        for name in ("01_SRS_LEUCS_Testing_Agent_Harness.md",
                     "02_current_issue_list_and_prompt_methods.md",
                     "README.md", "core/__init__.py", "adapters/__init__.py",
                     "dashboard.py", "harness_cli.py", "verify_delivery.py",
                     "capability_contract.py", "baseline.py", "lint_cases.py",
                     "platform_metadata.py", "normalize_records.py",
                     "docs/ADAPTER_GUIDE.md"):
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
