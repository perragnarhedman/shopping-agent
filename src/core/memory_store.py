from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from redis import asyncio as aioredis


REDIS_URL = os.getenv("REDIS_URL", "redis://shopping-agent-redis:6379/0")
MEMORY_ENABLED = os.getenv("AGENT_MEMORY_ENABLED", "true").lower() == "true"
MEMORY_TTL_SECONDS = int(os.getenv("AGENT_MEMORY_TTL_SECONDS", "0"))  # 0 = no TTL
_redis: Optional[aioredis.Redis] = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def _key(kind: str, site: str) -> str:
    return f"agmem:{kind}:{site}"


async def record_experience(kind: str, signature: Dict[str, Any], recipe: List[Dict[str, Any]], *, max_keep: int = 100) -> None:
    """Append a minimal experience entry to Redis (LPUSH + LTRIM)."""
    if not MEMORY_ENABLED:
        return
    site = (signature.get("site") or "unknown").lower()
    entry = {
        "ts": int(time.time()),
        "signature": {
            "site": site,
            "title_kws": signature.get("title_kws", [])[:6],
            "text_kws": signature.get("text_kws", [])[:10],
        },
        "recipe": [
            {"tool": step.get("tool"), "args": step.get("args", {})}
            for step in (recipe or [])
        ],
    }
    try:
        r = _get_redis()
        if MEMORY_TTL_SECONDS > 0:
            entry["ttl"] = MEMORY_TTL_SECONDS
        await r.lpush(_key(kind, site), json.dumps(entry, ensure_ascii=False))
        await r.ltrim(_key(kind, site), 0, max_keep - 1)
    except Exception:
        pass


def _score(sig_a: Dict[str, Any], sig_b: Dict[str, Any]) -> int:
    """Simple overlap score by keyword intersection."""
    a_title = set((sig_a.get("title_kws") or [])[:6])
    a_text = set((sig_a.get("text_kws") or [])[:10])
    b_title = set((sig_b.get("title_kws") or [])[:6])
    b_text = set((sig_b.get("text_kws") or [])[:10])
    return len(a_title & b_title) + len(a_text & b_text)


async def retrieve_known_resolution(kind: str, signature: Dict[str, Any], *, search_n: int = 50) -> Optional[List[Dict[str, Any]]]:
    """Return the best recipe for a signature if any, else None."""
    if not MEMORY_ENABLED:
        return None
    site = (signature.get("site") or "unknown").lower()
    try:
        r = _get_redis()
        items = await r.lrange(_key(kind, site), 0, search_n - 1)
        best = None
        best_score = -1
        for raw in items:
            try:
                ent = json.loads(raw)
            except Exception:
                continue
            score = _score(signature, ent.get("signature") or {})
            if score > best_score:
                best = ent
                best_score = score
        if best and best.get("recipe"):
            return list(best["recipe"])  # [{tool, args}]
    except Exception:
        pass
    return None


__all__ = ["record_experience", "retrieve_known_resolution"]


