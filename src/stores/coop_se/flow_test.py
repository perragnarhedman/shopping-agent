from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any, Dict

import yaml

from src.core.web_automation import launch_browser, new_context, new_page, safe_goto
from src.agents.authentication import AuthenticationAgent
from src.agents.shopping import ShoppingAgent
from src.stores.coop_se.store_interface import accept_cookies_if_present


BASE_DIR = Path(__file__).resolve().parent


def _read_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r") as f:
        return yaml.safe_load(f)


async def run_flow(query: str, headless: bool = True) -> None:
    cfg = _read_yaml(BASE_DIR / "config.yaml")
    selectors = _read_yaml(BASE_DIR / "selectors.yaml")

    base_url = cfg["base_url"]
    login_sels = selectors.get("login", {})
    search_sels = selectors.get("search", {})
    cart_sels = selectors.get("cart", {})

    username = os.getenv("COOP_USERNAME")
    password = os.getenv("COOP_PASSWORD")
    if not username or not password:
        raise RuntimeError("COOP_USERNAME and COOP_PASSWORD must be set. No fallbacks allowed.")

    auth = AuthenticationAgent()
    shop = ShoppingAgent()

    async with launch_browser(headless=headless) as browser:
        async with new_context(browser) as ctx:
            async with new_page(ctx) as page:
                print(f"Navigating to: {base_url}")
                await safe_goto(page, base_url)

                # Accept cookies if present
                if login_sels.get("accept_cookies_button"):
                    await accept_cookies_if_present(page, login_sels["accept_cookies_button"])

                # Login (required)
                print("Attempting login...")
                await auth.login_user(page, login_sels, username, password)

                # Search
                print(f"Searching for: {query}")
                products = await shop.search_products(page, search_sels, query)
                print(f"Found {len(products)} products")
                if not products:
                    return

                # Add first product to cart
                print("Adding first product to cart...")
                await shop.add_to_cart(page, search_sels, index=0, quantity=1)

                # Open cart
                print("Opening cart...")
                await shop.proceed_to_checkout(page, cart_sels)
                print("Cart opened (proceeded to checkout start).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="mjölk", help="Search query, default 'mjölk'")
    parser.add_argument("--headful", action="store_true", help="Run browser headful (for local debugging)")
    args = parser.parse_args()

    asyncio.run(run_flow(query=args.query, headless=not args.headful))


if __name__ == "__main__":
    main()


