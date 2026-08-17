"""Password hashing, signed session cookies, and the current-user dependency."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .config import Settings, get_settings
from .db import get_session
from .models import User

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
MIN_PASSWORD_LEN = 8

_hasher = PasswordHasher()

# Both a wrong password and an unknown user return this. Telling them apart
# would let anyone enumerate accounts.
BAD_CREDENTIALS = "That user id and password don't match an account."


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="oneread.session")


#: What a cookie predating `User.token_version` is taken to carry. Version 1 is
#: the baseline every account starts on, so reading an old cookie as version 1
#: keeps existing sessions working across the upgrade without weakening the
#: check: anything revoked afterwards is on 2 or above and no longer matches.
FIRST_TOKEN_VERSION = 1


def issue_session(response: Response, user: User, settings: Settings) -> None:
    token = _serializer(settings).dumps({"uid": user.id, "v": user.token_version})
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_max_age_s,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.cookie_name, path="/")


@dataclass(frozen=True)
class SessionCookie:
    """A cookie that verified: who it names, which generation, and how old it is."""

    uid: str
    version: int
    age_s: float


def open_session(request: Request, settings: Settings) -> SessionCookie | None:
    raw = request.cookies.get(settings.cookie_name)
    if not raw:
        return None
    try:
        data, issued = _serializer(settings).loads(
            raw, max_age=settings.session_max_age_s, return_timestamp=True
        )
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid")
    if not isinstance(uid, str):
        return None
    version = data.get("v")
    if not isinstance(version, int):
        version = FIRST_TOKEN_VERSION
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=UTC)
    return SessionCookie(
        uid=uid, version=version, age_s=(datetime.now(UTC) - issued).total_seconds()
    )


def read_session(request: Request, settings: Settings) -> str | None:
    cookie = open_session(request, settings)
    return cookie.uid if cookie is not None else None


def current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    cookie = open_session(request, settings)
    if cookie is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    user = session.scalar(select(User).where(User.id == cookie.uid))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    # A cookie from before the last revocation names a real user and carries a
    # good signature. The generation is what tells it apart from a current one.
    if cookie.version != user.token_version:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "That session was signed out. Sign in again."
        )
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_csrf(request: Request) -> None:
    """Custom-header CSRF guard.

    A cross-site form post cannot set this header, and a cross-site fetch that
    tries to would be stopped by preflight. Cheap, and no token to manage.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get("x-requested-with") != "oneread":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This request is missing its origin header."
        )


class SessionRefreshMiddleware(BaseHTTPMiddleware):
    """Keep an active session alive.

    A cookie is stamped when it's issued, so left alone it would expire a month
    after sign-in even for someone using the app daily. This re-stamps one that
    is getting on, which is cheap: no database, just a fresh signature.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        settings = self.settings
        cookie = open_session(request, settings)
        if cookie is None or cookie.age_s < settings.session_refresh_after_s:
            return response
        # Signing out sets its own cookie on the way past. Don't undo it.
        if any(
            header.startswith(f"{settings.cookie_name}=")
            for header in response.headers.getlist("set-cookie")
        ):
            return response
        response.set_cookie(
            settings.cookie_name,
            # The generation is carried through as it was found, so renewing a
            # cookie still costs no database access. A revoked one is turned
            # away by `current_user` on the same request either way.
            _serializer(settings).dumps({"uid": cookie.uid, "v": cookie.version}),
            max_age=settings.session_max_age_s,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        return response
