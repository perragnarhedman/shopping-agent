from __future__ import annotations

import asyncio
import uuid
import json
import logging
from typing import Any, Dict, List, Tuple

from src.core.schema_validator import load_json_schema_from_file, try_validate_with_jsonschema
from src.agents.tools import TOOL_IMPLS, ToolEnv
from src.core.llm_client import LLMClient
from src.utils.config_loader import ConfigLoader


class AgentRunner:
    def __init__(self, *, store: str, global_budget: int | None = None) -> None:
        self._store = store
        cfg = ConfigLoader.load_global_config()
        agents_cfg = cfg.get("agents", {})
        self._model = agents_cfg.get("model")
        self._temperature = float(agents_cfg.get("temperature", 0.0))
        self._max_steps = int(agents_cfg.get("max_steps_per_agent", 2))
        timeouts = agents_cfg.get("timeouts", {})
        self._per_step_seconds = int(timeouts.get("per_step_seconds", 30))
        self._max_actions_per_step = int(agents_cfg.get("max_actions_per_step", 1))
        self._client = LLMClient(model=self._model, temperature=self._temperature)
        self._global_budget = global_budget or int(agents_cfg.get("max_total_steps", 6))
        self._global_spent = 0
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
        run_id = str(uuid.uuid4())
        # Prepend global system prompt if present
        try:
            with open("src/agents/prompts/global_system.txt", "r", encoding="utf-8") as f:
                global_system = f.read()
        except Exception:
            global_system = ""
        system_combined = (global_system + "\n\n" + system_prompt).strip()
        conversation: List[Dict[str, str]] = [
            {"role": "system", "content": system_combined},
            {"role": "user", "content": user_goal},
        ]
        trace: List[Dict[str, Any]] = []

        for step in range(self._max_steps):
            if self._global_spent >= self._global_budget:
                result = {"run_id": run_id, "terminated": False, "reason": "global_budget_exceeded"}
                if debug:
                    result["trace"] = trace
                return result
            self._logger.debug(
                "agent.next_decision %s",
                json.dumps({
                    "agent": agent_name,
                    "step": step,
                    "global_spent": self._global_spent,
                    "global_budget": self._global_budget,
                    "allowed_tools": allowed_tools,
                    "max_actions_per_step": self._max_actions_per_step,
                }),
            )
            decision = await self._next_decision(conversation, allowed_tools)
            self._logger.debug(
                "agent.decision %s",
                json.dumps({"agent": agent_name, "step": step, "decision": decision}, ensure_ascii=False),
            )
            observations: List[Dict[str, Any]] = []
            # Observe -> Act(s) -> Observe
            actions_to_run = []
            if isinstance(decision, dict):
                actions = decision.get("actions", [])
                if isinstance(actions, list):
                    actions_to_run = actions[: max(1, self._max_actions_per_step)]
            for call in actions_to_run:
                # Guardrail: forbid placeholders
                args = call.get("args", {}) if isinstance(call, dict) else {}
                if isinstance(args, dict):
                    sel = str(args.get("selector", ""))
                    txt = str(args.get("text", ""))
                    if "_FROM_HINT" in sel or "${USERNAME}" in txt or "${PASSWORD}" in txt:
                        observations.append({"tool": call.get("name"), "ok": False, "error": "placeholders not allowed"})
                        continue
                tool_name = call.get("name") if isinstance(call, dict) else None
                if tool_name not in allowed_tools:
                    observations.append({"tool": tool_name, "ok": False, "error": "tool not allowed"})
                    continue
                self._logger.debug(
                    "tool.exec %s",
                    json.dumps({"agent": agent_name, "step": step, "tool": tool_name, "args": args}, ensure_ascii=False),
                )
                # propagate run_id for request_input
                page_env.run_id = run_id
                obs = await self._execute_tool(page_env, tool_name, args)
                observations.append({"tool": tool_name, **obs})
                self._logger.debug(
                    "tool.result %s",
                    json.dumps({
                        "agent": agent_name,
                        "step": step,
                        "tool": tool_name,
                        "ok": obs.get("ok"),
                        "summary": obs.get("summary"),
                        "data": obs.get("data"),
                        "error": obs.get("error"),
                    }, ensure_ascii=False),
                )
                self._global_spent += 1

            # Auto-observe after the actions
            try:
                url = page_env.page.url  # type: ignore[attr-defined]
            except Exception:
                url = ""
            overlay = False
            try:
                loc = page_env.page.locator("#cmpwrapper").first  # type: ignore[attr-defined]
                if await loc.count() > 0:
                    try:
                        overlay = await loc.is_visible()
                    except Exception:
                        overlay = False
            except Exception:
                overlay = False
            # Minimal modal detection (read-only): look for role=dialog or aria-modal=true
            modal_present = False
            modal_title = None
            modal_text = None
            modal_kind = None
            try:
                dialog = page_env.page.get_by_role("dialog").first  # type: ignore[attr-defined]
                visible_dialog = False
                if await dialog.count() > 0:
                    try:
                        visible_dialog = await dialog.is_visible()
                    except Exception:
                        visible_dialog = False
                if not visible_dialog:
                    # Fallback: aria-modal=true and visible
                    aria = page_env.page.locator("[aria-modal='true']").first  # type: ignore[attr-defined]
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

            auto_obs = {"tool": "auto_observe", "ok": True, "data": {"url": url, "overlay": overlay, "modal_present": modal_present, "modal_title": modal_title, "modal_text": modal_text, "modal_kind": modal_kind}}
            observations.append(auto_obs)
            self._logger.debug("tool.result %s", json.dumps({"agent": agent_name, "step": step, **auto_obs}, ensure_ascii=False))

            # Append structured observations as assistant message JSON string
            conversation.append({
                "role": "assistant",
                "content": json.dumps({
                    "observations": [
                        {"tool": o.get("tool"), "ok": o.get("ok"), "summary": o.get("summary"), "data": o.get("data")}
                        for o in observations
                    ]
                })
            })

            # Keep a step trace for debugging
            if debug:
                trace.append({
                    "step": step,
                    "decision": decision,
                    "observations": observations,
                    "global_spent": self._global_spent,
                })

            if isinstance(decision, dict) and bool(decision.get("terminate")):
                self._logger.debug(
                    "agent.terminate %s",
                    json.dumps({"agent": agent_name, "step": step}),
                )
                # If a finalize tool was called, capture its last payload for convenience
                final = next((o for o in reversed(observations) if o.get("tool") == "finalize" and o.get("ok")), None)
                result = {"run_id": run_id, "terminated": True, "observations": observations}
                if final:
                    result["result"] = {
                        "status": final.get("status"),
                        "provider": final.get("provider"),
                        "error": final.get("error"),
                        "screenshot": final.get("screenshot"),
                    }
                if debug:
                    result["trace"] = trace
                return result

        result = {"run_id": run_id, "terminated": False, "reason": "max_steps_exceeded"}
        if debug:
            result["trace"] = trace
        return result

    async def _next_decision(self, conversation: List[Dict[str, str]], allowed_tools: List[str]) -> Dict[str, Any]:
        schema = load_json_schema_from_file("src/agents/schemas/agent_decision.schema.json")
        system = conversation[0]["content"]
        user = "\n\n".join([m["content"] for m in conversation[1:]])
        prompt = user + f"\n\nAllowed tools: {allowed_tools}. Return a valid AgentDecision JSON."
        try:
            # Using LLM in JSON schema mode with file-based schema
            return await self._client.complete_json_with_schema(
                system_prompt=system,
                user_prompt=prompt,
                schema=schema,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Invalid AgentDecision: {exc}")

    async def _execute_tool(self, env: ToolEnv, tool_name: str | None, args: Dict[str, Any]) -> Dict[str, Any]:
        if not tool_name:
            return {"ok": False, "error": "missing tool name"}
        impl = TOOL_IMPLS.get(tool_name)
        if not impl:
            return {"ok": False, "error": "unknown tool"}
        # Enforce per-step timeout
        try:
            return await asyncio.wait_for(impl(env, **args), timeout=self._per_step_seconds)
        except asyncio.TimeoutError:
            # Provide a clearer timeout message, include key/selector if present
            arg_desc = None
            if isinstance(args, dict):
                if "key" in args:
                    arg_desc = f"key={args.get('key')}"
                elif "selector" in args:
                    arg_desc = f"selector={args.get('selector')}"
            detail = f"timeout after {self._per_step_seconds}s"
            if arg_desc:
                detail += f" ({arg_desc})"
            return {"ok": False, "error": detail}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}


__all__ = ["AgentRunner"]


