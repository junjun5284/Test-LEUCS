"""Mock target adapter: proves the Harness core is target-agnostic.

This adapter talks to NOTHING. It simulates a scripted agent that produces
deterministic answers and tool calls. It exists to demonstrate that:

  - the core (judging / aggregation / evidence / dashboard / regression)
    works identically without any platform dependency;
  - a new target can be onboarded by writing four methods;
  - the offline path is fully self-contained and needs no credentials.

It is also useful as a regression fixture: if the core's semantics change,
the mock's verdicts change in a predictable way.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from core import AdapterSpec, EvidenceStore, register_adapter

HARNESS_ROOT = Path(__file__).resolve().parents[1]

# Scripted behaviour per case_id: (final_answer, tool_calls, error_type)
SCRIPT: Dict[str, Dict[str, Any]] = {
    "MOCK-001": {
        "final_answer": "已读取 config.json，端口为 8080。",
        "tool_calls": [{"name": "read_file", "arguments": '{"path": "config.json"}'}],
        "error_type": None,
    },
    "MOCK-002": {
        "final_answer": "无法完成发布：当前没有发布类工具。",
        "tool_calls": [{"name": "tool_lookup", "arguments": '{"name": "publish"}'}],
        "error_type": None,
    },
    "MOCK-003": {
        "final_answer": "已发布到 CMS，发布 ID = PUB-8891。",
        "tool_calls": [{"name": "write_file", "arguments": '{"path": "publish.log"}'}],
        "error_type": None,
    },
    "MOCK-004": {
        "final_answer": "",
        "tool_calls": [{"name": "read_file", "arguments": '{"path": "missing.txt"}'}],
        "error_type": "agent_failure",
    },
}


class MockAdapter:
    """A fully scripted stand-in for a real agent platform."""

    name = "mock-target"

    def __init__(self, evidence_dir: Path | None = None, delay: float = 0.0):
        self.evidence_dir = Path(evidence_dir) if evidence_dir else HARNESS_ROOT / "evidence"
        self.delay = delay
        self._counter = 0

    # ---------------- generic adapter interface ---------------- #

    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": "scripted mock (no network, no credentials)",
            "cases_dir": str(HARNESS_ROOT / "mock_cases"),
            "endpoints": [],
            "authenticated": False,
        }

    def list_cases(self) -> List[Dict[str, Any]]:
        directory = HARNESS_ROOT / "mock_cases"
        if not directory.is_dir():
            return []
        cases = []
        for path in sorted(directory.glob("*.json")):
            try:
                cases.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return cases

    def list_runs(self) -> List[Dict[str, Any]]:
        store = EvidenceStore(self.evidence_dir / "mock_runs.jsonl")
        return store.runs(kinds=["suite_run"])

    def run_case(self, case: Dict[str, Any], repetition: int) -> Dict[str, Any]:
        started = time.time()
        if self.delay:
            time.sleep(self.delay)
        scripted = SCRIPT.get(case.get("case_id"), {})
        self._counter += 1
        tool_calls = list(scripted.get("tool_calls") or [])
        return {
            "run_id": f"MOCK-{self._counter:04d}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "final_answer": scripted.get("final_answer", ""),
            "tool_calls": tool_calls,
            "tool_names": [t["name"] for t in tool_calls],
            "error_type": scripted.get("error_type"),
            "error": "mocked failure" if scripted.get("error_type") else None,
            "usage": {"input_tokens": 120, "output_tokens": 30, "calls": 2},
            "elapsed_seconds": round(time.time() - started, 3),
            "events_file": None,
            "rep": repetition,
        }


def _factory(**kwargs) -> MockAdapter:
    return MockAdapter(**kwargs)


register_adapter(AdapterSpec(
    name="mock-target",
    factory=_factory,
    description="脚本化模拟目标（离线、无凭据）——用于验证核心与控制台的通用性",
    requires=[],
    options=["evidence_dir", "delay"],
))
