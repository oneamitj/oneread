"""Token-bucket rate limiting, held in process memory."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class RateLimiter:
    """`rate` refills over `per_seconds`; `burst` caps what can pile up."""

    rate: int
    per_seconds: float
    burst: int | None = None
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._capacity = float(self.burst or self.rate)
        self._refill_per_s = self.rate / self.per_seconds

    def check(self, key: str, cost: float = 1.0) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self._capacity, updated=now)
                self._buckets[key] = bucket
            elapsed = now - bucket.updated
            bucket.tokens = min(
                self._capacity, bucket.tokens + elapsed * self._refill_per_s
            )
            bucket.updated = now
            if bucket.tokens < cost:
                return False
            bucket.tokens -= cost
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(limiter: RateLimiter, key: str, message: str) -> None:
    if not limiter.check(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)
