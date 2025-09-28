from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from src.core.web_automation import click_selector


async def accept_cookies_if_present(page: Page, selector: str) -> None:
    try:
        await page.locator(selector).first.wait_for(state="visible", timeout=2000)
        await click_selector(page, selector, timeout_ms=5000)
    except Exception:
        return


__all__ = ["accept_cookies_if_present"]


