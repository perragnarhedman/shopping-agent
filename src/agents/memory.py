from __future__ import annotations

from typing import Any

from src.core.memory_store import MemoryStore


class MemoryAgent:
    def __init__(self) -> None:
        self._store = MemoryStore()

    def store_context(self, key: str, value: Any) -> None:
        self._store.set(key, value)

    def retrieve_relevant_context(self, key: str) -> Any | None:
        return self._store.get(key)


__all__ = ["MemoryAgent"]


