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


#: Buckets are kept in a plain dict, and anything that varies the key varies
#: how many there are. Past this many, the ones that have refilled are dropped:
#: a full bucket allows exactly what an absent one does, so forgetting it costs
#: nothing and stops a stream of fresh keys growing the dict without end.
MAX_BUCKETS = 10_000


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

    @property
    def _full_after_s(self) -> float:
        return self._capacity / self._refill_per_s

    def _evict(self, now: float) -> None:
        """Forget buckets that have refilled. Caller holds the lock."""
        stale = now - self._full_after_s
        for key in [k for k, bucket in self._buckets.items() if bucket.updated <= stale]:
            del self._buckets[key]

    def _refilled(self, key: str, now: float) -> _Bucket:
        """The bucket for `key`, brought up to date. Caller holds the lock."""
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= MAX_BUCKETS:
                self._evict(now)
            bucket = _Bucket(tokens=self._capacity, updated=now)
            self._buckets[key] = bucket
        bucket.tokens = min(
            self._capacity, bucket.tokens + (now - bucket.updated) * self._refill_per_s
        )
        bucket.updated = now
        return bucket

    def check(self, key: str, cost: float = 1.0) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._refilled(key, now)
            if bucket.tokens < cost:
                return False
            bucket.tokens -= cost
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


def client_ip(request: Request) -> str:
    """Who the request says it is from.

    Behind a proxy this is the only way to tell two people apart, so it is worth
    reading — but anyone can write it, so it is never the only key a limit is
    counted against. See `peer_ip`.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return peer_ip(request)


def peer_ip(request: Request) -> str:
    """The address the connection came from, as far as the server is told.

    Worth counting against, because spoofing `X-Forwarded-For` gives a fresh
    `client_ip` every request and so a fresh bucket every time. Behind a proxy
    every visitor shares one of these, which is why the peer allowance is a
    multiple of the per-client one.

    One caveat, and it is the reason the username limit below exists: uvicorn
    rewrites this from `X-Forwarded-For` by default whenever the real peer is one
    it trusts, and it trusts loopback out of the box. Run it with
    `--no-proxy-headers` (as the Dockerfile and Makefile do) and this is the
    genuine address; leave the default and a caller on the same host can move it
    at will. So it is a useful key, not a trustworthy one.
    """
    return request.client.host if request.client else "unknown"


def enforce(limiter: RateLimiter, key: str, message: str) -> None:
    if not limiter.check(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)
