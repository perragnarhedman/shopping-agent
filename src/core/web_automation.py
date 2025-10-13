from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


@asynccontextmanager
async def launch_browser(headless: bool = True) -> AsyncIterator[Browser]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            yield browser
        finally:
            await browser.close()


@asynccontextmanager
async def new_context(browser: Browser) -> AsyncIterator[BrowserContext]:
    context = await browser.new_context()
    # Clear any persisted state to avoid stale autofill/search: ensure fresh context
    try:
        await context.clear_cookies()
    except Exception:
        pass
    try:
        yield context
    finally:
        await context.close()


@asynccontextmanager
async def new_page(context: BrowserContext) -> AsyncIterator[Page]:
    page = await context.new_page()
    try:
        yield page
    finally:
        await page.close()


async def safe_goto(page: Page, url: str, timeout_ms: int = 30000) -> None:
    await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
    await page.wait_for_load_state("networkidle")


async def click_selector(page: Page, selector: str, *, timeout_ms: int = 30000) -> None:
    locator = page.locator(selector)
    await locator.first.wait_for(state="visible", timeout=timeout_ms)
    await locator.first.click(timeout=timeout_ms)
    # brief settle to allow navigations/modals to render
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass


async def type_selector(page: Page, selector: str, text: str, *, timeout_ms: int = 30000, delay_ms: int = 10) -> None:
    locator = page.locator(selector)
    await locator.first.wait_for(state="visible", timeout=timeout_ms)
    await locator.first.fill("")
    await locator.first.type(text, delay=delay_ms)


async def screenshot_on_failure(page: Page, path: str) -> None:
    try:
        # Append timestamp suffix to avoid overwriting
        import os, datetime
        base, ext = os.path.splitext(path)
        ts = datetime.datetime.now().strftime("-%Y%m%d-%H%M%S")
        final = f"{base}{ts}{ext}"
        await page.screenshot(path=final, full_page=True)
    except Exception:
        pass


__all__ = [
    "launch_browser",
    "new_context",
    "new_page",
    "safe_goto",
    "click_selector",
    "type_selector",
    "screenshot_on_failure",
]


