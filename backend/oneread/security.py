"""Headers, body limits, and the other things that keep the app boring to attack."""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The frontend is a plain Vite bundle with inline styles from the design tokens,
# so 'unsafe-inline' stays on styles only. No inline scripts, no remote origins.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def content_disposition(filename: str, *, fallback: str = "download") -> str:
    """An attachment header that survives whatever the name turns out to contain.

    Filenames come from uploads and entry titles, so they arrive holding quotes,
    semicolons and anything else a person can type. Interpolated straight into
    the header, a quote ends the quoted string early and the rest of the name
    becomes parameters — the browser then saves the file under a truncated name.

    So the quoted form is reduced to characters that can't do that, and the
    original is carried alongside in the RFC 5987 form when the two differ.
    A name that was already plain comes back exactly as it went in.
    """
    safe = _UNSAFE_IN_FILENAME.sub("_", filename).strip("._") or fallback
    header = f'attachment; filename="{safe}"'
    if safe != filename:
        header += f"; filename*=UTF-8''{quote(filename, safe='')}"
    return header


class BodyLimitMiddleware:
    """Refuse a request body past `limit` bytes, before anything buffers it.

    Uploads are read in chunks and cut off at their own ceiling, but a JSON body
    is parsed whole before any route sees it, so `max_text_chars` is checked only
    once the megabytes are already in memory. This is raw ASGI rather than
    `BaseHTTPMiddleware` on purpose: the latter reads the body itself, which is
    the thing being guarded against.

    `Content-Length` is honoured where it's given and counted where it isn't, so
    a chunked request can't slip past by leaving the header off.
    """

    def __init__(self, app: ASGIApp, *, limit: int, upload_limit: int) -> None:
        self.app = app
        self.limit = limit
        self.upload_limit = upload_limit

    def _limit_for(self, path: str) -> int:
        return self.upload_limit if path.startswith("/api/uploads") else self.limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        cap = self._limit_for(scope.get("path", ""))
        declared = _content_length(scope)
        if declared is not None and declared > cap:
            await _too_large(cap, scope, receive, send)
            return

        # A request that leaves the length off is counted as it arrives instead.
        state = {"seen": 0, "refused": False}

        async def counted() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                state["seen"] += len(message.get("body", b""))
                if state["seen"] > cap:
                    state["refused"] = True
                    # Cutting the body short is what stops the read; the answer
                    # comes from here rather than from whatever the truncated
                    # body makes the route think happened.
                    return {"type": "http.disconnect"}
            return message

        wrapped = _Sender(send, lambda: bool(state["refused"]))
        try:
            await self.app(scope, counted, wrapped)
        except Exception:
            # A route part-way through reading a body it will never get is a
            # disconnect as far as it knows. That's ours to answer, not a fault.
            if not state["refused"]:
                raise
        if state["refused"] and not wrapped.started:
            await _too_large(cap, scope, receive, send)


class _Sender:
    """Passes responses through, unless the body was refused while one was forming.

    A truncated body makes the route below fail in its own way — a parse error,
    a disconnect — and answer accordingly. That answer is wrong twice over: wrong
    status, and shaped by whichever layer produced it rather than by this app's
    one error contract. So once the limit is passed, whatever it was about to say
    is dropped on the floor and `_too_large` speaks instead.
    """

    def __init__(self, send: Send, refused: Callable[[], bool]) -> None:
        self._send = send
        self._refused = refused
        self._swallowing = False
        self.started = False

    async def __call__(self, message: Message) -> None:
        # Only a response that hasn't begun can be replaced. One already on its
        # way out is finished rather than truncated: half a response is worse
        # than a wrong status.
        if message["type"] == "http.response.start" and not self.started and self._refused():
            self._swallowing = True
        if self._swallowing:
            return
        if message["type"] == "http.response.start":
            self.started = True
        await self._send(message)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _in_units(size: int) -> str:
    """A ceiling as the person who set it would say it, MB or KB."""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.0f} MB"
    return f"{size / 1024:.0f} KB"


async def _too_large(cap: int, scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse(
        {"message": f"That request is bigger than {_in_units(cap)}, which is the limit."},
        status_code=413,
    )
    await response(scope, receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("Content-Security-Policy", CSP)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if self.hsts:
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
