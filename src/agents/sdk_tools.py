from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.agents.tools import TOOL_IMPLS, ToolEnv


def build_openai_tools(allowed_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Return OpenAI tool definitions for the registered tools.

    We start permissive (additionalProperties=True) and can tighten per-tool schemas later.
    """
    names = allowed_names or list(TOOL_IMPLS.keys())
    tools: List[Dict[str, Any]] = []
    for name in names:
        if name not in TOOL_IMPLS:
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": f"Execute tool {name}",
                "parameters": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {},
                },
            },
        })
    return tools


async def execute_tool(tool_name: str, args: Dict[str, Any], env: ToolEnv) -> Dict[str, Any]:
    impl = TOOL_IMPLS.get(tool_name)
    if not impl:
        return {"ok": False, "error": f"unknown tool: {tool_name}"}
    try:
        return await impl(env, **(args or {}))
    except TypeError as exc:
        # Better error for arg mismatch
        return {"ok": False, "error": f"bad args for {tool_name}: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


__all__ = ["build_openai_tools", "execute_tool"]


