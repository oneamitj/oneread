"""Sign in, sign out, and who am I."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import (
    BAD_CREDENTIALS,
    CurrentUser,
    clear_session,
    hash_password,
    issue_session,
    needs_rehash,
    require_csrf,
    verify_password,
)
from ..config import Settings, get_settings
from ..db import get_session
from ..models import User
from ..ratelimit import RateLimiter, client_ip, enforce, peer_ip
from ..schemas import Credentials, SessionOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

_login_limiter: RateLimiter | None = None
_login_peer_limiter: RateLimiter | None = None
_login_failure_limiter: RateLimiter | None = None


def login_limiter(settings: Annotated[Settings, Depends(get_settings)]) -> RateLimiter:
    global _login_limiter
    if _login_limiter is None:
        _login_limiter = RateLimiter(
            rate=settings.login_per_minute, per_seconds=60.0, burst=settings.login_per_minute
        )
    return _login_limiter


def login_peer_limiter(settings: Annotated[Settings, Depends(get_settings)]) -> RateLimiter:
    """The same limit, counted against the address that opened the connection."""
    global _login_peer_limiter
    if _login_peer_limiter is None:
        rate = settings.login_per_minute * settings.login_peer_factor
        _login_peer_limiter = RateLimiter(rate=rate, per_seconds=60.0, burst=rate)
    return _login_peer_limiter


def login_failure_limiter(settings: Annotated[Settings, Depends(get_settings)]) -> RateLimiter:
    """Wrong passwords for one user id, counted wherever they come from."""
    global _login_failure_limiter
    if _login_failure_limiter is None:
        _login_failure_limiter = RateLimiter(
            rate=settings.login_failures_per_minute,
            per_seconds=60.0,
            burst=settings.login_failures_per_minute,
        )
    return _login_failure_limiter


def reset_limiters() -> None:
    for limiter in (_login_limiter, _login_peer_limiter, _login_failure_limiter):
        if limiter is not None:
            limiter.reset()


@router.post("/login", response_model=SessionOut, dependencies=[Depends(require_csrf)])
def login(
    payload: Credentials,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(login_limiter)],
    peer_limiter: Annotated[RateLimiter, Depends(login_peer_limiter)],
    failure_limiter: Annotated[RateLimiter, Depends(login_failure_limiter)],
) -> SessionOut:
    """One door for both cases: a new user id signs you up, a known one signs you in."""
    too_many = "Too many sign-in attempts. Wait a minute and try again."
    # Three keys, because the first two are only as good as the address they came
    # from. `client_ip` reads a header the caller writes. `peer_ip` is the
    # connection, which uvicorn will itself rewrite from that same header when
    # the peer is one it trusts. The user id being guessed at is neither: someone
    # after a particular account has to keep naming it.
    enforce(limiter, client_ip(request), too_many)
    enforce(peer_limiter, peer_ip(request), too_many)

    def refuse() -> HTTPException:
        """Turn one attempt away, and count it against the user id it named.

        Only wrong answers reach here, and the limit is consulted only when one
        does — so someone typing their own password correctly is never held up by
        the guesses other people have been making at their account. Past the
        limit the answer becomes 429 rather than another 401, and stays that way
        until the bucket refills.

        The password check above it costs real time by design, so the two address
        limits are what keep that work bounded; this bounds the guessing itself.
        """
        if not failure_limiter.check(payload.username):
            return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, too_many)
        return HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS)

    user = session.scalar(select(User).where(User.username == payload.username))
    created = False

    if user is None:
        if not settings.allow_registration:
            raise refuse()
        user = User(
            username=payload.username,
            password_hash=hash_password(payload.password),
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError:  # someone claimed the name a moment ago
            session.rollback()
            user = session.scalar(select(User).where(User.username == payload.username))
            if user is None or not verify_password(user.password_hash, payload.password):
                raise refuse() from None
        else:
            created = True
    else:
        if not verify_password(user.password_hash, payload.password):
            raise refuse()
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(payload.password)
            session.commit()

    issue_session(response, user, settings)
    return SessionOut(user=UserOut.model_validate(user), created=created)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
def logout(settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session(response, settings)
    return response


@router.post(
    "/revoke-sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
def revoke_sessions(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Sign out everywhere else.

    Signing out normally only clears the cookie in the browser doing it, which is
    the right thing when you're closing one tab and no help at all when a laptop
    has gone missing. Raising the token version leaves every cookie ever issued
    for this account failing its check — so a fresh one is issued here, and this
    device stays signed in while the rest are turned away.
    """
    user.token_version += 1
    session.commit()

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    issue_session(response, user, settings)
    return response


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
