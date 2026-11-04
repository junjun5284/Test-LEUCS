#!/usr/bin/env python
"""Platform health probe: cheap, read-only checks of the LEUCS platform.

Purpose: detect platform regressions early and cheaply, so that a full suite run
is not the first place where an outage shows up.

Design:
- Only read-only endpoints; never starts an Agent run.
- Each probe has a fixed budget (timeout) and a fixed expectation.
- Results are appended to evidence/platform_probe.jsonl and can be diffed against
  a stored baseline (evidence/platform_probe_baseline.json).

Usage:
    python harness_srs/platform_probe.py --base https://123.57.180.120
    python harness_srs/platform_probe.py --base https://... --save-baseline
    python harness_srs/platform_probe.py --base https://... --compare-baseline
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence" / "platform_probe.jsonl"
BASELINE = ROOT / "evidence" / "platform_probe_baseline.json"

# (probe_id, method, path, expect_status, description)
PROBES: List[Tuple[str, str, str, Any, str]] = [
    ("P01-health", "GET", "/api/leucs/health", 200, "平台健康检查（agent_ready / build_id / mcp_tools）"),
    ("P02-conversations", "GET", "/api/leucs/conversations", 200, "会话列表可读"),
    ("P03-leucs-capability", "GET", "/api/leucs/capability_directory", 200, "能力目录可读"),
    ("P04-mcp-shelf", "GET", "/api/leucs_mcp/shelf", 200, "MCP 工具货架可读"),
    ("P05-mount-status", "GET", "/api/leucs/mount/status", 200, "挂载状态可读"),
    ("P06-approval-level", "GET", "/api/leucs/config/approval-level", 200, "审批级别配置可读"),
    ("P07-pool-status", "GET", "/api/lei-bit/pool_status", 200, "账号池状态可读"),
    ("P08-status", "GET", "/api/leucs/status", 200, "平台运行状态可读"),
]


def build_ctx(insecure: bool = True):
    return ssl._create_unverified_context() if insecure else ssl.create_default_context()


def probe_once(
    base: str,
    token: str,
    method: str,
    path: str,
    timeout: float,
    insecure: bool,
) -> Dict[str, Any]:
    url = base.rstrip("/") + path
    headers = {"authorization": "Bearer " + token, "accept": "application/json"}
    req = urllib.request.Request(url, headers=headers, method=method)
    started = time.time()
    status: Any = None
    body = b""
    error = None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=build_ctx(insecure)) as resp:
            status = resp.status
            body = resp.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
        error = f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    elapsed = round(time.time() - started, 2)
    text = body.decode("utf-8", "replace")
    if token:
        text = text.replace(token, "[token redacted]")
    return {
        "status": status,
        "elapsed_seconds": elapsed,
        "body_bytes": len(body),
        "error": error,
        "text_head": text[:200],
    }


def run_probes(
    base: str,
    token: str,
    timeout: float,
    insecure: bool,
    retries: int = 2,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for pid, method, path, expect, desc in PROBES:
        result: Dict[str, Any] = {}
        for attempt in range(1, max(1, retries) + 1):
            result = probe_once(base, token, method, path, timeout, insecure)
            if result.get("status") and not result.get("error"):
                break
            if attempt < retries:
                time.sleep(1.5 * attempt)
        ok = result.get("status") == expect
        records.append({
            "probe_id": pid,
            "method": method,
            "path": path,
            "description": desc,
            "expect_status": expect,
            "status": result.get("status"),
            "elapsed_seconds": result.get("elapsed_seconds"),
            "error": result.get("error"),
            "ok": ok,
            "verdict": "pass" if ok else "fail",
        })
    return records


def summarize(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    failed = [r for r in records if not r["ok"]]
    return {
        "probes": len(records),
        "passed": len(records) - len(failed),
        "failed": len(failed),
        "verdict": "healthy" if not failed else "degraded",
        "failed_ids": [r["probe_id"] for r in failed],
    }


def append_evidence(records: List[Dict[str, Any]], base: str) -> None:
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    with EVIDENCE.open("a", encoding="utf-8") as handle:
        for rec in records:
            handle.write(json.dumps({"timestamp": stamp, "base": base, **rec}, ensure_ascii=False) + "\n")


def save_baseline(records: List[Dict[str, Any]], base: str) -> None:
    payload = {
        "schema_version": "1.0",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "base": base,
        "summary": summarize(records),
        "probes": [
            {"probe_id": r["probe_id"], "path": r["path"], "expect_status": r["expect_status"],
             "status": r["status"], "verdict": r["verdict"]}
            for r in records
        ],
    }
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def compare_baseline(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not BASELINE.is_file():
        return {"comparison": "no_baseline", "note": f"尚未保存基线：{BASELINE.name}"}
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    base_map = {p["probe_id"]: p for p in base.get("probes", [])}
    drift: List[Dict[str, Any]] = []
    for rec in records:
        prev = base_map.get(rec["probe_id"])
        if prev is None:
            drift.append({"probe_id": rec["probe_id"], "kind": "new_probe"})
        elif prev.get("verdict") != rec["verdict"]:
            drift.append({
                "probe_id": rec["probe_id"],
                "kind": "verdict_changed",
                "baseline": prev.get("verdict"),
                "current": rec["verdict"],
                "baseline_status": prev.get("status"),
                "current_status": rec.get("status"),
            })
    for pid in base_map:
        if pid not in {r["probe_id"] for r in records}:
            drift.append({"probe_id": pid, "kind": "probe_missing_now"})
    return {
        "comparison": "ok" if not drift else "drift",
        "baseline_saved_at": base.get("saved_at"),
        "drift": drift,
    }


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="LEUCS platform health probe")
    parser.add_argument("--base", default=os.environ.get("LEUCS_PLATFORM_BASE", ""))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--compare-baseline", action="store_true")
    parser.add_argument("--verify-tls", action="store_true")
    args = parser.parse_args(argv)

    base = args.base
    token = os.environ.get("LEUCS_PLATFORM_TOKEN", "")
    if not base:
        print("ERROR: set LEUCS_PLATFORM_BASE or pass --base", file=sys.stderr)
        return 2
    if not token:
        print("ERROR: set LEUCS_PLATFORM_TOKEN first.", file=sys.stderr)
        return 2

    records = run_probes(base, token, args.timeout, not args.verify_tls, args.retries)
    append_evidence(records, base)
    summary = summarize(records)
    result: Dict[str, Any] = {
        "run_id": f"PRB-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base": base,
        "summary": summary,
        "probes": records,
    }
    if args.compare_baseline:
        result["baseline_comparison"] = compare_baseline(records)
    if args.save_baseline:
        save_baseline(records, base)
        result["baseline_saved"] = True

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if summary["verdict"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
