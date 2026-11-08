#!/usr/bin/env python
"""Capture the LEUCS platform's *runtime configuration* as comparable evidence.

Why this exists
---------------
A large part of what we call "platform behaviour" is actually **configuration**:
which model is bound, how large the output budget is, which approval level is
active, how many MCP tools are registered, whether a browser mount is attached.

If those change, previously recorded verdicts stop being comparable. This
script snapshots them so a regression can be attributed to "config changed"
rather than "the model got dumber".

Everything captured here is READ-ONLY.

Usage:
    python harness_srs/platform_metadata.py
    python harness_srs/platform_metadata.py --out evidence/platform_metadata.json
    python harness_srs/platform_metadata.py --compare evidence/platform_metadata.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence" / "platform_metadata.json"
DEFAULT_BASE = "https://123.57.180.120"

READ_ONLY_ENDPOINTS = [
    ("health", "/api/leucs/health"),
    ("status", "/api/leucs/status"),
    ("context_status", "/api/leucs/context-status"),
    ("mount_status", "/api/leucs/mount/status"),
    ("mount_policy", "/api/leucs/mount/policy"),
    ("approval_level", "/api/leucs/config/approval-level"),
    ("pool_status", "/api/lei-bit/pool_status"),
    ("model_info", "/api/leucs/model_info"),
    ("capability_directory", "/api/leucs/capability_directory"),
    ("mcp_shelf", "/api/leucs_mcp/shelf"),
    ("llm_list", "/api/llm/list"),
]


def _ctx(insecure: bool = True):
    return ssl._create_unverified_context() if insecure else ssl.create_default_context()


def fetch(base: str, token: str, path: str, insecure: bool, timeout: float = 15.0) -> Dict[str, Any]:
    req = urllib.request.Request(
        base.rstrip("/") + path,
        headers={"authorization": "Bearer " + token, "accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx(insecure)) as resp:
            raw = resp.read()
            return {"status": resp.status, "json": json.loads(raw) if raw else None}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "json": None}
    except Exception as exc:  # noqa: BLE001
        return {"status": None, "json": None, "error": f"{type(exc).__name__}: {exc}"}


def summarize(payloads: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce raw payloads to the fields that actually decide behaviour."""
    out: Dict[str, Any] = {}

    health = payloads.get("health", {}) or {}
    out["build_id"] = (health.get("json") or {}).get("build_id")
    out["agent_ready"] = (health.get("json") or {}).get("agent_ready")
    out["mcp_tools"] = (health.get("json") or {}).get("mcp_tools")

    llm = (payloads.get("llm_list", {}) or {}).get("json") or {}
    runtime_name = llm.get("current_runtime")
    out["runtime_api"] = runtime_name
    cfg = llm.get(runtime_name) or {}
    out["model"] = cfg.get("model")
    out["base_url"] = cfg.get("base_url")
    out["think_enabled"] = cfg.get("think_enabled")
    out["max_output"] = cfg.get("max_output")
    out["max_thinking_tokens"] = cfg.get("max_thinking_tokens")
    out["supports_thinking"] = cfg.get("supports_thinking")
    out["tool_exec_mode"] = cfg.get("tool_exec_mode")

    model_info = (payloads.get("model_info", {}) or {}).get("json") or {}
    out["runtime_max_output"] = model_info.get("runtime_max_output")
    out["theoretical_max_output"] = model_info.get("theoretical_max_output")
    out["context_length"] = model_info.get("context_length")
    out["default_temp"] = model_info.get("default_temp")

    ctx_status = (payloads.get("context_status", {}) or {}).get("json") or {}
    out["context_temperature"] = ctx_status.get("temperature")
    out["context_timeout"] = ctx_status.get("timeout")
    out["context_retry_count"] = ctx_status.get("retry_count")
    out["compact_trigger"] = ctx_status.get("compact_trigger")

    approval = (payloads.get("approval_level", {}) or {}).get("json") or {}
    out["approval_level"] = approval.get("level")
    out["approval_levels_available"] = sorted((approval.get("levels") or {}).keys())

    mount = (payloads.get("mount_status", {}) or {}).get("json") or {}
    out["mount_online"] = mount.get("online")
    out["mount_count"] = len(mount.get("mounts") or [])
    mounts = mount.get("mounts") or []
    if mounts:
        caps = mounts[0].get("caps") or {}
        out["mount_executor_kind"] = mounts[0].get("executor_kind")
        out["mount_tool_count"] = len(caps.get("tools") or [])
        out["mount_has_execution_tool"] = any(
            t in (caps.get("tools") or []) for t in
            ("run_command", "exec", "python_exec", "run_python", "shell")
        )

    policy = (payloads.get("mount_policy", {}) or {}).get("json") or {}
    out["mount_policy"] = policy.get("policy") or {}

    pool = (payloads.get("pool_status", {}) or {}).get("json") or {}
    out["pool_capacity_per_minute"] = pool.get("capacity_per_minute")
    out["pool_badge"] = pool.get("badge")
    out["pool_queued"] = pool.get("queued")

    shelf = (payloads.get("mcp_shelf", {}) or {}).get("json") or {}
    out["shelf_total_tools"] = shelf.get("total")

    caps = (payloads.get("capability_directory", {}) or {}).get("json") or {}
    out["capability_count"] = len(caps.get("capabilities") or [])
    out["capability_categories"] = sorted({c.get("category") for c in (caps.get("capabilities") or []) if c.get("category")})

    return out


def fingerprint(summary: Dict[str, Any]) -> str:
    """Stable hash of the fields that decide behaviour (ignores volatile ones)."""
    stable = {k: v for k, v in summary.items() if k not in ("mount_count", "mount_online", "pool_badge", "pool_queued")}
    blob = json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def compare(current: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    changed: List[Dict[str, Any]] = []
    for key in sorted(set(current) | set(baseline)):
        before = baseline.get(key)
        after = current.get(key)
        if before != after:
            changed.append({"field": key, "before": before, "after": after})
    return {
        "baseline_captured_at": baseline.get("captured_at"),
        "baseline_fingerprint": baseline.get("fingerprint"),
        "current_fingerprint": current.get("fingerprint"),
        "config_changed": bool(changed),
        "changed_fields": changed,
    }


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Snapshot LEUCS runtime configuration")
    parser.add_argument("--base", default=os.environ.get("LEUCS_PLATFORM_BASE", DEFAULT_BASE))
    parser.add_argument("--out", default=str(EVIDENCE))
    parser.add_argument("--compare", default="", help="compare against an existing snapshot")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--verify-tls", action="store_true")
    args = parser.parse_args(argv)

    token = os.environ.get("LEUCS_PLATFORM_TOKEN", "")
    if not token:
        print("ERROR: set LEUCS_PLATFORM_TOKEN first.", file=sys.stderr)
        return 2

    payloads: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for name, path in READ_ONLY_ENDPOINTS:
        result = fetch(args.base, token, path, not args.verify_tls, args.timeout)
        payloads[name] = result
        if result.get("error"):
            errors[name] = result["error"]
        elif result.get("status") != 200:
            errors[name] = f"HTTP {result.get('status')}"

    summary = summarize(payloads)
    snapshot = {
        "schema_version": "1.0",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "base": args.base,
        "fingerprint": fingerprint(summary),
        "summary": summary,
        "endpoint_errors": errors,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors:
        print("\nendpoint errors:", json.dumps(errors, ensure_ascii=False), file=sys.stderr)
    print(f"\nwrote {out_path}")

    if args.compare:
        baseline_path = Path(args.compare)
        if baseline_path.is_file():
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            result = compare(snapshot, baseline)
            print("\n=== 与基线比较 ===")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            (out_path.parent / "platform_metadata_diff.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            print(f"\n基线不存在：{baseline_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
