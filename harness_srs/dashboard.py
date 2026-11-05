#!/usr/bin/env python
"""Web dashboard for the Harness: browse runs, inspect events, watch live progress.

Standard library only (http.server) so it starts with no extra dependencies.

    python harness_srs/dashboard.py --port 8801
    python harness_srs/dashboard.py --port 8801 --adapter leucs --live

Endpoints
---------
GET  /                      dashboard HTML (single page, no build step)
GET  /api/adapters           registered adapters
GET  /api/runs               run records (filters: adapter, case_id, kind)
GET  /api/runs/<run_id>      one run record
GET  /api/events/<run_id>    full SSE/agent event trace for a run
GET  /api/summary            aggregated statistics
GET  /api/cases              case definitions of an adapter
GET  /api/live               Server-Sent Events stream of new runs
POST /api/run                trigger a suite run (body: {adapter, cases?, repeat?})
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys_path = str(ROOT)
if sys_path not in os.sys.path:
    os.sys.path.insert(0, sys_path)

from adapters import LeucsAdapter  # noqa: E402  (registers the "leucs" adapter)
from core import EvidenceStore, aggregate, get_adapter, is_success, list_adapters, run_suite  # noqa: E402

# Live stream subscribers
_SUBSCRIBERS: List["queue.Queue[dict]"] = []
_LOCK = threading.Lock()


def publish(event: Dict[str, Any]) -> None:
    with _LOCK:
        for q in list(_SUBSCRIBERS):
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


class Dashboard:
    """Holds the evidence stores and adapter factories the UI talks to."""

    def __init__(self, evidence_root: Path):
        self.evidence_root = Path(evidence_root)
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        self.adapters: Dict[str, Dict[str, Any]] = {
            "leucs": {
                "name": "leucs",
                "runs_file": self.evidence_root / "platform_runs.jsonl",
                "events_dir": self.evidence_root / "platform_events",
                "options": {
                    "base": os.environ.get("LEUCS_PLATFORM_BASE", "https://123.57.180.120"),
                    "token": os.environ.get("LEUCS_PLATFORM_TOKEN", ""),
                    "cases_dir": str(ROOT / "platform_cases"),
                    "evidence_dir": str(self.evidence_root),
                },
            },
        }
        self.lock = threading.Lock()
        self.running: Dict[str, Any] = {"state": "idle", "adapter": None, "started": None, "done": 0, "total": 0}

    # ------------------------------------------------------------------ #

    def store(self, adapter: str) -> EvidenceStore:
        spec = self.adapters.get(adapter) or self.adapters["leucs"]
        return EvidenceStore(spec["runs_file"])

    def runs(self, adapter: str, kind: Optional[str] = None, case_id: Optional[str] = None,
             limit: int = 500) -> List[Dict[str, Any]]:
        rows = self.store(adapter).runs(kinds=[kind] if kind else None)
        if case_id:
            rows = [r for r in rows if r.get("case_id") == case_id]
        rows = list(reversed(rows))
        return rows[:limit]

    def run_detail(self, adapter: str, run_id: str) -> Optional[Dict[str, Any]]:
        for r in self.store(adapter).runs():
            if r.get("run_id") == run_id:
                return r
        return None

    def events(self, adapter: str, run_id: str) -> List[Dict[str, Any]]:
        spec = self.adapters.get(adapter) or self.adapters["leucs"]
        path = spec["events_dir"] / f"{run_id}.json"
        if not path.is_file():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def summary(self, adapter: str) -> Dict[str, Any]:
        rows = self.store(adapter).runs(kinds=["suite_run", "run"])
        result = aggregate(rows)
        by_kind: Dict[str, int] = {}
        for r in rows:
            by_kind[r.get("kind") or "?"] = by_kind.get(r.get("kind") or "?", 0) + 1
        result["totals"]["by_kind"] = by_kind
        result["totals"]["evidence_files"] = len(list((self.adapters.get(adapter) or self.adapters["leucs"])["events_dir"].glob("*.json"))) \
            if (self.adapters.get(adapter) or self.adapters["leucs"])["events_dir"].is_dir() else 0
        return result

    def cases(self, adapter: str) -> List[Dict[str, Any]]:
        spec = self.adapters.get(adapter) or self.adapters["leucs"]
        try:
            instance = get_adapter(adapter, **{k: v for k, v in spec["options"].items()})
        except Exception:
            return []
        return instance.list_cases()

    def trigger(self, adapter: str, case_ids: Optional[List[str]] = None, repeat: int = 0) -> Dict[str, Any]:
        with self.lock:
            if self.running["state"] == "running":
                return {"started": False, "reason": "a run is already in progress"}
            spec = self.adapters.get(adapter) or self.adapters["leucs"]
            self.running = {"state": "running", "adapter": adapter,
                            "started": datetime.now(timezone.utc).isoformat(),
                            "done": 0, "total": 0}
        thread = threading.Thread(target=self._run_worker, args=(adapter, case_ids, repeat), daemon=True)
        thread.start()
        return {"started": True, "adapter": adapter}

    def _run_worker(self, adapter: str, case_ids: Optional[List[str]], repeat: int) -> None:
        spec = self.adapters.get(adapter) or self.adapters["leucs"]
        try:
            instance = get_adapter(adapter, **spec["options"])
            cases = instance.list_cases()
            if case_ids:
                wanted = set(case_ids)
                cases = [c for c in cases if c.get("case_id") in wanted]
            self.running["total"] = len(cases)
            publish({"type": "suite_start", "adapter": adapter, "cases": len(cases)})
            store = self.store(adapter)

            def on_event(record: Dict[str, Any]) -> None:
                with self.lock:
                    self.running["done"] = self.running.get("done", 0) + 1
                publish({"type": "run", "record": record})

            run_suite(instance, store, cases, repeat_override=repeat, on_event=on_event)
            publish({"type": "suite_done", "adapter": adapter})
        except Exception as exc:  # noqa: BLE001
            publish({"type": "error", "message": f"{type(exc).__name__}: {exc}",
                     "trace": traceback.format_exc()[-1500:]})
        finally:
            with self.lock:
                self.running["state"] = "idle"


DASH = None  # type: ignore


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Harness 控制台</title>
<style>
  :root{
    --bg:#0e1116; --panel:#161b22; --panel2:#1c2330; --line:#2a3441;
    --fg:#e6edf3; --dim:#8b949e; --ok:#3fb950; --bad:#f85149;
    --warn:#d29922; --info:#58a6ff; --accent:#a371f7;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:14px/1.55 -apple-system,"Segoe UI",Microsoft YaHei,sans-serif}
  header{display:flex;align-items:center;gap:16px;padding:12px 20px;
         background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
  h1{font-size:16px;margin:0;font-weight:600;letter-spacing:.3px}
  h1 span{color:var(--accent)}
  .tag{font-size:11px;color:var(--dim);border:1px solid var(--line);
       border-radius:10px;padding:1px 8px}
  .spacer{flex:1}
  button{background:var(--panel2);color:var(--fg);border:1px solid var(--line);
         border-radius:6px;padding:5px 12px;cursor:pointer;font-size:13px}
  button:hover{border-color:var(--info);color:var(--info)}
  button.primary{background:#1f6feb;border-color:#1f6feb;color:#fff}
  select,input{background:var(--panel2);color:var(--fg);border:1px solid var(--line);
               border-radius:6px;padding:5px 9px;font-size:13px}
  main{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:14px 20px 40px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  .card h2{margin:0;padding:9px 14px;font-size:13px;font-weight:600;color:var(--fg);
           border-bottom:1px solid var(--line);background:var(--panel2);
           display:flex;align-items:center;gap:8px}
  .card h2 .n{color:var(--dim);font-weight:400;font-size:11px}
  .card .body{padding:10px 14px;max-height:520px;overflow:auto}
  .full{grid-column:1/-1}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th{text-align:left;color:var(--dim);font-weight:500;padding:6px 8px;
     border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel)}
  td{padding:5px 8px;border-bottom:1px solid #20262e;vertical-align:top}
  tr.click:hover{background:var(--panel2);cursor:pointer}
  tr.sel{background:#1f3a5f}
  .pill{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;
        border:1px solid var(--line);white-space:nowrap}
  .p-ok{color:var(--ok);border-color:#1f6f33;background:#0f2b16}
  .p-bad{color:var(--bad);border-color:#7d2b28;background:#2d1214}
  .p-warn{color:var(--warn);border-color:#6b5418;background:#2b2410}
  .p-info{color:var(--info);border-color:#1f4a7a;background:#0f2033}
  .p-dim{color:var(--dim)}
  .mono{font-family:ui-monospace,Consolas,monospace;font-size:11.5px}
  .muted{color:var(--dim)}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;padding:12px 14px}
  .kpi{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:9px 11px}
  .kpi .v{font-size:21px;font-weight:600}
  .kpi .l{color:var(--dim);font-size:11px;margin-top:2px}
  pre{margin:0;white-space:pre-wrap;word-break:break-word;font-size:11.5px;
      font-family:ui-monospace,Consolas,monospace;color:#c9d1d9}
  .ev{padding:5px 8px;border-bottom:1px solid #20262e;display:grid;
      grid-template-columns:150px 1fr;gap:8px}
  .ev .t{color:var(--accent);font-family:ui-monospace,Consolas,monospace;font-size:11px}
  .ev .c{white-space:pre-wrap;word-break:break-word;color:#b8c4ce;font-size:11.5px}
  .bar{display:inline-block;height:7px;border-radius:4px;background:var(--info);vertical-align:middle}
  .bar.ok{background:var(--ok)} .bar.bad{background:var(--bad)}
  .live{width:8px;height:8px;border-radius:50%;background:var(--dim);display:inline-block}
  .live.on{background:var(--ok);box-shadow:0 0 6px var(--ok)}
  .flt{display:flex;gap:8px;align-items:center;padding:9px 14px;border-bottom:1px solid var(--line);flex-wrap:wrap}
</style>
</head>
<body>
<header>
  <h1>Test <span>Harness</span> 控制台</h1>
  <select id="adapter"></select>
  <button id="refresh">刷新</button>
  <button id="run" class="primary">运行套件</button>
  <span class="live" id="live"></span>
  <span class="tag" id="stat">idle</span>
  <div class="spacer"></div>
  <span class="tag" id="clock"></span>
</header>

<main>
  <section class="card full">
    <h2>总览</h2>
    <div class="kpis" id="kpis"></div>
  </section>

  <section class="card">
    <h2>运行记录 <span class="n" id="runCount"></span></h2>
    <div class="flt">
      <select id="fCase"><option value="">全部用例</option></select>
      <select id="fKind">
        <option value="">全部类型</option>
        <option value="suite_run">suite_run</option>
        <option value="run">run</option>
      </select>
      <select id="fVerdict">
        <option value="">全部判定</option>
        <option value="pass">成功</option>
        <option value="fail">失败</option>
      </select>
    </div>
    <div class="body" style="max-height:460px">
      <table><thead><tr>
        <th>run_id</th><th>用例</th><th>判定</th><th>失败类型</th><th>耗时</th><th>工具数</th>
      </tr></thead><tbody id="rows"></tbody></table>
    </div>
  </section>

  <section class="card">
    <h2>用例统计</h2>
    <div class="body" style="max-height:460px">
      <table><thead><tr>
        <th>用例</th><th>n</th><th>成功</th><th>成功率</th><th>平均耗时</th>
      </tr></thead><tbody id="caseRows"></tbody></table>
    </div>
  </section>

  <section class="card full">
    <h2>运行详情 <span class="n" id="detailId">未选择</span></h2>
    <div class="body" style="max-height:560px">
      <div id="detail"></div>
    </div>
  </section>
</main>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s??"").replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let ADAPTER = null, selected = null, allRuns = [];

async function api(path, opts){
  const r = await fetch(path, opts);
  if(!r.ok) throw new Error("HTTP "+r.status+" "+await r.text());
  return r.json();
}

function verdictPill(rec){
  const ok = rec.judgement ? rec.judgement.success : rec.success;
  const et = rec.error_type;
  if(et === "skipped") return `<span class="pill p-warn">跳过</span>`;
  if(et) return `<span class="pill p-bad">${esc(et)}</span>`;
  return ok ? `<span class="pill p-ok">通过</span>` : `<span class="pill p-bad">失败</span>`;
}
const isOk = rec => (rec.judgement ? rec.judgement.success : rec.success) === true;

async function initAdapters(){
  const list = await api("/api/adapters");
  $("#adapter").innerHTML = list.map(a=>`<option value="${esc(a.name)}">${esc(a.name)} — ${esc(a.description)}</option>`).join("");
  ADAPTER = list[0]?.name;
  if(ADAPTER) $("#adapter").value = ADAPTER;
}

async function loadSummary(){
  const s = await api("/api/summary?adapter="+ADAPTER);
  const t = s.totals;
  const dist = t.error_type_distribution||{};
  $("#kpis").innerHTML = `
    <div class="kpi"><div class="v">${t.runs}</div><div class="l">运行总数</div></div>
    <div class="kpi"><div class="v" style="color:var(--ok)">${t.success}</div><div class="l">成功</div></div>
    <div class="kpi"><div class="v" style="color:var(--info)">${(t.success_rate*100).toFixed(1)}%</div><div class="l">成功率</div></div>
    <div class="kpi"><div class="v">${t.evidence_files||0}</div><div class="l">事件证据文件</div></div>
    <div class="kpi"><div class="v" style="color:var(--bad)">${(dist.infrastructure_error||0)}</div><div class="l">基础设施错误</div></div>
    <div class="kpi"><div class="v" style="color:var(--warn)">${(dist.timeout||0)+(dist.incomplete_stream||0)}</div><div class="l">超时/中断</div></div>`;
}

async function loadCases(){
  const cases = await api("/api/cases?adapter="+ADAPTER);
  const sel = $("#fCase");
  const cur = sel.value;
  sel.innerHTML = `<option value="">全部用例</option>` +
    cases.map(c=>`<option value="${esc(c.case_id)}">${esc(c.case_id)} · ${esc(c.title||"")}</option>`).join("");
  sel.value = cur;
}

async function loadRuns(){
  const q = new URLSearchParams({adapter:ADAPTER, limit:"400"});
  if($("#fCase").value) q.set("case_id", $("#fCase").value);
  if($("#fKind").value) q.set("kind", $("#fKind").value);
  allRuns = await api("/api/runs?"+q);
  if($("#fVerdict").value==="pass") allRuns = allRuns.filter(isOk);
  if($("#fVerdict").value==="fail") allRuns = allRuns.filter(r=>!isOk(r));
  $("#runCount").textContent = allRuns.length + " 条";
  $("#rows").innerHTML = allRuns.map(r=>{
    const ok = isOk(r);
    return `<tr class="click ${selected===r.run_id?'sel':''}" data-id="${esc(r.run_id)}">
      <td class="mono">${esc(r.run_id)}</td>
      <td>${esc(r.case_id||r.kind)}</td>
      <td>${ok?'<span class="pill p-ok">通过</span>':'<span class="pill p-bad">失败</span>'}</td>
      <td>${r.error_type?`<span class="pill p-warn">${esc(r.error_type)}</span>`:'<span class="muted">-</span>'}</td>
      <td>${r.elapsed_seconds??'-'}s</td>
      <td>${(r.tool_names||[]).length}</td></tr>`;
  }).join("");
  document.querySelectorAll("#rows tr").forEach(tr=>tr.onclick=()=>showDetail(tr.dataset.id));
}

async function loadCaseStats(){
  const s = await api("/api/summary?adapter="+ADAPTER);
  $("#caseRows").innerHTML = Object.entries(s.by_case).map(([cid,a])=>`
    <tr><td class="mono">${esc(cid)}</td><td>${a.n}</td><td>${a.success}</td>
    <td><span class="bar ${a.success_rate>=0.99?'ok':(a.success_rate>=0.5?'':'bad')}" style="width:${Math.round(a.success_rate*70)}px"></span>
        ${(a.success_rate*100).toFixed(0)}%</td>
    <td>${a.avg_elapsed_seconds}s</td></tr>`).join("");
}

async function showDetail(id){
  selected = id;
  $("#detailId").textContent = id;
  const rec = await api("/api/run?adapter="+ADAPTER+"&run_id="+encodeURIComponent(id));
  if(!rec){ $("#detail").innerHTML = `<div class="muted">未找到该记录</div>`; return; }
  const j = rec.judgement||{};
  const checks = Object.entries(j.checks||{}).map(([k,v])=>
    `<span class="pill ${v?'p-ok':'p-bad'}">${esc(k)}=${v}</span>`).join(" ");
  const tools = (rec.tool_names||[]).map(t=>`<span class="pill p-info">${esc(t)}</span>`).join(" ");
  let html = `
    <div class="flt" style="border:0;padding:0 0 10px">
      ${checks} ${tools}
    </div>
    <div class="muted" style="margin-bottom:6px">最终回答</div>
    <pre>${esc(rec.final_answer||"(空)")}</pre>`;
  if(rec.error || rec.stop_detail){
    html += `<div class="muted" style="margin:10px 0 6px">错误信息</div>
             <pre style="color:var(--bad)">${esc(rec.stop_detail||rec.error||"")}</pre>`;
  }
  if(rec.usage && Object.keys(rec.usage).length){
    html += `<div class="muted" style="margin:10px 0 6px">用量</div>
             <pre>${esc(JSON.stringify(rec.usage,null,2))}</pre>`;
  }
  if(rec.discovery_detail){
    html += `<div class="muted" style="margin:10px 0 6px">工具发现分析</div>
             <pre>${esc(JSON.stringify(rec.discovery_detail,null,2))}</pre>`;
  }
  $("#detail").innerHTML = html;
  const evs = await api("/api/events?adapter="+ADAPTER+"&run_id="+encodeURIComponent(id));
  if(evs.length){
    const counts = {};
    evs.forEach(e=>counts[e.type||"?"]=(counts[e.type||"?"]||0)+1);
    html += `<div class="muted" style="margin:12px 0 6px">事件轨迹（${evs.length} 条）
      · ${Object.entries(counts).map(([k,v])=>`${esc(k)}×${v}`).join(" ")}</div>
      <div>${evs.map(e=>`<div class="ev"><div class="t">${esc(e.type||"?")}</div>
        <div class="c">${esc(String(e.content??e.message??e.tool_name??"").slice(0,600))}</div></div>`).join("")}</div>`;
    $("#detail").innerHTML = html;
  }
}

function connectLive(){
  const es = new EventSource("/api/live");
  es.onopen = ()=>{ $("#live").classList.add("on"); };
  es.onerror = ()=>{ $("#live").classList.remove("on"); };
  es.onmessage = ev=>{
    const d = JSON.parse(ev.data);
    if(d.type==="suite_start"){ $("#stat").textContent = "运行中 "+d.cases+" 用例"; }
    if(d.type==="suite_done"){ $("#stat").textContent = "完成"; refreshAll(); }
    if(d.type==="run"){
      $("#stat").textContent = "运行中";
      const r = d.record;
      $("#rows").insertAdjacentHTML("afterbegin",
        `<tr class="click" data-id="${esc(r.run_id)}">
         <td class="mono">${esc(r.run_id)}</td><td>${esc(r.case_id||r.kind)}</td>
         <td>${isOk(r)?'<span class="pill p-ok">通过</span>':'<span class="pill p-bad">失败</span>'}</td>
         <td>${r.error_type?`<span class="pill p-warn">${esc(r.error_type)}</span>`:'<span class="muted">-</span>'}</td>
         <td>${r.elapsed_seconds??'-'}s</td><td>${(r.tool_names||[]).length}</td></tr>`);
      document.querySelectorAll("#rows tr").forEach(tr=>tr.onclick=()=>showDetail(tr.dataset.id));
    }
  };
}

async function refreshAll(){
  await loadSummary(); await loadCases(); await loadRuns(); await loadCaseStats();
}

$("#adapter").onchange = async e=>{ ADAPTER = e.target.value; await refreshAll(); };
$("#refresh").onclick = refreshAll;
$("#fCase").onchange = loadRuns;
$("#fKind").onchange = loadRuns;
$("#fVerdict").onchange = loadRuns;
$("#run").onclick = async ()=>{
  if(!confirm("在平台目标上运行套件？这会产生真实的模型调用与平台会话。")) return;
  const r = await api("/api/run", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({adapter:ADAPTER, repeat:2})});
  alert(r.started ? "已开始运行，可在下方实时查看。" : ("未启动："+(r.reason||"")));
};
$("#clock").textContent = new Date().toLocaleString("zh-CN");
setInterval(()=>$("#clock").textContent = new Date().toLocaleString("zh-CN"), 1000);

(async()=>{ await initAdapters(); await refreshAll(); connectLive(); })();
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "HarnessDashboard/1.0"

    def log_message(self, *args):  # silence
        pass

    # ------------------------------------------------------------------ #

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        one = lambda k, d=None: (query.get(k) or [d])[0]  # noqa: E731
        try:
            if path == "/":
                self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/adapters":
                self._json(list_adapters())
                return
            if path == "/api/summary":
                self._json(DASH.summary(one("adapter", "leucs")))
                return
            if path == "/api/cases":
                self._json(DASH.cases(one("adapter", "leucs")))
                return
            if path == "/api/runs":
                self._json(DASH.runs(one("adapter", "leucs"), one("kind"), one("case_id"),
                                      int(one("limit", "500"))))
                return
            if path == "/api/run":
                rec = DASH.run_detail(one("adapter", "leucs"), one("run_id", ""))
                self._json(rec or {"error": "not found"}, 200 if rec else 404)
                return
            if path == "/api/events":
                self._json(DASH.events(one("adapter", "leucs"), one("run_id", "")))
                return
            if path == "/api/live":
                self._stream_live()
                return
            self._json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        if parsed.path == "/api/run":
            adapter = body.get("adapter", "leucs")
            self._json(DASH.trigger(adapter, body.get("cases"), int(body.get("repeat") or 0)))
            return
        self._json({"error": "not found"}, 404)

    def _stream_live(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q: "queue.Queue[dict]" = queue.Queue(maxsize=200)
        with _LOCK:
            _SUBSCRIBERS.append(q)
        try:
            while True:
                try:
                    payload = q.get(timeout=15)
                    data = json.dumps(payload, ensure_ascii=False)
                except queue.Empty:
                    data = json.dumps({"type": "heartbeat"}, ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _LOCK:
                if q in _SUBSCRIBERS:
                    _SUBSCRIBERS.remove(q)


def main(argv: List[str]) -> int:
    global DASH
    parser = argparse.ArgumentParser(description="Harness web dashboard")
    parser.add_argument("--port", type=int, default=8801)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--evidence-dir", default=str(ROOT / "evidence"))
    args = parser.parse_args(argv)

    DASH = Dashboard(Path(args.evidence_dir))
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Harness dashboard: http://{args.host}:{args.port}")
    print(f"  evidence dir : {args.evidence_dir}")
    print(f"  adapters     : {', '.join(a['name'] for a in list_adapters())}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(os.sys.argv[1:]))
