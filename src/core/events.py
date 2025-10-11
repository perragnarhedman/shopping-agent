from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncIterator, Dict, Optional

from redis import asyncio as aioredis


CHANNEL = os.getenv("AGENT_EVENTS_CHANNEL", "agent-events")
REDIS_URL = os.getenv("REDIS_URL", "redis://shopping-agent-redis:6379/0")


_redis_singleton: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    global _redis_singleton
    if _redis_singleton is None:
        _redis_singleton = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis_singleton


async def publish_event(event: Dict[str, Any]) -> None:
    try:
        await get_redis().publish(CHANNEL, json.dumps(event, ensure_ascii=False))
    except Exception:
        # Best-effort: viewer is optional
        pass


async def subscribe_events() -> AsyncIterator[Dict[str, Any]]:
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                try:
                    data = json.loads(message.get("data") or "{}")
                    yield data
                except Exception:
                    continue
            else:
                await asyncio.sleep(0.05)
    finally:
        try:
            await pubsub.unsubscribe(CHANNEL)
        except Exception:
            pass


__all__ = ["publish_event", "subscribe_events", "get_redis", "CHANNEL"]


