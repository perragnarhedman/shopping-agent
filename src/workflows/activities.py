from __future__ import annotations

import asyncio
from typing import Any, Dict

from temporalio import activity

from src.agents.authentication import AuthenticationAgent
from src.agents.shopping import ShoppingAgent
from src.agents.tools import ToolEnv
from src.core.web_automation import launch_browser, new_context, new_page, safe_goto


@activity.defn
async def run_authentication_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    store = payload.get("store", "coop_se")
    headless = bool(payload.get("headless", True))
    debug = bool(payload.get("debug", False))
    login_method = payload.get("login_method") or "email"
    workflow_id = payload.get("workflow_id") or "authentication"

    agent = AuthenticationAgent(store=store)
    async with launch_browser(headless=headless) as browser:
        async with new_context(browser) as ctx:
            async with new_page(ctx) as page:
                await safe_goto(page, _base_url_for_store(store))
                env = ToolEnv(page=page, store=store, run_id=workflow_id)
                result = await agent.run(goal=f"Authenticate to {store} using {login_method}", env=env, debug=debug)
                return result


@activity.defn
async def run_shopping_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    store = payload.get("store", "coop_se")
    headless = bool(payload.get("headless", True))
    debug = bool(payload.get("debug", False))
    workflow_id = payload.get("workflow_id") or "shopping"

    agent = ShoppingAgent(store=store)
    async with launch_browser(headless=headless) as browser:
        async with new_context(browser) as ctx:
            async with new_page(ctx) as page:
                await safe_goto(page, _base_url_for_store(store))
                env = ToolEnv(page=page, store=store, run_id=workflow_id)
                shopping_list = (payload.get("shopping_list") or "").strip()
                if shopping_list:
                    goal = f"Shop the following items: {shopping_list}. Add exactly 1 unit of each, then open the cart."
                else:
                    goal = "Find 'mjölk', add 1 unit to cart, then open the cart."
                # Ensure a clean context per run: new browser context already isolates storage.
                # Also tag events with workflow_id to correlate in UI if needed.
                result = await agent.run(goal=goal, env=env, debug=debug)
                return result


def _base_url_for_store(store: str) -> str:
    # Lightweight lookup to avoid importing yaml/config here
    if store == "coop_se":
        return "https://www.coop.se/"
    return "https://www.coop.se/"


