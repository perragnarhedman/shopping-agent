#!/usr/bin/env python3
import asyncio
import uuid
import logging
from fastapi import FastAPI
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi import HTTPException
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv
import yaml

from src.core.logger import setup_logging
from src.utils.config_loader import ConfigLoader
from src.agents.human_io import human_broker
from src.agents.tools import ToolEnv
from src.core.temporal_client import get_temporal_client
from src.core.events import subscribe_events
from src.workflows.auth_workflow import AuthenticationWorkflow
from src.workflows.shopping_workflow import ShoppingWorkflow


load_dotenv()

app = FastAPI()
app.mount("/logs", StaticFiles(directory="logs"), name="logs")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "healthy"})


async def startup() -> None:
    setup_logging()
    logging.getLogger(__name__).info("Booting Shopping Agent API...")
    _ = ConfigLoader.load_global_config()


class AgentInput(BaseModel):
    run_id: str
    kind: str
    value: str


@app.post("/agent/input")
async def submit_agent_input(payload: AgentInput) -> JSONResponse:
    ok = human_broker.submit_input(payload.run_id, payload.kind, payload.value)
    if not ok:
        raise HTTPException(status_code=404, detail="No pending input for this run_id/kind")
    return JSONResponse({"status": "accepted"}, status_code=202)


class RunRequest(BaseModel):
    goal: str
    store: str = "coop_se"
    headless: bool = True
    debug: bool = False
    login_method: str | None = None


# removed legacy /run endpoint (v1)


# removed legacy /run/authentication endpoint (v1)


@app.get("/ui/qr")
async def ui_qr(run_id: str | None = None) -> HTMLResponse:
    html = (
        """
        <html>
          <head><meta http-equiv="refresh" content="3"></head>
          <body>
            <h3>BankID QR</h3>
            <p>Refreshes every 3s. If empty, the agent hasn't produced a QR yet.</p>
            <img src="/logs/bankid_qr.png" alt="QR" style="max-width:480px;"/>
          </body>
        </html>
        """
    )
    return HTMLResponse(html)


@app.get("/ui/qr/auto")
async def ui_qr_auto(run_id: str | None = None) -> HTMLResponse:
    # Simple watcher page that opens the QR tab once the file appears
    target = f"/ui/qr?run_id={run_id or ''}"
    html = f"""
    <html>
      <body>
        <h3>Waiting for BankID request…</h3>
        <p>This page will open the QR in a new tab when available.</p>
        <script>
          let opened = false;
          async function check() {{
            try {{
              const res = await fetch('/logs/bankid_qr.png?ts=' + Date.now(), {{ method: 'HEAD', cache: 'no-store' }});
              if (res.ok && !opened) {{
                opened = true;
                window.open('{target}', '_blank');
              }}
            }} catch (e) {{}}
          }}
          setInterval(check, 2000);
          check();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(html)


@app.websocket("/ws/agent-events")
async def ws_agent_events(ws: WebSocket) -> None:
    await ws.accept()
    try:
        async for evt in subscribe_events():
            await ws.send_json(evt)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass


@app.get("/ui/live")
async def ui_live() -> HTMLResponse:
    html = (
        """
        <html>
          <head>
            <meta charset=\"utf-8\" />
            <title>Agent Live Viewer</title>
            <style>
              body { font-family: -apple-system, system-ui, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 0; }
              .bar { display:flex; align-items:center; gap:12px; padding:10px 14px; border-bottom:1px solid #eee; }
              .btn { background:#0b5fff; color:#fff; border:none; padding:8px 12px; border-radius:6px; cursor:pointer; }
              .btn.secondary { background:#eee; color:#333; }
              .wrap { display:flex; height: calc(100vh - 52px); }
              .pane { flex:1; overflow:auto; }
              .logs { padding:12px; }
              .event { border-bottom:1px solid #f0f0f0; padding:8px 0; font-size:14px; }
              .event .meta { color:#666; font-size:12px; margin-bottom:4px; }
              .event pre { background:#fafafa; padding:8px; border-radius:6px; overflow:auto; }
            </style>
          </head>
          <body>
            <div class=\"bar\">
              <button class=\"btn\" onclick=\"window.open('https://www.coop.se/', '_blank')\">Open coop.se</button>
              <button class=\"btn secondary\" onclick=\"clearLogs()\">Clear</button>
              <span id=\"status\" style=\"margin-left:auto;color:#666;\">Disconnected</span>
            </div>
            <div class=\"wrap\">
              <div class=\"pane logs\" id=\"logPane\"></div>
            </div>
            <script>
              const logPane = document.getElementById('logPane');
              const statusEl = document.getElementById('status');
              function addEvent(evt) {
                const div = document.createElement('div');
                div.className = 'event';
                const meta = document.createElement('div');
                meta.className = 'meta';
                meta.textContent = `[${new Date().toLocaleTimeString()}] ${evt.type || 'event'}`;
                const pre = document.createElement('pre');
                pre.textContent = JSON.stringify(evt, null, 2);
                div.appendChild(meta);
                div.appendChild(pre);
                logPane.prepend(div);
              }
              function clearLogs(){ logPane.innerHTML=''; }
              function connect() {
                const proto = (location.protocol === 'https:') ? 'wss' : 'ws';
                const ws = new WebSocket(`${proto}://${location.host}/ws/agent-events`);
                ws.onopen = () => { statusEl.textContent = 'Connected'; statusEl.style.color = '#0a0'; };
                ws.onclose = () => { statusEl.textContent = 'Disconnected'; statusEl.style.color = '#a00'; setTimeout(connect, 1500); };
                ws.onerror = () => { statusEl.textContent = 'Error'; statusEl.style.color = '#a00'; };
                ws.onmessage = (e) => {
                  try { addEvent(JSON.parse(e.data)); } catch { /* ignore */ }
                };
              }
              connect();
            </script>
          </body>
        </html>
        """
    )
    return HTMLResponse(html)


@app.get("/ui/desktop")
async def ui_desktop() -> HTMLResponse:
    html = (
        """
        <html>
          <head>
            <meta charset=\"utf-8\" />
            <title>Agent Desktop Viewer</title>
            <style>
              body { margin:0; height:100vh; display:flex; flex-direction:column; }
              header { padding:10px 12px; border-bottom:1px solid #eee; font-family: -apple-system, system-ui, Segoe UI, Roboto, Helvetica, Arial, sans-serif; }
              iframe { flex:1; width:100%; border:0; }
            </style>
          </head>
          <body>
            <header>
              <strong>Desktop Viewer</strong> – mirrors the worker's Chromium via noVNC
            </header>
            <iframe src="http://localhost:6080/vnc_auto.html?autoconnect=true"></iframe>
          </body>
        </html>
        """
    )
    return HTMLResponse(html)




@app.get("/ui/start")
async def ui_start() -> HTMLResponse:
    html = (
        """
        <html>
          <head>
            <meta charset=\"utf-8\" />
            <title>Start Shopping Run</title>
            <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"/>
            <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin/>
            <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap\" rel=\"stylesheet\"/>
            <style>
              :root { --bg:#0b0c10; --card:#111318; --muted:#8f9baa; --text:#e6e9ef; --accent:#22c55e; }
              *{ box-sizing:border-box }
              body { margin:0; background:#0b0c10; color:var(--text); font-family: Inter, -apple-system, system-ui, Segoe UI, Roboto, Helvetica, Arial, sans-serif; }
              .wrap { display:grid; grid-template-columns: 360px 1fr; height:100vh; }
              .side { padding:20px; border-right:1px solid #1b1e24; background:linear-gradient(180deg, #0e1015 0%, #0b0c10 100%); }
              .card { background:var(--card); border:1px solid #1b1e24; border-radius:12px; padding:16px; box-shadow: 0 10px 30px rgba(0,0,0,0.25); }
              .title { font-size:18px; font-weight:600; margin:0 0 12px; }
              textarea { width:100%; height:160px; resize:vertical; background:#0d0f14; color:var(--text); border:1px solid #20232a; border-radius:10px; padding:10px 12px; font-family: inherit; }
              .row { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:12px 0; }
              .toggle { display:flex; align-items:center; gap:10px; color:var(--muted); }
              .btn { background:var(--accent); border:none; color:#0a0f0a; font-weight:600; padding:10px 14px; border-radius:10px; cursor:pointer; }
              .btn:disabled { opacity:0.6; cursor:not-allowed; }
              .main { display:flex; flex-direction:column; }
              header { display:flex; align-items:center; justify-content:space-between; padding:14px 18px; border-bottom:1px solid #1b1e24; }
              .status { font-size:13px; color:var(--muted); }
              .panes { display:grid; grid-template-rows: auto 1fr; gap:10px; padding:12px; }
              .messages { background:var(--card); border:1px solid #1b1e24; border-radius:10px; padding:12px; max-height:220px; overflow:auto; }
              iframe { width:100%; height:100%; border:0; background:#000; border-radius:10px; }
              .timeline { background:var(--card); border:1px solid #1b1e24; border-radius:10px; padding:12px; overflow:auto; }
              .event { border-bottom:1px solid #1b1e24; padding:8px 0; font-size:14px; }
              .event .meta { color:var(--muted); font-size:12px; margin-bottom:4px; }
              .muted { color:var(--muted); }
              a.link { color:#8ab4ff; text-decoration:none; }
            </style>
          </head>
          <body>
            <div class=\"wrap\">
              <aside class=\"side\">
                <div class=\"card\">
                  <h3 class=\"title\">Start a Shopping Run</h3>
                  <label class=\"muted\">Shopping list (one item per line or comma-separated)</label>
                  <textarea id=\"shopping_list\" placeholder=\"e.g. mjölk, bröd\"></textarea>
                  <div class=\"row\">
                    <label class=\"toggle\"><input id=\"headless\" type=\"checkbox\"/> Headless</label>
                    <button id=\"startBtn\" class=\"btn\">Start</button>
                  </div>
                  <div class=\"muted\" id=\"runInfo\">No run started</div>
                  <div style=\"margin-top:10px\"><a class=\"link\" href=\"/ui/desktop\" target=\"_blank\">Open Desktop Viewer</a> · <a class=\"link\" href=\"/ui/live\" target=\"_blank\">Open Live Events</a></div>
                </div>
              </aside>
              <main class=\"main\">
                <header>
                  <div><strong>Shopping Agent</strong> <span class=\"status\" id=\"status\">Idle</span></div>
                </header>
                <div class=\"panes\">
                  <div class=\"messages\" id=\"messages\"></div>
                  <iframe id=\"viewer\" src=\"/ui/desktop\" style=\"height:60vh\"></iframe>
                  <div class=\"timeline\" id=\"timeline\"></div>
                </div>
              </main>
            </div>
            <script>
              const startBtn = document.getElementById('startBtn');
              const headless = document.getElementById('headless');
              const shoppingList = document.getElementById('shopping_list');
              const runInfo = document.getElementById('runInfo');
              const timeline = document.getElementById('timeline');
              const statusEl = document.getElementById('status');
              const msgPane = document.getElementById('messages');
              let runId = null;

              function addEvent(evt){
                const div = document.createElement('div');
                div.className = 'event';
                const meta = document.createElement('div');
                meta.className = 'meta';
                meta.textContent = '[' + new Date().toLocaleTimeString() + '] ' + (evt.type || 'event');
                const pre = document.createElement('pre');
                pre.textContent = JSON.stringify(evt, null, 2);
                div.appendChild(meta); div.appendChild(pre);
                timeline.prepend(div);
              }

              function connectEvents(){
                const proto = (location.protocol === 'https:') ? 'wss' : 'ws';
                const ws = new WebSocket(proto + '://' + location.host + '/ws/agent-events');
                ws.onmessage = (e)=>{ try { const evt = JSON.parse(e.data); addEvent(evt); statusEl.textContent = 'Running';
                  if (evt.type === 'tool_result' || evt.type === 'auto_observe') {
                    const div = document.createElement('div');
                    div.style.borderBottom = '1px solid #1b1e24';
                    div.style.padding = '6px 0';
                    div.textContent = JSON.stringify(evt, null, 2);
                    msgPane.prepend(div);
                    // keep only last ~8 messages
                    while (msgPane.childElementCount > 8) msgPane.removeChild(msgPane.lastChild);
                  }
                } catch {} };
                ws.onclose = ()=>{ statusEl.textContent = 'Idle'; };
              }

              startBtn.onclick = async ()=>{
                startBtn.disabled = true;
                try {
                  const payload = {
                    store: 'coop_se',
                    headless: !!headless.checked,
                    debug: true,
                    task_queue: 'shopping-agent-task-queue',
                    shopping_list: shoppingList.value
                  };
                  const res = await fetch('/v2/run/shopping', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                  const json = await res.json();
                  if (json.workflow_id){
                    runId = json.workflow_id;
                    runInfo.textContent = 'Run: ' + runId;
                    statusEl.textContent = 'Running';
                    connectEvents();
                    try { window.open('/ui/desktop', '_blank'); } catch(e) {}
                    try { window.open('/ui/live', '_blank'); } catch(e) {}
                  }
                } catch (e) { console.error(e); }
                finally { startBtn.disabled = false; }
              };
            </script>
          </body>
        </html>
        """
    )
    return HTMLResponse(html)


@app.get("/ui/login/email")
async def ui_login_email(run_id: str) -> HTMLResponse:
    html = f"""
    <html>
      <body>
        <h3>Email login</h3>
        <p>When ready, click Continue. The agent will proceed using your saved credentials.</p>
        <form method="post" action="/agent/input">
          <input type="hidden" name="run_id" value="{run_id}">
          <input type="hidden" name="kind" value="email_continue">
          <input type="hidden" name="value" value="OK">
          <button type="submit">Continue</button>
        </form>
      </body>
    </html>
    """
    return HTMLResponse(html)


# removed legacy /run/shopping endpoint (v1)


class V2RunRequest(BaseModel):
    store: str = "coop_se"
    headless: bool = True
    debug: bool = False
    login_method: str | None = None
    workflow_id: str | None = None
    task_queue: str = "shopping-agent-task-queue"
    shopping_list: str | None = None


@app.post("/v2/run/authentication")
async def v2_run_authentication(req: V2RunRequest) -> JSONResponse:
    try:
        client = await get_temporal_client()
        payload = req.model_dump()
        workflow_id = req.workflow_id or f"auth-{uuid.uuid4()}"
        handle = await client.start_workflow(
            AuthenticationWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=req.task_queue,
        )
        return JSONResponse({"workflow_id": handle.id})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/v2/run/shopping")
async def v2_run_shopping(req: V2RunRequest) -> JSONResponse:
    try:
        client = await get_temporal_client()
        payload = req.model_dump()
        workflow_id = req.workflow_id or f"shop-{uuid.uuid4()}"
        handle = await client.start_workflow(
            ShoppingWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=req.task_queue,
        )
        return JSONResponse({"workflow_id": handle.id})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


class SignalRequest(BaseModel):
    workflow_id: str


@app.post("/v2/signal/pause")
async def signal_pause(req: SignalRequest) -> JSONResponse:
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(req.workflow_id)
        await handle.signal(ShoppingWorkflow.pause)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/v2/signal/resume")
async def signal_resume(req: SignalRequest) -> JSONResponse:
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(req.workflow_id)
        await handle.signal(ShoppingWorkflow.resume)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/v2/signal/cancel")
async def signal_cancel(req: SignalRequest) -> JSONResponse:
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(req.workflow_id)
        await handle.signal(ShoppingWorkflow.cancel)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def run() -> None:
    asyncio.run(startup())
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)


if __name__ == "__main__":
    run()


