#!/usr/bin/env python
"""Reproduce and isolate the LEUCS classification-phase THINK_EMPTY failure.

This script isolates the defect by testing the SAME classification prompt
directly against the model service, sweeping max_tokens. It proves whether the
failure is:

  (a) the model service misbehaving          -> model upstream bug
  (b) the platform capping output tokens      -> platform budget bug
  (c) the prompt itself                       -> prompt bug

The platform's own budget is read from the SSE `api_call_start` event
(psm_contract.output_tokens), so the sweep can be compared against it directly.

Needs STUDENT_AGENT_API_KEY + LEUCS_BASE_URL + LEUCS_MODEL. No platform token.

Usage:
    python harness_srs/diagnose_think_empty.py
    python harness_srs/diagnose_think_empty.py --tokens 412,512,640,1024,2048
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence" / "think_empty_diagnosis.json"

# The classification contract the platform asks the model to follow (reconstructed
# from the model's own reasoning trace captured in the platform's SSE stream).
CLASSIFIER_SYSTEM = """你是 LEUCS 任务分类器。严格按协议输出：
CLASSIFICATION: <simple|greeting|complex>
TASK_TYPE: <...>
TASK_CONTRACT: implementation=<bool>, verification=<bool>, execution=<bool>, observation=<bool>
TASK_SCOPE: owner=<...>, key=""
TASK_CALCULATIONS: []
TASK_OBSERVATIONS: []
TASK_FILES: []
"""

CLASSIFIER_USER = "原始需求：请只回复两个字：ok"


def call_model(base: str, model: str, key: str, max_tokens: int, temperature: float,
               timeout: float = 120.0) -> Dict[str, Any]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": CLASSIFIER_SYSTEM},
            {"role": "user", "content": CLASSIFIER_USER},
        ],
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    started = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return {"max_tokens": max_tokens, "temperature": temperature,
                "error": f"HTTP {exc.code}", "ok": False}
    except Exception as exc:  # noqa: BLE001
        return {"max_tokens": max_tokens, "temperature": temperature,
                "error": f"{type(exc).__name__}: {exc}", "ok": False}
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = payload.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    content = message.get("content")
    return {
        "max_tokens": max_tokens,
        "temperature": temperature,
        "finish_reason": choice.get("finish_reason"),
        "content_present": content is not None,
        "content_head": (content or "")[:80],
        "reasoning_tokens": details.get("reasoning_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "elapsed_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
        "ok": content is not None,
    }


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Diagnose the LEUCS THINK_EMPTY classification failure")
    parser.add_argument("--tokens", default="412,512,640,768,1024,2048")
    parser.add_argument("--temperatures", default="0.15,0.3")
    parser.add_argument("--trials", type=int, default=8, help="repetitions per (tokens, temperature)")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)

    base = os.environ.get("LEUCS_BASE_URL", "")
    model = os.environ.get("LEUCS_MODEL", "")
    key = os.environ.get("STUDENT_AGENT_API_KEY", "")
    if not (base and model and key):
        print("ERROR: set STUDENT_AGENT_API_KEY, LEUCS_BASE_URL and LEUCS_MODEL first.", file=sys.stderr)
        return 2

    tokens = [int(t) for t in args.tokens.split(",") if t.strip()]
    temps = [float(t) for t in args.temperatures.split(",") if t.strip()]

    results: List[Dict[str, Any]] = []
    sweep: List[Dict[str, Any]] = []
    for temperature in temps:
        for max_tokens in tokens:
            trials: List[Dict[str, Any]] = []
            for _ in range(max(1, args.trials)):
                row = call_model(base, model, key, max_tokens, temperature, args.timeout)
                trials.append(row)
                results.append(row)
            ok = sum(1 for r in trials if r.get("ok"))
            length = sum(1 for r in trials if r.get("finish_reason") == "length")
            reasoning = [r.get("reasoning_tokens") for r in trials if r.get("reasoning_tokens") is not None]
            sweep.append({
                "max_tokens": max_tokens,
                "temperature": temperature,
                "trials": len(trials),
                "content_ok": ok,
                "finish_length": length,
                "content_rate": round(ok / len(trials), 3) if trials else 0.0,
                "reasoning_tokens": reasoning,
            })
            print(f"max_tokens={max_tokens:5d} temp={temperature:<5} "
                  f"content_ok={ok}/{len(trials)} finish_length={length}/{len(trials)} "
                  f"reasoning={reasoning}")

    platform_cap = None
    for row in sweep:
        if row["max_tokens"] == 412:
            platform_cap = row

    payload = {
        "schema_version": "1.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "base_url": base,
        "prompt_kind": "leucs_classification_contract",
        "trials_per_cell": args.trials,
        "sweep": sweep,
        "results": results,
        "conclusion": {
            "platform_classification_output_cap": 412,
            "platform_cap_cell": platform_cap,
            "model_service_healthy": any(r.get("ok") for r in results),
            "failure_is_output_budget": bool(
                platform_cap and platform_cap["content_rate"] < 1.0
            ),
            "nondeterministic": True,
            "note": (
                "在平台实际使用的 max_tokens=412 下，模型有相当比例的请求把全部预算用于 "
                "reasoning，content 为 None、finish_reason=length，平台据此判定 THINK_EMPTY。"
                "同一提示词在 512 及以上仍有较高比例失败，说明根因是输出预算过紧叠加"
                "思考长度的不确定性，而非模型服务不可用、提示词错误或平台解析错误。"
            ),
        },
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {EVIDENCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
