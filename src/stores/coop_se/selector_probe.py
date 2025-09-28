from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict, List

import yaml
from playwright.async_api import Page

from src.core.web_automation import launch_browser, new_context, new_page, safe_goto
from src.core.llm_client import LLMClient
import json


BASE_DIR = Path(__file__).resolve().parent


def _read_config() -> Dict:
    with (BASE_DIR / "config.yaml").open("r") as f:
        return yaml.safe_load(f)


def _read_selectors() -> Dict:
    path = BASE_DIR / "selectors.yaml"
    if not path.exists():
        return {}
    with path.open("r") as f:
        return yaml.safe_load(f) or {}


def _write_selectors(selectors: Dict) -> None:
    with (BASE_DIR / "selectors.yaml").open("w") as f:
        yaml.safe_dump(selectors, f, sort_keys=False, allow_unicode=True)


async def _first_working_selector(page: Page, candidates: List[str], timeout_ms: int = 10000) -> str | None:
    for sel in candidates:
        try:
            await page.locator(sel).first.wait_for(state="visible", timeout=timeout_ms)
            return sel
        except Exception:
            continue
    return None

async def _propose_with_llm(page: Page, purpose: str, hint_text: str | None = None) -> List[str]:
    """Ask the LLM to propose selector candidates based on minimal DOM+text context."""
    try:
        # Collect limited context: title, url, some text snippets
        url = page.url
        title = await page.title()
        # Grab visible buttons/links text to help the LLM
        texts = []
        try:
            texts = await page.evaluate("() => Array.from(document.querySelectorAll('button, a')).slice(0,50).map(e=>e.innerText).filter(Boolean)")
        except Exception:
            texts = []
        client = LLMClient()
        system = Path("src/agents/prompts/selector_probe_system.txt").read_text(encoding="utf-8")
        user = {
            "purpose": purpose,
            "url": url,
            "title": title,
            "hint_text": hint_text or "",
            "visible_button_texts": texts[:20],
        }
        resp = await client._chat_completion_json(system_prompt=system, user_prompt=json.dumps(user), schema={"type":"object","properties":{"candidates":{"type":"array","items":{"type":"string"}}},"required":["candidates"]})  # type: ignore[attr-defined]
        cands = resp.get("candidates", [])
        return [c for c in cands if isinstance(c, str)]
    except Exception:
        return []


async def probe_selectors() -> Dict:
    cfg = _read_config()
    base_url = cfg.get("base_url")
    results: Dict[str, Dict[str, str]] = {"login": {}, "search": {}, "cart": {}, "checkout": {}}

    async with launch_browser(headless=True) as browser:
        async with new_context(browser) as ctx:
            async with new_page(ctx) as page:
                await safe_goto(page, base_url)

                # login (homepage level)
                results["login"]["accept_cookies_button"] = (
                    await _first_working_selector(
                        page,
                        [
                            "#onetrust-accept-btn-handler",
                            "button#onetrust-accept-btn-handler",
                            "button[aria-label='Accept']",
                            "button:has-text('Acceptera')",
                            "text=Acceptera alla",
                            "text=Godkänn alla",
                        ],
                    )
                    or ""
                )
                # If cookie button exists, click to unblock interactions
                try:
                    acb = results["login"].get("accept_cookies_button")
                    if acb:
                        await page.locator(acb).first.click(timeout=10000)
                        try:
                            await page.locator("#cmpwrapper").first.wait_for(state="hidden", timeout=10000)
                        except Exception:
                            pass
                except Exception:
                    pass

                results["login"]["open_login_button"] = (
                    await _first_working_selector(
                        page,
                        [
                            "text=Logga in",
                            "a[href*='login']",
                            "button[data-test*='login']",
                            "a[data-test*='login']",
                        ],
                    )
                    or ""
                )
                if not results["login"]["open_login_button"]:
                    llm_cands = await _propose_with_llm(page, "Open login link/button", hint_text="Logga in")
                    pick = await _first_working_selector(page, llm_cands)
                    results["login"]["open_login_button"] = pick or ""

                # If we have a login button, click it and probe the login form/overlay
                try:
                    if results["login"].get("open_login_button"):
                        await page.locator(results["login"]["open_login_button"]).first.click(timeout=15000)
                        # Wait briefly for either overlay choices or redirect page
                        try:
                            await page.wait_for_load_state("networkidle", timeout=15000)
                        except Exception:
                            pass
                        # Probe buttons for BankID / Email
                        results["login"]["login_with_bankid_button"] = (
                            await _first_working_selector(
                                page,
                                [
                                    "text=Med BankID",
                                    "button:has-text('BankID')",
                                    "[data-testid*='bankid']",
                                ],
                                timeout_ms=10000,
                            )
                            or ""
                        )
                        results["login"]["login_with_email_button"] = (
                            await _first_working_selector(
                                page,
                                [
                                    "text=Med e-post",
                                    "button:has-text('e-post')",
                                    "[data-testid*='email']",
                                ],
                                timeout_ms=10000,
                            )
                            or ""
                        )

                        # If an email button exists, click it to reveal inputs
                        try:
                            if results["login"].get("login_with_email_button"):
                                await page.locator(results["login"]["login_with_email_button"]).first.click(timeout=15000)
                                try:
                                    await page.wait_for_load_state("networkidle", timeout=10000)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        # Probe username/password/submit on login page (login.coop.se)
                        results["login"]["username_input"] = (
                            await _first_working_selector(
                                page,
                                [
                                    "input[name='Email']",
                                    "input[type='email']",
                                    "input[name='username']",
                                ],
                            )
                            or ""
                        )
                        if not results["login"]["username_input"]:
                            pick = await _first_working_selector(page, await _propose_with_llm(page, "username/email field", hint_text="Email / e-post"))
                            results["login"]["username_input"] = pick or ""

                        results["login"]["password_input"] = (
                            await _first_working_selector(
                                page,
                                [
                                    "input[name='Password']",
                                    "input[type='password']",
                                ],
                            )
                            or ""
                        )
                        if not results["login"]["password_input"]:
                            pick = await _first_working_selector(page, await _propose_with_llm(page, "password field", hint_text="Lösenord / Password"))
                            results["login"]["password_input"] = pick or ""

                        results["login"]["submit_button"] = (
                            await _first_working_selector(
                                page,
                                [
                                    "button[type='submit']",
                                    "button:has-text('Logga in')",
                                ],
                            )
                            or ""
                        )
                        if not results["login"]["submit_button"]:
                            pick = await _first_working_selector(page, await _propose_with_llm(page, "submit login button", hint_text="Logga in"))
                            results["login"]["submit_button"] = pick or ""
                except Exception:
                    pass

                # search
                results["search"]["search_input"] = (
                    await _first_working_selector(
                        page,
                        [
                            "input[type='search']",
                            "input[name='q']",
                            "input[placeholder*='Sök']",
                            "input[aria-label*='Sök']",
                        ],
                    )
                    or ""
                )
                results["search"]["search_submit"] = (
                    await _first_working_selector(
                        page,
                        [
                            "button[type='submit']",
                            "button:has-text('Sök')",
                            "[data-test*='search'] button",
                        ],
                    )
                    or ""
                )
                results["search"]["product_card"] = (
                    await _first_working_selector(
                        page,
                        [
                            "[data-test='product-card']",
                            "[data-test*='product-card']",
                            ".product-card",
                            "[data-testid*='product']",
                        ],
                    )
                    or ""
                )
                results["search"]["product_card_name"] = (
                    await _first_working_selector(
                        page,
                        [
                            ".product-card__title",
                            "[data-test='product-card-title']",
                            "[data-testid*='product-name']",
                        ],
                    )
                    or ""
                )
                results["search"]["add_to_cart_button"] = (
                    await _first_working_selector(
                        page,
                        [
                            "button[data-test='add-to-cart']",
                            "button[data-testid*='add-to-cart']",
                            "button[aria-label*='Lägg']",
                            "button:has-text('Köp')",
                        ],
                    )
                    or ""
                )

                # cart
                results["cart"]["open_cart_button"] = (
                    await _first_working_selector(
                        page,
                        [
                            "a[href*='cart']",
                            "button[data-test='open-cart']",
                            "a[aria-label*='Kundvagn']",
                            "text=Kundvagn",
                        ],
                    )
                    or ""
                )
                results["cart"]["checkout_button"] = (
                    await _first_working_selector(
                        page,
                        [
                            "a[href*='checkout']",
                            "button[data-test='checkout']",
                            "button:has-text('Till kassan')",
                        ],
                    )
                    or ""
                )

    return results


async def main() -> None:
    current = _read_selectors()
    found = await probe_selectors()

    # Merge: prefer found non-empty values; keep existing otherwise
    merged: Dict[str, Dict[str, str]] = {}
    for section in ["login", "search", "cart", "checkout"]:
        merged[section] = {**(current.get(section) or {})}
        for key, val in (found.get(section) or {}).items():
            if val:
                merged[section][key] = val
    _write_selectors(merged)
    print("Updated selectors.yaml with:")
    print(yaml.safe_dump(merged, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    asyncio.run(main())


