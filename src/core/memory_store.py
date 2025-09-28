from __future__ import annotations

import os
from typing import Any, Dict, Optional

try:
    import redis  # type: ignore
except Exception:  # noqa: BLE001
    redis = None  # type: ignore[assignment]


class MemoryStore:
    def __init__(self) -> None:
        backend = os.getenv("MEMORY_BACKEND", "local").lower()
        self._is_redis = backend == "redis" and redis is not None
        if self._is_redis:
            url = os.getenv("REDIS_URL", "redis://redis:6379/0")
            self._client = redis.Redis.from_url(url, decode_responses=True)  # type: ignore[attr-defined]
        else:
            self._store: Dict[str, Any] = {}

    def set(self, key: str, value: Any, *, ttl_seconds: Optional[int] = None) -> None:
        if self._is_redis:
            if ttl_seconds is not None:
                self._client.setex(key, ttl_seconds, value)
            else:
                self._client.set(key, value)
        else:
            self._store[key] = value

    def get(self, key: str) -> Any | None:
        if self._is_redis:
            return self._client.get(key)
        return self._store.get(key)

    def delete(self, key: str) -> None:
        if self._is_redis:
            self._client.delete(key)
        else:
            self._store.pop(key, None)


__all__ = ["MemoryStore"]


