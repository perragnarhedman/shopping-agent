from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable, TypeVar


ResultT = TypeVar("ResultT")


class RetryError(Exception):
    pass


async def retry_async(
    operation: Callable[[], Awaitable[ResultT]],
    *,
    retries: int = 3,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 8.0,
    jitter_fraction: float = 0.2,
) -> ResultT:
    """Exponential backoff with jitter for async operations.

    Jitter: +/- jitter_fraction * delay
    """
    attempt = 0
    last_exc: Exception | None = None
    delay = base_delay_seconds
    while attempt <= retries:
        try:
            return await operation()
        except Exception as exc:  # noqa: BLE001 - we want to retry on any exception
            last_exc = exc
            if attempt == retries:
                break
            jitter = delay * jitter_fraction
            sleep_for = max(0.0, min(max_delay_seconds, delay + random.uniform(-jitter, jitter)))
            await asyncio.sleep(sleep_for)
            delay = min(max_delay_seconds, delay * 2.0)
            attempt += 1
    raise RetryError(f"Operation failed after {retries + 1} attempts") from last_exc


__all__ = ["retry_async", "RetryError"]


