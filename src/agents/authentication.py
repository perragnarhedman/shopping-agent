from __future__ import annotations

from typing import Any, Dict

from src.agents.runtime import AgentRunner
from src.agents.tools import ToolEnv, TOOL_IMPLS


class AuthenticationAgent:
    def __init__(self, *, store: str) -> None:
        self._runner = AgentRunner(store=store)
        self._store = store

    async def run(self, *, goal: str, env: ToolEnv, debug: bool = False) -> Dict[str, Any]:
        with open("src/agents/prompts/authentication_system.txt", "r") as f:
            system = f.read()
        # Inject prompt params (no secrets in prompt text)
        import os
        login_id = os.getenv("COOP_USERNAME", "")
        system = system.replace("{{loginId}}", login_id).replace("{{secretRef}}", "COOP_PASSWORD")
        # Max autonomy: derive allowed tools from registry, minus a tiny denylist for safety
        denied = {"invoke_subagent"}
        allowed = sorted(k for k in TOOL_IMPLS.keys() if k not in denied)
        return await self._runner.run(
            agent_name="authentication",
            system_prompt=system,
            user_goal=goal,
            page_env=env,
            allowed_tools=allowed,
            debug=debug,
        )


__all__ = ["AuthenticationAgent"]


