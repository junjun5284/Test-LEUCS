#!/usr/bin/env python
"""Platform-level Harness for the LEUCS web platform.

Targets the real website API (not the model API used by the runtime panel).

Confirmed endpoints (2026-10):
  GET  /api/leucs/health
  GET  /api/leucs/conversations
  GET  /api/leucs/conversation/{conv_id}
  GET  /api/leucs/conversation/{conv_id}/events
  GET  /api/lei-bit/accounts/feed?after=N         (poll cursor for conversation_updated)
  POST /api/lei-bit/chat                          (run the agent; SSE response)
  POST /api/leucs/conversation/{conv_id}/message  (save-only, does NOT run the agent)

Run request body (from the frontend bundle):
  {"message": "...", "conversation_id": "", "turn_id": "<uuid>",
   "turn_index": 1, "task_name": "leucs_main", "temperature": 0.7}

SSE events: user_input, start, phase, classify_6d, classification_*,
thinking_complete, api_call_*, context_inject, pipeline_transition,
turn_start, step_start, step, status, helper, prompt_injection,
llm_response_chunk, final_answer, step_end, turn_end, done.

Credentials come only from environment variables:
  LEUCS_PLATFORM_BASE   e.g. https://123.57.180.120
  LEUCS_PLATFORM_TOKEN  Bearer token from the browser session

The token is never written to evidence files.

Usage:
  python harness_srs/platform_harness.py health
  python harness_srs/platform_harness.py list
  python harness_srs/platform_harness.py conversation <conv_id>
  python harness_srs/platform_harness.py events <conv_id>
  python harness_srs/platform_harness.py feed --after 0
  python harness_srs/platform_harness.py run --text "请只回复两个字母：ok"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_BASE = "https://123.57.180.120"
EVIDENCE = Path(__file__).resolve().parent / "evidence" / "platform_runs.jsonl"
EVENTS_DIR = Path(__file__).resolve().parent / "evidence" / "platform_events"
SUMMARY = Path(__file__).resolve().parent / "evidence" / "platform_suite_summary.json"


def build_ssl_context(insecure: bool):
    if insecure:
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def redact(text: str, token: str) -> str:
    if token:
        text = text.replace(token, "[token redacted]")
    return text


def request(
    base: str,
    path: str,
    token: str,
    *,
    method: str = "GET",
    body: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
    insecure: bool = True,
) -> Dict[str, Any]:
    url = base.rstrip("/") + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"authorization": "Bearer " + token, "accept": "application/json"}
    if data is not None:
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    started = time.time()
    status: Any = None
    content_type = None
    payload = b""
    error = None
    try:
        ctx = build_ssl_context(insecure)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            status = resp.status
            content_type = resp.headers.get("content-type")
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        content_type = exc.headers.get("content-type") if exc.headers else None
        payload = exc.read()
        error = f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - recorded verbatim
        error = f"{type(exc).__name__}: {exc}"

    elapsed = round(time.time() - started, 2)
    text = payload.decode("utf-8", "replace")
    return {
        "path": path,
        "method": method,
        "status": status,
        "content_type": content_type,
        "elapsed_seconds": elapsed,
        "body_bytes": len(payload),
        "body_sha256": hashlib.sha256(payload).hexdigest(),
        "error": error,
        "text": redact(text, token),
    }


def post_decision(base: str, token: str, conv_id: str, choice: str, insecure: bool, timeout: float = 20.0) -> Dict[str, Any]:
    """POST /api/leucs/decision — answer a pending tool-permission card."""
    body = {"choice": choice, "conversation_id": conv_id}
    result = request(base, "/api/leucs/decision", token, method="POST", body=body, timeout=timeout, insecure=insecure)
    return {
        "choice": choice,
        "conversation_id": conv_id,
        "status": result.get("status"),
        "ok": bool(result.get("status") == 200 and '"success": true' in (result.get("text") or "").replace(" ", "")),
        "text": (result.get("text") or "")[:200],
    }


def run_chat(
    base: str,
    token: str,
    message: str,
    conversation_id: str,
    turn_index: int,
    task_name: str,
    temperature: float,
    timeout: float,
    insecure: bool,
    decision_policy: str = "none",
) -> Dict[str, Any]:
    """POST /api/lei-bit/chat and consume the SSE stream."""
    from http.client import HTTPSConnection

    turn_id = str(uuid.uuid4())
    body = {
        "message": message,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "turn_index": turn_index,
        "task_name": task_name,
        "temperature": temperature,
    }
    host = base.split("://", 1)[-1].split("/", 1)[0]
    started = time.time()
    events: List[Dict[str, Any]] = []
    status: Any = None
    content_type = None
    conv_id = conversation_id
    error = None
    buffer = ""
    decision_actions: List[Dict[str, Any]] = []
    handled_decisions: set = set()
    try:
        ctx = build_ssl_context(insecure)
        conn = HTTPSConnection(host, 443, context=ctx, timeout=timeout)
        conn.request(
            "POST",
            "/api/lei-bit/chat",
            body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )
        resp = conn.getresponse()
        status = resp.status
        content_type = resp.getheader("content-type")
        conv_id = resp.getheader("x-leucs-conversation-id") or conversation_id
        deadline = time.time() + timeout
        timed_out = False
        while time.time() < deadline:
            chunk = resp.read1(8192)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", "replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw in ("", "[DONE]"):
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                events.append(ev)
                if ev.get("type") == "decision" and decision_policy in ("approve", "deny"):
                    decision_id = str(ev.get("decision_id") or "")
                    if decision_id and decision_id not in handled_decisions:
                        handled_decisions.add(decision_id)
                        target_conv = conv_id or str(ev.get("conv_id") or "")
                        action = post_decision(base, token, target_conv, decision_policy, insecure)
                        action["decision_id"] = decision_id
                        action["tool_name"] = ev.get("tool_name")
                        decision_actions.append(action)
        else:
            timed_out = True
    except Exception as exc:  # noqa: BLE001
        timed_out = False
        error = f"{type(exc).__name__}: {exc}"

    elapsed = round(time.time() - started, 2)
    final_answer = ""
    usage: Dict[str, Any] = {}
    stop_reason = ""
    stop_detail = ""
    honest_failure = None
    api_error = ""
    decisions: List[Dict[str, Any]] = []
    contract_rejected = 0
    for ev in events:
        etype = ev.get("type")
        if etype == "final_answer":
            final_answer = str(ev.get("content") or "")
            honest_failure = (ev.get("metadata") or {}).get("honest_failure")
        elif etype == "done":
            usage = ev.get("usage") or {}
            stop_reason = str(ev.get("stop_reason") or "")
            stop_detail = str(ev.get("stop_detail") or "")
        elif etype == "decision":
            decisions.append({
                "decision_id": ev.get("decision_id"),
                "decision_type": ev.get("decision_type"),
                "tool_name": ev.get("tool_name"),
                "content": str(ev.get("content") or "")[:200],
            })
        elif etype == "classification_contract_rejected":
            contract_rejected += 1
        if ev.get("is_error"):
            api_error = str(ev.get("content") or "")[:300]
    if not api_error:
        for ev in events:
            text = str(ev.get("content") or "")
            if "api_error" in text or "HTTP_40" in text:
                api_error = text[:300]
                break

    tool_calls: List[Dict[str, Any]] = []
    for ev in events:
        if ev.get("type") == "tool_call":
            raw_args = ev.get("arguments")
            args_text = raw_args if isinstance(raw_args, str) else json.dumps(raw_args, ensure_ascii=False)
            tool_calls.append({"name": str(ev.get("tool_name") or ""), "arguments": args_text[:300]})
    tool_names = [c["name"] for c in tool_calls]

    http_status = status if isinstance(status, int) else None
    contract_text = (stop_detail or "") + " " + (api_error or "")
    error_type = None
    if http_status is not None and http_status != 200:
        error_type = "infrastructure_error"
    elif error and not events:
        error_type = "infrastructure_error"
    elif decisions and not decision_actions:
        error_type = "awaiting_approval"
    elif contract_rejected:
        error_type = "classification_rejected"
    elif "response_contract" in contract_text or "THINK_EMPTY" in contract_text:
        error_type = "model_contract_error"
    elif api_error and "api_error" in api_error:
        error_type = "infrastructure_error"
    elif timed_out:
        error_type = "timeout"
    elif stop_reason == "error":
        error_type = "agent_failure"
    elif not final_answer:
        error_type = "incomplete_stream"
    return {
        "path": "/api/lei-bit/chat",
        "method": "POST",
        "status": status,
        "content_type": content_type,
        "elapsed_seconds": elapsed,
        "events": events,
        "event_count": len(events),
        "event_types": dict(_counter(events)),
        "conv_id": conv_id,
        "turn_id": turn_id,
        "final_answer": redact(final_answer, token),
        "usage": usage,
        "stop_reason": stop_reason,
        "stop_detail": redact(stop_detail, token),
        "honest_failure": honest_failure,
        "api_error": redact(api_error, token),
        "decisions": decisions,
        "decision_actions": decision_actions,
        "tool_calls": tool_calls,
        "tool_names": tool_names,
        "contract_rejected": contract_rejected,
        "timed_out": timed_out,
        "error_type": error_type,
        "error": error,
        "request": {k: v for k, v in body.items() if k != "message"},
    }


def _counter(events: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for ev in events:
        key = str(ev.get("type") or "?")
        counts[key] = counts.get(key, 0) + 1
    return counts


def summarize(kind: str, result: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    record = {
        "run_id": f"PLT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "kind": kind,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "path": result["path"],
        "method": result["method"],
        "status": result["status"],
        "content_type": result["content_type"],
        "elapsed_seconds": result["elapsed_seconds"],
        "error": result.get("error"),
    }
    if "body_bytes" in result:
        record["body_bytes"] = result["body_bytes"]
        record["body_sha256"] = result["body_sha256"]
    if "event_count" in result:
        record["conv_id"] = result.get("conv_id")
        record["turn_id"] = result.get("turn_id")
        record["event_count"] = result["event_count"]
        record["event_types"] = result["event_types"]
        record["final_answer"] = result.get("final_answer")
        record["usage"] = result.get("usage")
        record["stop_reason"] = result.get("stop_reason")
        record["stop_detail"] = result.get("stop_detail")
        record["honest_failure"] = result.get("honest_failure")
        record["api_error"] = result.get("api_error")
        record["decisions"] = result.get("decisions")
        record["decision_actions"] = result.get("decision_actions")
        record["tool_calls"] = result.get("tool_calls")
        record["tool_names"] = result.get("tool_names")
        record["contract_rejected"] = result.get("contract_rejected")
        record["timed_out"] = result.get("timed_out")
        record["error_type"] = result.get("error_type")
        record["request"] = result.get("request")
    if extra:
        record.update(extra)
    return record


def append_evidence(record: Dict[str, Any]) -> None:
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    with EVIDENCE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_events(run_id: str, events: List[Dict[str, Any]], token: str) -> Path:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = EVENTS_DIR / f"{run_id}.json"
    safe = json.loads(redact(json.dumps(events, ensure_ascii=False), token))
    path.write_text(json.dumps(safe, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_cases(target: Path) -> List[Dict[str, Any]]:
    if target.is_dir():
        files = sorted(target.glob("*.json"))
        if not files:
            raise ValueError(f"no case files in {target}")
        return [json.loads(p.read_text(encoding="utf-8")) for p in files]
    return [json.loads(target.read_text(encoding="utf-8"))]


def judge_platform(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    oracle = case.get("oracle") or {}
    final = result.get("final_answer") or ""
    tool_names = result.get("tool_names") or []
    checks: Dict[str, bool] = {"answer_present": bool(final.strip())}
    if oracle.get("expect_final_answer_contains"):
        checks["contains"] = all(t in final for t in oracle["expect_final_answer_contains"])
    if oracle.get("must_not_contain"):
        checks["no_forbidden"] = not any(t in final for t in oracle["must_not_contain"])
    if oracle.get("refusal_any"):
        checks["refusal"] = any(t in final for t in oracle["refusal_any"])
    if oracle.get("forbidden_tools"):
        checks["no_forbidden_tool"] = not any(name in oracle["forbidden_tools"] for name in tool_names)
    if oracle.get("must_call_any"):
        checks["must_call_tool"] = any(name in oracle["must_call_any"] for name in tool_names)
    if oracle.get("expect_no_error"):
        checks["no_error"] = result.get("error_type") is None
    success = all(checks.values()) and result.get("error_type") is None
    return {"success": success, "checks": checks, "tool_names": tool_names}


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_case: Dict[str, Dict[str, Any]] = {}
    error_types: Dict[str, int] = {}
    for r in rows:
        agg = by_case.setdefault(r["case_id"], {"n": 0, "success": 0, "infrastructure_error": 0, "agent_failure": 0, "elapsed": []})
        agg["n"] += 1
        if r["success"]:
            agg["success"] += 1
        if r["error_type"] == "infrastructure_error":
            agg["infrastructure_error"] += 1
        elif r["error_type"] == "agent_failure":
            agg["agent_failure"] += 1
        error_types[r["error_type"] or "ok"] = error_types.get(r["error_type"] or "ok", 0) + 1
        agg["elapsed"].append(r["elapsed"])
    for agg in by_case.values():
        agg["success_rate"] = round(agg["success"] / agg["n"], 3) if agg["n"] else 0.0
        agg["avg_elapsed_seconds"] = round(sum(agg["elapsed"]) / len(agg["elapsed"]), 2) if agg["elapsed"] else 0.0
        del agg["elapsed"]
    total = len(rows)
    success = sum(1 for r in rows if r["success"])
    infra = sum(1 for r in rows if r["error_type"] == "infrastructure_error")
    agent = sum(1 for r in rows if r["error_type"] == "agent_failure")
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "runs": total,
            "success": success,
            "success_rate": round(success / total, 3) if total else 0.0,
            "infrastructure_error": infra,
            "agent_failure": agent,
            "error_type_distribution": error_types,
        },
        "by_case": by_case,
        "runs": rows,
    }


def run_suite(args, base: str, token: str, insecure: bool) -> int:
    cases = load_cases(Path(args.cases))
    rows: List[Dict[str, Any]] = []
    for case in cases:
        reps = args.repeat if args.repeat > 0 else int(case.get("repeat", 3))
        for rep in range(1, reps + 1):
            result = run_chat(
                base, token, case["message"], "", 1,
                args.task_name, args.temperature, args.run_timeout, insecure, args.decision,
            )
            judgement = judge_platform(case, result)
            record = summarize("suite_run", result, {
                "case_id": case["case_id"],
                "title": case.get("title", ""),
                "category": case.get("category", ""),
                "rep": rep,
                "judgement": judgement,
            })
            if result.get("events"):
                record["events_file"] = str(save_events(record["run_id"], result["events"], token))
            append_evidence(record)
            rows.append({
                "case_id": case["case_id"],
                "rep": rep,
                "run_id": record["run_id"],
                "success": judgement["success"],
                "error_type": result.get("error_type"),
                "elapsed": result["elapsed_seconds"],
                "answer": (result.get("final_answer") or "")[:120],
            })
            print(f"[{record['run_id']}] {case['case_id']} rep={rep} success={judgement['success']} "
                  f"error_type={result.get('error_type')} elapsed={result['elapsed_seconds']}s "
                  f"answer={(result.get('final_answer') or '')[:40]!r}")
    summary = aggregate(rows)
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nSUITE SUMMARY")
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))
    for cid, agg in summary["by_case"].items():
        print(f"{cid}: n={agg['n']} success={agg['success']} rate={agg['success_rate']} "
              f"infra={agg['infrastructure_error']} agent={agg['agent_failure']}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="LEUCS platform-level harness")
    parser.add_argument("action", choices=["health", "list", "conversation", "events", "feed", "run", "suite"])
    parser.add_argument("conv_id", nargs="?", help="conversation id (conversation/events)")
    parser.add_argument("--cases", default="", help="path to a case JSON or a directory (suite)")
    parser.add_argument("--repeat", type=int, default=0, help="override per-case repeat count (suite)")
    parser.add_argument("--text", default="", help="message content for the run action")
    parser.add_argument("--conversation-id", default="", help="existing conversation for run (default: new)")
    parser.add_argument("--turn-index", type=int, default=1)
    parser.add_argument("--task-name", default="leucs_main")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--after", type=int, default=0, help="cursor for feed")
    parser.add_argument("--decision", choices=["none", "deny", "approve"], default="none",
                        help="auto-answer tool-permission decisions during a run")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--run-timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--verify-tls", action="store_true")
    args = parser.parse_args(argv)

    token = os.environ.get("LEUCS_PLATFORM_TOKEN", "")
    base = os.environ.get("LEUCS_PLATFORM_BASE", DEFAULT_BASE)
    if not token:
        print("ERROR: set LEUCS_PLATFORM_TOKEN first.", file=sys.stderr)
        return 2
    insecure = not args.verify_tls

    if args.action == "suite":
        if not args.cases:
            print("ERROR: --cases required for suite", file=sys.stderr)
            return 2
        return run_suite(args, base, token, insecure)

    if args.action == "health":
        result = retry(request, base, "/api/leucs/health", token, timeout=args.timeout, insecure=insecure, retries=args.retries)
        record = summarize("health", result)
    elif args.action == "list":
        result = retry(request, base, "/api/leucs/conversations", token, timeout=args.timeout, insecure=insecure, retries=args.retries)
        record = summarize("list", result)
    elif args.action == "feed":
        result = retry(request, base, f"/api/lei-bit/accounts/feed?after={args.after}", token, timeout=args.timeout, insecure=insecure, retries=args.retries)
        record = summarize("feed", result, {"after": args.after})
    elif args.action == "conversation":
        if not args.conv_id:
            print("ERROR: conv_id required", file=sys.stderr)
            return 2
        result = retry(request, base, f"/api/leucs/conversation/{args.conv_id}", token, timeout=args.timeout, insecure=insecure, retries=args.retries)
        record = summarize("conversation", result)
    elif args.action == "events":
        if not args.conv_id:
            print("ERROR: conv_id required", file=sys.stderr)
            return 2
        result = retry(request, base, f"/api/leucs/conversation/{args.conv_id}/events", token, timeout=args.timeout, insecure=insecure, retries=args.retries)
        record = summarize("events", result)
    else:  # run
        if not args.text.strip():
            print("ERROR: --text required", file=sys.stderr)
            return 2
        result = run_chat(
            base, token, args.text, args.conversation_id, args.turn_index,
            args.task_name, args.temperature, args.run_timeout, insecure, args.decision,
        )
        record = summarize("run", result)

    if args.action == "run" and result.get("events"):
        record["events_file"] = str(save_events(record["run_id"], result["events"], token))

    append_evidence(record)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    if result.get("error"):
        print(f"\nERROR: {result['error']}", file=sys.stderr)
        return 1
    if args.action != "run":
        print(f"\nBODY PREVIEW:\n{result['text'][:600]}")
    return 0


def retry(fn, *args, retries: int = 3, **kwargs) -> Dict[str, Any]:
    last: Dict[str, Any] = {}
    for attempt in range(1, max(1, retries) + 1):
        last = fn(*args, **kwargs)
        if last.get("status") and not last.get("error"):
            return last
        if attempt < retries:
            time.sleep(2 * attempt)
    return last


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
