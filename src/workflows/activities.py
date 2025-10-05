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

    agent = AuthenticationAgent(store=store)
    async with launch_browser(headless=headless) as browser:
        async with new_context(browser) as ctx:
            async with new_page(ctx) as page:
                await safe_goto(page, _base_url_for_store(store))
                env = ToolEnv(page=page, store=store)
                result = await agent.run(goal=f"Authenticate to {store} using {login_method}", env=env, debug=debug)
                return result


@activity.defn
async def run_shopping_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    store = payload.get("store", "coop_se")
    headless = bool(payload.get("headless", True))
    debug = bool(payload.get("debug", False))

    agent = ShoppingAgent(store=store)
    async with launch_browser(headless=headless) as browser:
        async with new_context(browser) as ctx:
            async with new_page(ctx) as page:
                await safe_goto(page, _base_url_for_store(store))
                env = ToolEnv(page=page, store=store)
                result = await agent.run(goal="Find 'mjölk', add 1 unit to cart, then open the cart.", env=env, debug=debug)
                return result


def _base_url_for_store(store: str) -> str:
    # Lightweight lookup to avoid importing yaml/config here
    if store == "coop_se":
        return "https://www.coop.se/"
    return "https://www.coop.se/"


