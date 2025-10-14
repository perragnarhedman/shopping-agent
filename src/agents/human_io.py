from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional

from typing import Any


@dataclass
class PendingInput:
    future: asyncio.Future[str]
    kind: str


class HumanIOBroker:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._pending: Dict[str, PendingInput] = {}

    async def wait_for_input(self, run_id: str, kind: str, timeout_seconds: int = 120) -> str:
        fut: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._pending[run_id] = PendingInput(future=fut, kind=kind)
        try:
            return await asyncio.wait_for(fut, timeout=timeout_seconds)
        finally:
            self._pending.pop(run_id, None)

    def submit_input(self, run_id: str, kind: str, value: str) -> bool:
        pending = self._pending.get(run_id)
        if not pending or pending.kind != kind:
            return False
        if not pending.future.done():
            pending.future.set_result(value)
        return True


human_broker = HumanIOBroker()


__all__ = ["human_broker", "HumanIOBroker"]


