from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from src.agents.sdk_tools import build_openai_tools, execute_tool
from src.agents.tools import ToolEnv
from src.utils.config_loader import ConfigLoader
from src.core.events import publish_event
from src.core.memory_store import retrieve_known_resolution, record_experience


class AgentSDKRunner:
    def __init__(self, *, model: Optional[str] = None, temperature: float = 0.0) -> None:
        cfg = ConfigLoader.load_global_config()
        agents_cfg = cfg.get("agents", {})
        self._model = model or agents_cfg.get("model") or "gpt-4o-mini"
        self._temperature = float(agents_cfg.get("temperature", temperature))
        timeouts = agents_cfg.get("timeouts", {})
        self._per_step_seconds = int(timeouts.get("per_step_seconds", 30))
        self._max_total_steps = int(agents_cfg.get("max_total_steps", 12))
        self._client = AsyncOpenAI()
        self._logger = logging.getLogger(__name__)

    async def run(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        user_goal: str,
        page_env: ToolEnv,
        allowed_tools: List[str],
        debug: bool = False,
    ) -> Dict[str, Any]:
        # Prepend global system prompt
        try:
            with open("src/agents/prompts/global_system.txt", "r", encoding="utf-8") as f:
                global_system = f.read()
        except Exception:
            global_system = ""
        system_combined = (global_system + "\n\n" + system_prompt).strip()

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_combined},
            {"role": "user", "content": user_goal},
        ]
        tools = build_openai_tools([t for t in allowed_tools if t != "invoke_subagent"])  # safety denylist

        steps_used = 0
        last_config_value: Any | None = None
        trace: List[Dict[str, Any]] = []

        # Ensure clean page state for each run: clear history and localStorage/sessionStorage
        try:
            await page_env.page.context.clear_cookies()
        except Exception:
            pass
        try:
            await page_env.page.add_init_script("window.localStorage.clear(); window.sessionStorage.clear();")
        except Exception:
            pass

        # simple retry accounting to nudge HITL if stuck
        consecutive_failures = 0

        while steps_used < self._max_total_steps:
            # If a modal is currently visible, surface any known resolution recipe as guidance
            try:
                auto_probe = await self._auto_observe_snapshot(page_env)
                if auto_probe.get("modal_present"):
                    # Build a simple signature from url host and modal title/text keywords
                    import urllib.parse
                    parsed = urllib.parse.urlparse(auto_probe.get("url") or "")
                    site = (parsed.hostname or "").lower()
                    title = (auto_probe.get("modal_title") or "").lower()
                    text = (auto_probe.get("modal_text") or "").lower()
                    signature = {
                        "site": site,
                        "title_kws": [w for w in title.split()[:6]],
                        "text_kws": [w for w in text.split()[:10]],
                    }
                    recipe = await retrieve_known_resolution("modal", signature)
                    if recipe:
                        # Provide a KNOWN_RESOLUTION hint while keeping the model in control
                        hint_steps = "; ".join([f"{step.get('tool')}({step.get('args', {})})" for step in recipe])
                        messages.append({
                            "role": "assistant",
                            "content": f"KNOWN_RESOLUTION: Based on past successful runs, try: {hint_steps}",
                        })
            except Exception:
                pass
            resp = await self._client.chat.completions.create(
                model=self._model,
                temperature=self._temperature,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            choice = resp.choices[0]
            msg = choice.message
            tool_calls = msg.tool_calls or []

            # Append the assistant message we just received to preserve protocol context.
            # If there are tool_calls, they must be included on the assistant message that precedes our tool results.
            if tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments or "{}",
                            },
                        }
                        for tc in tool_calls
                    ],
                })
            elif msg.content:
                messages.append({"role": "assistant", "content": msg.content})

            if not tool_calls:
                # No tool calls; append assistant text (if any) and provide auto-observe context as assistant message
                if msg.content:
                    messages.append({"role": "assistant", "content": msg.content})
                auto_obs = await self._auto_observe_snapshot(page_env)
                # Provide lightweight context without violating tool-call protocol
                messages.append({
                    "role": "assistant",
                    "content": f"CONTEXT_AUTO_OBSERVE: {json.dumps(auto_obs)}",
                })
                try:
                    await publish_event({"type": "auto_observe", "data": auto_obs})
                except Exception:
                    pass
                steps_used += 1
                continue

            # Execute tool calls in order
            for tc in tool_calls:
                name = tc.function.name
                args = {}
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}

                # Auto-substitute last config value for postcode placeholders
                if name in {"modal_fill_label", "fill_label"}:
                    val = args.get("value")
                    if isinstance(val, str) and val.strip() in {"<to-be-filled>", "", "<value>"} and last_config_value not in (None, ""):
                        args = dict(args)
                        args["value"] = str(last_config_value)

                # Execute tool safely; always produce a tool message
                try:
                    result = await execute_tool(name, args, page_env)
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}
                # Publish step event for live viewer
                try:
                    await publish_event({
                        "type": "tool_result",
                        "tool": name,
                        "args": args,
                        "result": result,
                    })
                except Exception:
                    pass
                # Capture get_config value for substitution
                if name == "get_config" and result.get("ok"):
                    if "value" in result:
                        last_config_value = result.get("value")
                    elif isinstance(result.get("data"), dict) and "value" in result.get("data", {}):
                        last_config_value = result["data"].get("value")

                # Append the tool result message back
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                })
                steps_used += 1
                # update failure counter
                if isinstance(result, dict) and not result.get("ok", True):
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0

                # Keep a trace similar to the legacy runner
                if debug:
                    trace.append({"tool": name, "args": args, "result": result})

                # Only honor termination via finalize tool
                if name == "finalize" and result.get("ok"):
                    out: Dict[str, Any] = {"run_id": agent_name, "terminated": True, "observations": []}
                    out["result"] = {
                        "status": result.get("status"),
                        "provider": result.get("provider"),
                        "error": result.get("error"),
                        "screenshot": result.get("screenshot"),
                    }
                    if debug:
                        out["trace"] = trace
                    return out

                # Inject auto-observe context as assistant message (not a tool response)
                auto_obs = await self._auto_observe_snapshot(page_env)
                messages.append({
                    "role": "assistant",
                    "content": f"CONTEXT_AUTO_OBSERVE: {json.dumps(auto_obs)}",
                })
                # If repeated failures or a modal persists, nudge the model to ask for HITL
                try:
                    if consecutive_failures >= 2 or auto_obs.get("modal_present"):
                        messages.append({
                            "role": "assistant",
                            "content": "CONTEXT_HINT: If blocked, call request_input(kind='modal_help', prompt='Describe the visible dialog/button text and what you need to proceed').",
                        })
                except Exception:
                    pass
                try:
                    await publish_event({"type": "auto_observe", "data": auto_obs})
                except Exception:
                    pass

        # Budget exceeded
        out = {"run_id": agent_name, "terminated": False, "reason": "max_steps_exceeded"}
        if debug:
            out["trace"] = trace
        return out

    async def _auto_observe_snapshot(self, env: ToolEnv) -> Dict[str, Any]:
        # Mirror minimal auto_observe fields so the model can reason without another tool
        try:
            url = env.page.url
        except Exception:
            url = ""
        overlay = False
        try:
            loc = env.page.locator("#cmpwrapper").first
            if await loc.count() > 0:
                try:
                    overlay = await loc.is_visible()
                except Exception:
                    overlay = False
        except Exception:
            overlay = False
        modal_present = False
        modal_title = None
        modal_text = None
        modal_kind = None
        try:
            dialog = env.page.get_by_role("dialog").first
            visible_dialog = False
            if await dialog.count() > 0:
                try:
                    visible_dialog = await dialog.is_visible()
                except Exception:
                    visible_dialog = False
            if not visible_dialog:
                aria = env.page.locator("[aria-modal='true']").first
                if await aria.count() > 0:
                    try:
                        if await aria.is_visible():
                            dialog = aria
                            visible_dialog = True
                    except Exception:
                        visible_dialog = False
            if visible_dialog:
                modal_present = True
                try:
                    heading = dialog.get_by_role("heading").first
                    if await heading.count() > 0:
                        modal_title = (await heading.text_content()) or None
                except Exception:
                    pass
                try:
                    txt = (await dialog.text_content()) or ""
                    txt = txt.strip()
                    if len(txt) > 300:
                        txt = txt[:300]
                    modal_text = txt or None
                    low = (txt or "").lower()
                    if any(k in low for k in ["postnummer", "var är du", "hitta butik", "leveransadress"]):
                        modal_kind = "postcode"
                except Exception:
                    pass
        except Exception:
            pass
        return {
            "ok": True,
            "url": url,
            "overlay": overlay,
            "modal_present": modal_present,
            "modal_title": modal_title,
            "modal_text": modal_text,
            "modal_kind": modal_kind,
        }


__all__ = ["AgentSDKRunner"]


