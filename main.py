#!/usr/bin/env python3
import asyncio
import logging
from fastapi import FastAPI
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
from src.agents.main_orchestrator import Orchestrator
from src.agents.authentication import AuthenticationAgent
from src.agents.shopping import ShoppingAgent
from src.agents.tools import ToolEnv
from src.core.web_automation import launch_browser, new_context, new_page, safe_goto


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


@app.post("/run")
async def run_orchestrator(req: RunRequest) -> JSONResponse:
    orchestrator = Orchestrator(store=req.store)
    async with launch_browser(headless=req.headless) as browser:
        async with new_context(browser) as ctx:
            async with new_page(ctx) as page:
                with open(f"src/stores/{req.store}/config.yaml", "r") as f:
                    cfg = yaml.safe_load(f)
                await safe_goto(page, cfg["base_url"])
                env = ToolEnv(page=page, store=req.store)
                try:
                    result = await orchestrator.run(goal=req.goal, env=env, debug=req.debug)
                    return JSONResponse(result)
                except Exception as exc:
                    return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/run/authentication")
async def run_authentication(req: RunRequest) -> JSONResponse:
    agent = AuthenticationAgent(store=req.store)
    async with launch_browser(headless=req.headless) as browser:
        async with new_context(browser) as ctx:
            async with new_page(ctx) as page:
                with open(f"src/stores/{req.store}/config.yaml", "r") as f:
                    cfg = yaml.safe_load(f)
                await safe_goto(page, cfg["base_url"])
                env = ToolEnv(page=page, store=req.store)
                try:
                    # Default to email if not provided
                    method = req.login_method or "email"
                    goal = "Log in to coop.se and confirm logged-in state."
                    goal += f" Login method: {method}."
                    result = await agent.run(goal=goal, env=env, debug=req.debug)
                    return JSONResponse(result)
                except Exception as exc:
                    import traceback
                    logging.getLogger(__name__).exception("/run/authentication failed: %s", exc)
                    return JSONResponse({"error": str(exc), "traceback": traceback.format_exc()}, status_code=500)


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


@app.post("/run/shopping")
async def run_shopping(req: RunRequest) -> JSONResponse:
    agent = ShoppingAgent(store=req.store)
    async with launch_browser(headless=req.headless) as browser:
        async with new_context(browser) as ctx:
            async with new_page(ctx) as page:
                with open(f"src/stores/{req.store}/config.yaml", "r") as f:
                    cfg = yaml.safe_load(f)
                await safe_goto(page, cfg["base_url"])
                env = ToolEnv(page=page, store=req.store)
                try:
                    result = await agent.run(goal="Find 'mjölk', add 1 unit to cart, then open the cart.", env=env, debug=req.debug)
                    return JSONResponse(result)
                except Exception as exc:
                    return JSONResponse({"error": str(exc)}, status_code=500)


def run() -> None:
    asyncio.run(startup())
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)


if __name__ == "__main__":
    run()


