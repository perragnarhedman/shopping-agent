from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from playwright.async_api import Page

from src.core.web_automation import (
    click_selector,
    new_context,
    new_page,
    safe_goto,
    type_selector,
    screenshot_on_failure,
)
from src.utils.config_loader import ConfigLoader
from src.agents.human_io import human_broker
from src.core.events import publish_event
import os


@dataclass
class ToolEnv:
    page: Page
    store: str
    invoke_subagent: Optional[Callable[[str, str], Awaitable[Dict[str, Any]]]] = None
    run_id: Optional[str] = None


def _load_store_login_signals(store: str) -> list[str]:
    cfg = ConfigLoader.load_global_config()
    return (cfg.get("stores", {}).get(store, {}) or {}).get("login_signals", [])


async def t_goto(env: ToolEnv, *, url: str) -> Dict[str, Any]:
    await safe_goto(env.page, url)
    return {"ok": True}


async def t_wait_network_idle(env: ToolEnv, *, timeout_ms: int = 30000) -> Dict[str, Any]:
    try:
        await env.page.wait_for_load_state("networkidle", timeout=timeout_ms)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def t_exists(env: ToolEnv, *, selector: str) -> Dict[str, Any]:
    count = await env.page.locator(selector).count()
    return {"ok": True, "exists": count > 0}


async def t_count(env: ToolEnv, *, selector: str) -> Dict[str, Any]:
    count = await env.page.locator(selector).count()
    return {"ok": True, "count": count}


async def t_query_text(env: ToolEnv, *, selector: str, max_len: int = 200) -> Dict[str, Any]:
    loc = env.page.locator(selector).first
    txt = (await loc.text_content()) or ""
    if len(txt) > max_len:
        txt = txt[:max_len]
    return {"ok": True, "text": txt.strip()}


async def t_click(env: ToolEnv, *, selector: str) -> Dict[str, Any]:
    await click_selector(env.page, selector)
    return {"ok": True}


async def t_type(env: ToolEnv, *, selector: str, text: str) -> Dict[str, Any]:
    await type_selector(env.page, selector, text)
    return {"ok": True}


async def t_press(env: ToolEnv, *, selector: str, key: str) -> Dict[str, Any]:
    await env.page.locator(selector).first.press(key)
    return {"ok": True}


async def t_screenshot(env: ToolEnv, *, tag: str = "shot", path: str | None = None) -> Dict[str, Any]:
    import datetime
    ts = datetime.datetime.now().strftime("-%Y%m%d-%H%M%S")
    file_path = path or f"logs/{tag}{ts}.png"
    # Ensure directory exists
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
    except Exception:
        pass
    await env.page.screenshot(path=file_path, full_page=True)
    return {"ok": True, "path": file_path}


async def t_accept_cookies(env: ToolEnv) -> Dict[str, Any]:
    """Attempt to accept cookie banners using semantic matching only.

    Strategy:
    - If a common overlay container exists (#cmpwrapper), search inside it first.
    - Click a visible button/link with common accept texts.
    - Wait briefly for the overlay to disappear (best effort).
    """
    try:
        overlay = env.page.locator("#cmpwrapper").first
    except Exception:
        overlay = None  # type: ignore

    # Candidate button texts (case-insensitive)
    candidates = [
        "Acceptera", "Godkänn", "Godkänna", "Accept", "I understand", "OK", "Ok", "Jag förstår",
    ]

    async def click_any_button(scope_locator) -> bool:
        for label in candidates:
            try:
                btn = scope_locator.get_by_role("button", name=label)
                if await btn.count() > 0:
                    await btn.first.click(timeout=5000)
                    return True
            except Exception:
                pass
            try:
                link = scope_locator.get_by_text(label, exact=False)
                if await link.count() > 0:
                    await link.first.click(timeout=5000)
                    return True
            except Exception:
                pass
        return False

    clicked = False
    try:
        if overlay and await overlay.count() > 0:
            try:
                if await overlay.is_visible():
                    clicked = await click_any_button(overlay)
            except Exception:
                pass
        if not clicked:
            clicked = await click_any_button(env.page)
    except Exception:
        clicked = False

    # Best-effort wait for overlay to disappear
    try:
        if overlay:
            await overlay.wait_for(state="hidden", timeout=5000)
    except Exception:
        pass

    return {"ok": True, "clicked": bool(clicked)}


"""
Hint/CSS selector tools have been removed to favor robust semantic tools.
"""


async def t_check_logged_in(env: ToolEnv) -> Dict[str, Any]:
    signals = _load_store_login_signals(env.store)
    for sig in signals:
        try:
            if await env.page.locator(sig).count() > 0:
                return {"ok": True, "logged_in": True, "signal": sig}
        except Exception:
            continue
    return {"ok": True, "logged_in": False}


async def t_invoke_subagent(env: ToolEnv, *, name: str, goal: str) -> Dict[str, Any]:
    if env.invoke_subagent is None:
        return {"ok": False, "error": "invoke_subagent not configured"}
    result = await env.invoke_subagent(name, goal)
    return {"ok": True, "result": result}


TOOL_IMPLS = {
    "goto": t_goto,
    "wait_network_idle": t_wait_network_idle,
    "exists": t_exists,
    "count": t_count,
    "query_text": t_query_text,
    "click": t_click,
    "type": t_type,
    "press": t_press,
    "screenshot": t_screenshot,
    "accept_cookies": t_accept_cookies,
    "check_logged_in": t_check_logged_in,
    "invoke_subagent": t_invoke_subagent,
}


async def t_request_input(env: ToolEnv, *, kind: str = "generic", prompt: str = "", timeout_seconds: int = 120) -> Dict[str, Any]:
    # Register a wait and block until submitted via /agent/input
    if not env.run_id:
        return {"ok": False, "error": "run_id not set in environment"}
    try:
        # Notify UI: awaiting human input
        try:
            await publish_event({
                "type": "awaiting_human",
                "run_id": env.run_id,
                "kind": kind or "generic",
                "prompt": prompt or "",
            })
        except Exception:
            pass
        req_kind = kind or "generic"
        value = await human_broker.wait_for_input(env.run_id, req_kind, timeout_seconds=timeout_seconds)
        # Notify UI: human input received (do not include value)
        try:
            await publish_event({
                "type": "human_input",
                "run_id": env.run_id,
                "kind": req_kind,
            })
        except Exception:
            pass
        return {"ok": True, "value": value}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}

TOOL_IMPLS["request_input"] = t_request_input


# Hint/CSS tools removed


# --- Secrets tool (auth-only) ---
import os


async def t_get_secret(env: ToolEnv, *, name: str) -> Dict[str, Any]:
    if name not in {"COOP_USERNAME", "COOP_PASSWORD"}:
        return {"ok": False, "error": "secret not allowed"}
    val = os.getenv(name)
    if not val:
        return {"ok": False, "error": f"secret {name} is empty"}
    # Do not log actual value
    return {"ok": True, "value": val}


TOOL_IMPLS["get_secret"] = t_get_secret


# Secret hint typing removed


# --- Wait for hint state tool ---
# wait_for_hint removed


# --- Semantic tools (store-agnostic) ---
from playwright.async_api import Locator
import re


async def t_click_text(env: ToolEnv, *, text: str, exact: bool = False, timeout_ms: int = 60000) -> Dict[str, Any]:
    try:
        # Try direct match first
        loc = env.page.get_by_text(text, exact=exact)
        await loc.first.wait_for(state="visible", timeout=timeout_ms)
        await loc.first.click(timeout=timeout_ms)
        return {"ok": True}
    except Exception:
        # Fallbacks: normalize hyphen variants and use a regex that matches -, ‑, – , —
        try:
            hyphen_variants = "-‑–—"
            normalized = text.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
            pattern_str = re.escape(normalized).replace("\\-", f"[{hyphen_variants}]")
            pattern = re.compile(pattern_str, re.IGNORECASE)
            loc = env.page.get_by_text(pattern)
            await loc.first.wait_for(state="visible", timeout=timeout_ms)
            await loc.first.click(timeout=timeout_ms)
            return {"ok": True, "fallback": "regex"}
        except Exception as exc:
            try:
                await screenshot_on_failure(env.page, "logs/error_click_text.png")
            except Exception:
                pass
            return {"ok": False, "error": str(exc), "text": text, "screenshot": "logs/error_click_text.png"}


async def t_fill_label(env: ToolEnv, *, label: str, value: str, exact: bool = False, timeout_ms: int = 60000, delay_ms: int = 10) -> Dict[str, Any]:
    try:
        loc = env.page.get_by_label(label, exact=exact)
        await loc.first.wait_for(state="visible", timeout=timeout_ms)
        await loc.first.fill("")
        await loc.first.type(value, delay=delay_ms)
        return {"ok": True}
    except Exception as exc:
        try:
            await screenshot_on_failure(env.page, "logs/error_fill_label.png")
        except Exception:
            pass
        return {"ok": False, "error": str(exc), "label": label, "screenshot": "logs/error_fill_label.png"}


async def t_click_role(env: ToolEnv, *, role: str, name: str | None = None, timeout_ms: int = 60000) -> Dict[str, Any]:
    try:
        loc: Locator = env.page.get_by_role(role, name=name)  # type: ignore[arg-type]
        await loc.first.wait_for(state="visible", timeout=timeout_ms)
        await loc.first.click(timeout=timeout_ms)
        return {"ok": True}
    except Exception as exc:
        try:
            await screenshot_on_failure(env.page, "logs/error_click_role.png")
        except Exception:
            pass
        return {"ok": False, "error": str(exc), "role": role, "name": name, "screenshot": "logs/error_click_role.png"}


async def t_current_url(env: ToolEnv) -> Dict[str, Any]:
    try:
        return {"ok": True, "url": env.page.url}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def t_fill_role(
    env: ToolEnv,
    *,
    role: str,
    name: str | None = None,
    value: str,
    exact: bool = False,
    timeout_ms: int = 60000,
    delay_ms: int = 10,
) -> Dict[str, Any]:
    try:
        loc: Locator = env.page.get_by_role(role, name=name, exact=exact)  # type: ignore[arg-type]
        await loc.first.wait_for(state="visible", timeout=timeout_ms)
        await loc.first.fill("")
        await loc.first.type(value, delay=delay_ms)
        return {"ok": True}
    except Exception as exc:
        try:
            await screenshot_on_failure(env.page, "logs/error_fill_role.png")
        except Exception:
            pass
        return {"ok": False, "error": str(exc), "role": role, "name": name, "screenshot": "logs/error_fill_role.png"}


async def t_press_key(env: ToolEnv, *, key: str) -> Dict[str, Any]:
    try:
        await env.page.keyboard.press(key)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# selector update helper removed


async def t_exists_text(env: ToolEnv, *, text: str, exact: bool = False, timeout_ms: int | None = None) -> Dict[str, Any]:
    try:
        if timeout_ms and timeout_ms > 0:
            try:
                await env.page.get_by_text(text, exact=exact).first.wait_for(state="visible", timeout=timeout_ms)
                return {"ok": True, "exists": True}
            except Exception:
                return {"ok": True, "exists": False}
        count = await env.page.get_by_text(text, exact=exact).count()
        return {"ok": True, "exists": count > 0}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def t_wait_text(env: ToolEnv, *, text: str, exact: bool = False, timeout_ms: int = 60000) -> Dict[str, Any]:
    try:
        await env.page.get_by_text(text, exact=exact).first.wait_for(state="visible", timeout=timeout_ms)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# --- Finalize tool: agent can emit a structured final result ---
async def t_finalize(env: ToolEnv, *, status: str, provider: str | None = None, error: str | None = None, screenshot: str | None = None) -> Dict[str, Any]:
    # No side-effects; just echo data so runtime can surface it
    result = {"ok": True, "status": status}
    if provider:
        result["provider"] = provider
    if error:
        result["error"] = error
    if screenshot:
        result["screenshot"] = screenshot
    return result

TOOL_IMPLS.update({
    "click_text": t_click_text,
    "fill_label": t_fill_label,
    "click_role": t_click_role,
    "fill_role": t_fill_role,
    "press_key": t_press_key,
    "current_url": t_current_url,
    "exists_text": t_exists_text,
    "wait_text": t_wait_text,
    "finalize": t_finalize,
})


# --- Modal utilities (semantic, dialog-scoped) ---
def _get_dialog(env: ToolEnv):
    dialog = env.page.get_by_role("dialog").first
    return dialog


async def t_modal_exists(env: ToolEnv) -> Dict[str, Any]:
    try:
        dlg = _get_dialog(env)
        present = await dlg.count() > 0
        title = None
        text = None
        if present:
            try:
                heading = dlg.get_by_role("heading").first
                if await heading.count() > 0:
                    title = (await heading.text_content()) or None
            except Exception:
                pass
            try:
                txt = (await dlg.text_content()) or ""
                txt = txt.strip()
                if len(txt) > 300:
                    txt = txt[:300]
                text = txt or None
            except Exception:
                pass
        return {"ok": True, "present": present, "title": title, "text": text}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def t_modal_click_text(env: ToolEnv, *, text: str, exact: bool = False, timeout_ms: int = 60000) -> Dict[str, Any]:
    try:
        dlg = _get_dialog(env)
        loc = dlg.get_by_text(text, exact=exact)
        await loc.first.wait_for(state="visible", timeout=timeout_ms)
        await loc.first.click(timeout=timeout_ms)
        return {"ok": True}
    except Exception as exc:
        try:
            await screenshot_on_failure(env.page, "logs/error_modal_click_text.png")
        except Exception:
            pass
        return {"ok": False, "error": str(exc), "text": text, "screenshot": "logs/error_modal_click_text.png"}


async def t_modal_fill_label(
    env: ToolEnv,
    *,
    label: str,
    value: str,
    exact: bool = False,
    timeout_ms: int = 60000,
    delay_ms: int = 10,
) -> Dict[str, Any]:
    try:
        dlg = _get_dialog(env)
        # Try by accessible label first
        loc = dlg.get_by_label(label, exact=exact)
        try:
            await loc.first.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            # Fallback to placeholder match inside dialog
            loc = dlg.get_by_placeholder(label, exact=exact)
            try:
                await loc.first.wait_for(state="visible", timeout=timeout_ms)
            except Exception:
                # Last resort: the first textbox in the dialog
                loc = dlg.get_by_role("textbox")
                await loc.first.wait_for(state="visible", timeout=timeout_ms)
        await loc.first.fill("")
        await loc.first.type(value, delay=delay_ms)
        return {"ok": True}
    except Exception as exc:
        try:
            await screenshot_on_failure(env.page, "logs/error_modal_fill_label.png")
        except Exception:
            pass
        return {"ok": False, "error": str(exc), "label": label, "screenshot": "logs/error_modal_fill_label.png"}


async def t_modal_press_key(env: ToolEnv, *, key: str) -> Dict[str, Any]:
    try:
        await env.page.keyboard.press(key)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def t_modal_close(env: ToolEnv, *, timeout_ms: int = 60000) -> Dict[str, Any]:
    try:
        dlg = _get_dialog(env)
        if await dlg.count() == 0:
            return {"ok": True, "closed": False}
        # Try standard close buttons
        try:
            btn = dlg.get_by_role("button", name=re.compile(r"(Stäng|Close|✕|×|Avbryt|OK|Ok)", re.IGNORECASE)).first
            await btn.wait_for(state="visible", timeout=timeout_ms)
            await btn.click(timeout=timeout_ms)
        except Exception:
            # Fallback to Escape
            await env.page.keyboard.press("Escape")
        # Wait for it to disappear
        try:
            await dlg.wait_for(state="hidden", timeout=timeout_ms)
        except Exception:
            pass
        return {"ok": True, "closed": True}
    except Exception as exc:
        try:
            await screenshot_on_failure(env.page, "logs/error_modal_close.png")
        except Exception:
            pass
        return {"ok": False, "error": str(exc), "screenshot": "logs/error_modal_close.png"}


# --- Config read helper (autonomy: agent decides to use) ---
def _get_from_dict(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for part in path.split('.'):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


async def t_get_config(env: ToolEnv, *, key: str) -> Dict[str, Any]:
    try:
        cfg = ConfigLoader.load_global_config()
        val = _get_from_dict(cfg, key)
        # Also surface under data so the runtime forwards it back to the model
        return {"ok": True, "value": val, "data": {"value": val}}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


TOOL_IMPLS.update({
    "modal_exists": t_modal_exists,
    "modal_click_text": t_modal_click_text,
    "modal_fill_label": t_modal_fill_label,
    "modal_press_key": t_modal_press_key,
    "modal_close": t_modal_close,
    "get_config": t_get_config,
})

__all__ = ["ToolEnv", "TOOL_IMPLS"]


