"""How many people used the site, counted without following anyone around.

This is the measurement that runs for everybody, everywhere, with nothing asked
of the reader — which is only defensible because of what it refuses to keep. No
cookie is set, nothing is written to the browser, no address or user agent ever
reaches the disk, and there is no row anywhere about any one person. What ends
up stored is four integers a day.

Uniqueness comes from a keyed hash of address and user agent under a salt made
in memory at midnight and thrown away at the next one. Two days therefore cannot
be joined, not by an attacker with the database and not by us: the key that
would link them no longer exists. It is a headcount, and it is designed so that
it can never quietly become anything else.

Microsoft Clarity, which does follow people around, is the separate thing that
asks first. See `frontend/src/analytics/consent.ts`.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from fastapi import Request

from .config import get_settings
from .db import session_scope
from .models import DailyCount
from .ratelimit import client_ip

log = logging.getLogger("oneread.visits")

#: Digests held for the day in progress. Past this the visitor count stops
#: rising and says so once in the log. 200k × ~100 bytes is roughly 20 MB, which
#: is the ceiling this puts on a day.
#:
#: A hard cap rather than an LRU, deliberately: evicting an old digest would let
#: a returning reader count twice, so the number would drift upward and look
#: fine. Stopping makes the same instance show a flat plateau, which is wrong in
#: a way somebody notices. An instance that genuinely reaches this wants a
#: HyperLogLog sketch — ±2% in about 12 KB at any size — not a bigger set.
MAX_TRACKED = 200_000

#: The paths the frontend actually routes: the library, and one entry. Mirrors
#: `entryFromPath` in `frontend/src/App.tsx`. The catch-all hands over a path
#: with no leading slash. Anything else still gets the shell exactly as before —
#: a scanner asking for /wp-login.php is served, it just isn't a visit.
_APP_ROUTE = re.compile(r"^(?:|e/[A-Za-z0-9]+/?)$")

#: Substrings that mean nobody is reading this. Crawlers, uptime probes, link
#: unfurlers and command-line tools all say so in the user agent, and a headcount
#: that includes them is not a headcount.
_AUTOMATED = (
    "bot", "crawl", "spider", "slurp", "curl/", "wget", "python-requests",
    "python-urllib", "httpx", "aiohttp", "okhttp", "go-http-client", "java/",
    "libwww", "headless", "phantomjs", "puppeteer", "playwright", "selenium",
    "lighthouse", "pagespeed", "monitor", "uptime", "pingdom", "statuscake",
    "facebookexternalhit", "embedly", "quora link preview", "preview",
    "fetcher", "scraper", "archiver", "validator", "feedburner", "rss",
)


def looks_automated(user_agent: str) -> bool:
    lowered = user_agent.lower()
    return any(token in lowered for token in _AUTOMATED)


@dataclass
class Pending:
    """Counts waiting to be written. Never holds anything about a person."""

    day: date
    views: int = 0
    #: Unique visitors so far today — a total, not a delta. See `VisitCounter`.
    visitors: int = 0
    signups: int = 0
    signins: int = 0


@dataclass
class _Day:
    day: date
    #: Made here and nowhere else. Never persisted, never logged, and pointedly
    #: not derived from `secret_key`, which lives on disk: a digest anyone could
    #: recompute would be a permanent identifier wearing a hash for a hat. At
    #: midnight this is replaced and the old value becomes unreachable, so
    #: yesterday's digests cannot be reproduced by anybody at all.
    salt: bytes = field(default_factory=lambda: secrets.token_bytes(16))
    seen: set[bytes] = field(default_factory=set)
    views: int = 0
    signups: int = 0
    signins: int = 0
    capped: bool = False

    def snapshot(self) -> Pending:
        return Pending(
            day=self.day,
            views=self.views,
            visitors=len(self.seen),
            signups=self.signups,
            signins=self.signins,
        )


def _utc_today() -> date:
    return datetime.now(UTC).date()


class VisitCounter:
    """Accumulates in memory, writes one row per day every `flush_interval_s`.

    Two accumulation rules, and the difference between them is the whole design:

    * `views`, `signups` and `signins` are deltas. They are taken and zeroed on
      each flush and added by the database, so a restart costs at most one
      interval.
    * `visitors` is the running total for the day, written with `max()`. Uniques
      cannot be added up — the set behind them is only cleared at midnight — and
      `max` makes the write idempotent, so a failed flush is simply retried by
      the next one.

    The honest cost of never persisting the salt: a restart mid-day loses the
    set, so that day's visitor count plateaus at whatever was last written and
    only resumes climbing once the fresh set overtakes it. Making it durable
    would mean writing per-visitor digests to disk, which is exactly the thing
    this file exists to avoid. Restarts are deploys; a dent in one day's number
    is the right price.
    """

    def __init__(
        self,
        *,
        flush_interval_s: float = 60.0,
        max_tracked: int = MAX_TRACKED,
        clock=_utc_today,
    ) -> None:
        self.flush_interval_s = flush_interval_s
        self.max_tracked = max_tracked
        self._clock = clock
        self._lock = threading.Lock()
        self._today = _Day(day=clock())
        # Days that ended before their last counts were written. The salt and
        # the digests are dropped at the rollover itself, so these are integers.
        self._finished: list[Pending] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # --- recording ----------------------------------------------------------

    def record_view(self, ip: str, user_agent: str) -> None:
        with self._lock:
            state = self._current()
            state.views += 1
            # blake2b takes a key directly, so there is no HMAC to construct.
            # The newline keeps ("1.2.3", "4x") from colliding with ("1.2", "34x").
            digest = hashlib.blake2b(
                f"{ip}\n{user_agent}".encode(), key=state.salt, digest_size=16
            ).digest()
            # Hashing inside the lock is deliberate: reading the salt out and
            # hashing outside leaves a window where a rollover swaps it and the
            # digest lands in the wrong day's set.
            if len(state.seen) < self.max_tracked:
                state.seen.add(digest)
            elif not state.capped:
                state.capped = True
                log.warning(
                    "more than %s visitors today; the count stops there", self.max_tracked
                )

    def record_signup(self) -> None:
        with self._lock:
            self._current().signups += 1

    def record_signin(self) -> None:
        with self._lock:
            self._current().signins += 1

    def _current(self) -> _Day:
        """Today's state, rolling over first if the date has moved. Lock held."""
        today = self._clock()
        if self._today.day != today:
            # Queued rather than dropped, so the finished day's last minute is
            # written under its own date. `snapshot` keeps the integers and
            # leaves the salt and the set to be collected.
            self._finished.append(self._today.snapshot())
            self._today = _Day(day=today)
        return self._today

    # --- writing ------------------------------------------------------------

    def _take(self) -> list[Pending]:
        with self._lock:
            batch = self._finished
            self._finished = []
            state = self._current()
            batch.append(state.snapshot())
            # Only the deltas reset. `seen` carries on until midnight, which is
            # what makes `visitors` a total rather than a sum of parts.
            state.views = state.signups = state.signins = 0
        return [item for item in batch if _worth_writing(item)]

    def _give_back(self, batch: list[Pending]) -> None:
        """Put unwritten counts back, so a failed flush loses nothing."""
        with self._lock:
            state = self._current()
            for item in batch:
                if item.day == state.day:
                    state.views += item.views
                    state.signups += item.signups
                    state.signins += item.signins
                else:
                    self._finished.append(item)

    def flush(self) -> None:
        batch = self._take()
        if not batch:
            return
        try:
            with session_scope() as session:
                for item in batch:
                    row = session.get(DailyCount, item.day)
                    if row is None:
                        # Spelled out rather than left to the column defaults,
                        # which SQLAlchemy only applies at INSERT — the `+=`
                        # below happens before that.
                        row = DailyCount(
                            day=item.day, views=0, visitors=0, signups=0, signins=0
                        )
                        session.add(row)
                    row.views += item.views
                    row.signups += item.signups
                    row.signins += item.signins
                    row.visitors = max(row.visitors, item.visitors)
        except Exception:
            # Usually a busy database. Silently eating a minute of counting
            # would make the numbers quietly wrong, so they go back in the pot.
            self._give_back(batch)
            log.warning("visit counts couldn't be written; they go in the next flush")

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="oneread-visits", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        # `wait` returns True the moment stop() sets the event, so shutdown
        # doesn't sit out the rest of the interval first.
        while not self._stop.wait(self.flush_interval_s):
            self.flush()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)
        # One last write, so a clean shutdown or a deploy loses nothing at all.
        self.flush()


def _worth_writing(item: Pending) -> bool:
    return bool(item.views or item.visitors or item.signups or item.signins)


def record_page_view(request: Request, path: str) -> None:
    """Count one document load, if that is really what this is.

    Only reached from the SPA fallback, which is already past the API routers,
    the public pages and the static files — so the filtering left to do is about
    who is asking rather than what for.
    """
    if request.method != "GET":
        # Starlette answers HEAD from every GET route, and that is what uptime
        # monitors send.
        return
    if not _APP_ROUTE.match(path):
        return
    user_agent = request.headers.get("user-agent", "")
    # A browser always sends one, so an empty user agent is a script.
    if not user_agent or looks_automated(user_agent):
        return
    if _is_prefetch(request):
        # The browser guessing at what might be wanted next, not somebody arriving.
        return
    get_counter().record_view(client_ip(request), user_agent)


def _is_prefetch(request: Request) -> bool:
    headers = request.headers
    return (
        "prefetch" in headers.get("sec-purpose", "")
        or "prerender" in headers.get("sec-purpose", "")
        or headers.get("purpose", "").lower() == "prefetch"
        or headers.get("x-moz", "").lower() == "prefetch"
    )


_counter: VisitCounter | None = None
_counter_lock = threading.Lock()


def get_counter() -> VisitCounter:
    global _counter
    with _counter_lock:
        if _counter is None:
            _counter = VisitCounter(
                flush_interval_s=get_settings().visits_flush_interval_s
            )
        return _counter


def set_counter(counter: VisitCounter | None) -> None:
    global _counter
    with _counter_lock:
        _counter = counter
