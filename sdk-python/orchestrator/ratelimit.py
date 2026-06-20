"""Async token-bucket rate limiter.

One bucket gates the global dispatch rate; one bucket per named provider gates
that provider's requests (and, optionally, tokens). Acquiring blocks cooperatively
until capacity is available, yielding the event loop to other ready tasks.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from .spec import RateLimit


class TokenBucket:
    def __init__(self, rate: float, per: float, capacity: Optional[float] = None, name: str = "bucket"):
        if rate <= 0 or per <= 0:
            raise ValueError("rate and per must be positive")
        self.rate = rate            # tokens added per `per` seconds
        self.per = per
        self.capacity = capacity if capacity is not None else rate
        self.tokens = self.capacity
        self.name = name
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        self.tokens = min(self.capacity, self.tokens + elapsed * (self.rate / self.per))
        self._updated = now

    async def acquire(self, amount: float = 1.0) -> None:
        if amount > self.capacity:
            raise ValueError(f"requested {amount} exceeds bucket capacity {self.capacity}")
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= amount:
                    self.tokens -= amount
                    return
                deficit = amount - self.tokens
                wait = deficit * (self.per / self.rate)
            await asyncio.sleep(wait)


class NullBucket:
    """No-op bucket used when no rate limit is configured."""

    async def acquire(self, amount: float = 1.0) -> None:  # noqa: D401
        return None


def bucket_for(rl: Optional[RateLimit], name: str):
    if rl is None:
        return NullBucket()
    return TokenBucket(rate=rl.requests, per=rl.per, capacity=rl.requests, name=name)


def token_bucket_for(rl: Optional[RateLimit], name: str):
    """Optional token-budget bucket (LLM TPM). Returns NullBucket if not set."""
    if rl is None or rl.tokens is None or rl.per_tokens is None:
        return NullBucket()
    return TokenBucket(rate=rl.tokens, per=rl.per_tokens, capacity=rl.tokens, name=name)
