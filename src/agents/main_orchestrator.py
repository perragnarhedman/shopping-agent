from __future__ import annotations

from typing import Any, Dict, List

from src.agents.runtime import AgentRunner
from src.agents.tools import ToolEnv, TOOL_IMPLS


class Orchestrator:
    def __init__(self, *, store: str) -> None:
        self._runner = AgentRunner(store=store)
        self._store = store

    async def run(self, *, goal: str, env: ToolEnv, debug: bool = False) -> Dict[str, Any]:
        with open("src/agents/prompts/orchestrator_system.txt", "r") as f:
            system = f.read()

        async def _invoke_subagent(name: str, subgoal: str) -> Dict[str, Any]:
            if name == "authentication":
                from src.agents.authentication import AuthenticationAgent  # local import to avoid cycles
                agent = AuthenticationAgent(store=self._store)
                return await agent.run(goal=subgoal, env=env)
            if name == "shopping":
                from src.agents.shopping import ShoppingAgent
                agent = ShoppingAgent(store=self._store)
                return await agent.run(goal=subgoal, env=env)
            return {"error": f"unknown subagent {name}"}

        env.invoke_subagent = _invoke_subagent
        # Max autonomy: expose the full tool registry
        allowed = sorted(TOOL_IMPLS.keys())
        return await self._runner.run(
            agent_name="orchestrator",
            system_prompt=system,
            user_goal=goal,
            page_env=env,
            allowed_tools=allowed,
            debug=debug,
        )


__all__ = ["Orchestrator"]


