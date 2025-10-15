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
            <title>Shopping Agent</title>
            <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"/>
            <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin/>
            <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap\" rel=\"stylesheet\"/>
            <style>
              /* ChatGPT-like dark theme */
              :root {
                --bg:#0e0f13;           /* page background */
                --panel:#0f1117;        /* chat bubble (assistant) */
                --panel-2:#0b0d12;      /* side panel background */
                --border:#262a34;       /* subtle borders */
                --muted:#9aa4b2;        /* secondary text */
                --text:#e7ebf0;         /* primary text */
                --accent:#10b981;       /* emerald */
                --user:#1a2330;         /* user bubble */
              }
              *{ box-sizing:border-box }
              body {
                margin:0; background:var(--bg); color:var(--text);
                font-family: Inter, -apple-system, system-ui, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
              }
              .app { display:grid; grid-template-columns: 520px 1fr; height:100vh; }
              .left { display:flex; flex-direction:column; border-right:1px solid var(--border); background:var(--panel-2); }
              .right { display:flex; flex-direction:column; }
              .head { display:flex; align-items:center; gap:10px; padding:14px 16px; border-bottom:1px solid var(--border); }
              .head .dot { width:8px; height:8px; border-radius:50%; background:var(--accent); box-shadow:0 0 0 3px rgba(16,185,129,0.15); }
              .head .title { font-weight:600; letter-spacing:0.2px; }
              .actions { display:flex; gap:8px; margin-left:auto; }
              .btn { background:#1a1f29; color:#d5d9e3; border:1px solid var(--border); font-weight:500; padding:8px 12px; border-radius:10px; cursor:pointer; }
              .btn:hover{ background:#1d2330; }
              .btn.primary { background:var(--accent); color:#062; border-color:#0e9f6e; }
              .muted { color:var(--muted); font-size:12px; }

              .chat { flex:1; overflow:auto; padding:18px; display:flex; flex-direction:column; gap:14px; }
              .row { display:flex; gap:10px; align-items:flex-start; }
              .avatar { width:28px; height:28px; border-radius:50%; flex:0 0 28px; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; }
              .avatar.assistant { background:linear-gradient(135deg,#093,#0a7); color:#eafff6; border:1px solid #0b5; }
              .avatar.user { background:#243447; color:#cde7ff; border:1px solid #2b3d51; }
              .bubble { max-width:85%; padding:12px 14px; border-radius:14px; line-height:1.5; border:1px solid var(--border); }
              .assistant .bubble { background:var(--panel); }
              .user .bubble { background:var(--user); }

              .input { padding:14px 16px; border-top:1px solid var(--border); display:flex; gap:10px; }
              .input input { flex:1; background:#0f131a; color:var(--text); border:1px solid var(--border); border-radius:999px; padding:12px 16px; }
              .send { background:var(--accent); color:#052; border:none; font-weight:700; padding:10px 16px; border-radius:999px; cursor:pointer; }

              .canvasHead { display:flex; align-items:center; justify-content:space-between; padding:12px 16px; border-bottom:1px solid var(--border); }
              .pill { font-size:12px; background:#0d141c; color:#9ff5c7; border:1px solid #17333a; padding:4px 8px; border-radius:999px; }
              .canvasWrap { flex:1; padding:12px; }
              .viewer { width:100%; height:100%; border:0; background:#000; border-radius:12px; box-shadow: 0 18px 48px rgba(0,0,0,0.35); }
            </style>
          </head>
          <body>
            <div class=\"app\">
              <section class=\"left\">
                <div class=\"head\">
                  <span class=\"dot\"></span>
                  <div>
                    <div class=\"title\">Shopping Agent</div>
                    <div class=\"muted\" id=\"status\">Stopped</div>
                  </div>
                  <div class=\"actions\">
                    <button class=\"btn secondary\" id=\"pauseBtn\">Pause</button>
                    <button class=\"btn secondary\" id=\"resumeBtn\">Resume</button>
                    <button class=\"btn secondary\" id=\"cancelBtn\">Cancel</button>
                  </div>
                </div>
                <div id=\"chat\" class=\"chat\"></div>
                <div class=\"input\">
                  <input id=\"chatInput\" placeholder=\"Message Shopping Agent… (/shop <item>, /pause, /resume, /cancel)\" />
                  <button id=\"sendBtn\" class=\"send\">Send</button>
                </div>
              </section>
              <section class=\"right\">
                <div class=\"canvasHead\">
                  <div><strong>Canvas</strong> <span class=\"pill\" id=\"runBadge\">No run</span></div>
                  <div class=\"muted\">noVNC live viewer</div>
                </div>
                <div class=\"canvasWrap\">
                  <iframe id=\"viewer\" class=\"viewer\" src=\"http://localhost:6080/vnc_auto.html?autoconnect=true\"></iframe>
                </div>
              </section>
            </div>

            <script>
              const chat = document.getElementById('chat');
              const input = document.getElementById('chatInput');
              const sendBtn = document.getElementById('sendBtn');
              const statusEl = document.getElementById('status');
              const runBadge = document.getElementById('runBadge');
              const pauseBtn = document.getElementById('pauseBtn');
              const resumeBtn = document.getElementById('resumeBtn');
              const cancelBtn = document.getElementById('cancelBtn');

              let runId = null;

              function scrollToBottom(){ chat.scrollTop = chat.scrollHeight; }

              function addMsg(text, who){
                const row = document.createElement('div');
                const role = who || 'assistant';
                row.className = 'row ' + role;
                const av = document.createElement('div');
                av.className = 'avatar ' + role;
                av.textContent = role === 'assistant' ? 'A' : 'U';
                const bub = document.createElement('div');
                bub.className = 'bubble';
                bub.textContent = text;
                row.appendChild(av); row.appendChild(bub);
                chat.appendChild(row);
                scrollToBottom();
              }

              function mapEventToAssistantText(evt){
                try {
                  if (evt.type === 'tool_result') {
                    const ok = evt.result && evt.result.ok !== undefined ? evt.result.ok : (evt.result ? true : false);
                    const args = evt.args ? JSON.stringify(evt.args) : '';
                    return `(${evt.tool}) ${ok ? 'ok' : 'error'} ${args}`;
                  }
                  if (evt.type === 'auto_observe') {
                    const u = evt.data && evt.data.url ? evt.data.url : '';
                    const m = evt.data && evt.data.modal_present ? ' · cart/modal open' : '';
                    return `Observed: ${u}${m}`;
                  }
                  if (evt.type === 'awaiting_human') {
                    return null; // handled separately
                  }
                  if (evt.type === 'human_input') {
                    return `Human input received: ${evt.value}`;
                  }
                  if (evt.type === 'human_input_failed') {
                    return `Human input failed: ${evt.error}`;
                  }
                  return JSON.stringify(evt);
                } catch { return '[event]'; }
              }

              function showHumanInputForm(runId, kind, prompt){
                // Remove any existing input form
                const existing = document.getElementById('hitl-form-wrapper');
                if (existing) existing.remove();

                // Create new form wrapper
                const wrapper = document.createElement('div');
                wrapper.id = 'hitl-form-wrapper';
                wrapper.style.cssText = 'margin:1rem 0; padding:1rem; background:#f9fafb; border-radius:0.5rem; border:1px solid #e5e7eb;';

                // Prompt text
                const promptP = document.createElement('p');
                promptP.style.cssText = 'margin:0 0 0.75rem 0; font-weight:500; color:#374151;';
                promptP.textContent = prompt || 'Agent is waiting for your input:';
                wrapper.appendChild(promptP);

                // Input field
                const inputField = document.createElement('input');
                inputField.type = 'text';
                inputField.id = 'hitl-input';
                inputField.placeholder = 'Type your response here...';
                inputField.style.cssText = 'width:100%; padding:0.5rem; border:1px solid #d1d5db; border-radius:0.375rem; margin-bottom:0.5rem;';
                wrapper.appendChild(inputField);

                // Submit button
                const submitBtn = document.createElement('button');
                submitBtn.textContent = 'Submit';
                submitBtn.style.cssText = 'padding:0.5rem 1rem; background:#10b981; color:#fff; border:none; border-radius:0.375rem; cursor:pointer; font-weight:500;';
                submitBtn.onclick = async () => {
                  const value = inputField.value.trim();
                  if (!value) return;
                  try {
                    const formData = new FormData();
                    formData.append('run_id', runId);
                    formData.append('kind', kind);
                    formData.append('value', value);
                    await fetch('/agent/input', { method:'POST', body: formData });
                    addMsg('You: ' + value, 'user');
                    wrapper.remove();
                  } catch (e) {
                    addMsg('Failed to send input: ' + (e && e.message ? e.message : e), 'assistant');
                  }
                };
                wrapper.appendChild(submitBtn);
                
                // Enter key support
                inputField.addEventListener('keydown', (e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    submitBtn.click();
                  }
                });

                // Add to chat
                chat.appendChild(wrapper);
                scrollToBottom();
                inputField.focus();
              }

              function connectEvents(){
                const proto = (location.protocol === 'https:') ? 'wss' : 'ws';
                const ws = new WebSocket(proto + '://' + location.host + '/ws/agent-events');
                ws.onopen = () => { statusEl.textContent = 'Running'; };
                ws.onclose = () => { statusEl.textContent = 'Stopped'; setTimeout(connectEvents, 1500); };
                ws.onmessage = (e) => {
                  try {
                    const evt = JSON.parse(e.data);
                    if (!evt) return;
                    
                    // Handle awaiting_human specially
                    if (evt.type === 'awaiting_human') {
                      addMsg('Agent is waiting for your input...', 'assistant');
                      showHumanInputForm(evt.run_id, evt.kind, evt.prompt);
                      return;
                    }
                    
                    const txt = mapEventToAssistantText(evt);
                    if (txt) addMsg(txt, 'assistant');
                    if (evt.type === 'tool_result' && evt.tool === 'finalize' && evt.result && evt.result.status){
                      addMsg('Done: ' + evt.result.status, 'assistant');
                    }
                  } catch {}
                };
              }

              async function startShopping(shoppingList){
                addMsg('You: /shop ' + shoppingList, 'user');
                try {
                  const payload = { store:'coop_se', headless:false, debug:true, task_queue:'shopping-agent-task-queue', shopping_list: shoppingList };
                  const res = await fetch('/v2/run/shopping', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
                  const json = await res.json();
                  if (json.workflow_id){
                    runId = json.workflow_id; runBadge.textContent = runId; statusEl.textContent = 'Running';
                  } else if (json.error){
                    addMsg('Error: ' + json.error, 'assistant');
                  }
                } catch (e) { addMsg('Error starting: ' + (e && e.message ? e.message : e), 'assistant'); }
              }

              async function signal(kind){
                if (!runId){ addMsg('No active run', 'assistant'); return; }
                const url = kind === 'pause' ? '/v2/signal/pause' : kind === 'resume' ? '/v2/signal/resume' : '/v2/signal/cancel';
                try {
                  await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ workflow_id: runId }) });
                  addMsg('You: /' + kind, 'user');
                } catch (e) { addMsg('Signal failed: ' + (e && e.message ? e.message : e), 'assistant'); }
              }

              sendBtn.onclick = () => {
                const text = (input.value || '').trim();
                if (!text) return;
                if (text.startsWith('/shop')) {
                  const q = text.replace('/shop', '').trim();
                  startShopping(q || 'mjölk');
                } else if (text === '/pause') {
                  signal('pause');
                } else if (text === '/resume') {
                  signal('resume');
                } else if (text === '/cancel') {
                  signal('cancel');
                } else {
                  addMsg('You: ' + text, 'user');
                }
                input.value = '';
              };

              input.addEventListener('keydown', (e)=>{ if (e.key === 'Enter'){ e.preventDefault(); sendBtn.click(); }});

              // init
              addMsg('Hi! Type /shop mjölk to start a run. Use /pause, /resume, /cancel to control it.', 'assistant');
              connectEvents();
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
        payload["workflow_id"] = workflow_id
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
        payload["workflow_id"] = workflow_id
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


