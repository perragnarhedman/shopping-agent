from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from src.agents.agent_sdk_runner import AgentSDKRunner
from src.agents.tools import ToolEnv, TOOL_IMPLS


class ShoppingAgent:
    def __init__(self, *, store: str) -> None:
        self._runner = AgentSDKRunner()
        self._store = store

    async def run(self, *, goal: str, env: ToolEnv, debug: bool = False) -> Dict[str, Any]:
        with open("src/agents/prompts/shopping_system.txt", "r") as f:
            system = f.read()
        # Align with current shopping prompt which uses semantic + hint tools
        denied = {"invoke_subagent"}
        allowed = sorted(k for k in TOOL_IMPLS.keys() if k not in denied)
        return await self._runner.run(
            agent_name="shopping",
            system_prompt=system,
            user_goal=goal,
            page_env=env,
            allowed_tools=allowed,
            debug=debug,
        )


__all__ = ["ShoppingAgent"]


