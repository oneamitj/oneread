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
from ..ratelimit import RateLimiter, client_ip, enforce
from ..schemas import Credentials, SessionOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

_login_limiter: RateLimiter | None = None


def login_limiter(settings: Annotated[Settings, Depends(get_settings)]) -> RateLimiter:
    global _login_limiter
    if _login_limiter is None:
        _login_limiter = RateLimiter(
            rate=settings.login_per_minute, per_seconds=60.0, burst=settings.login_per_minute
        )
    return _login_limiter


def reset_limiters() -> None:
    if _login_limiter is not None:
        _login_limiter.reset()


@router.post("/login", response_model=SessionOut, dependencies=[Depends(require_csrf)])
def login(
    payload: Credentials,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(login_limiter)],
) -> SessionOut:
    """One door for both cases: a new user id signs you up, a known one signs you in."""
    enforce(
        limiter,
        client_ip(request),
        "Too many sign-in attempts. Wait a minute and try again.",
    )

    user = session.scalar(select(User).where(User.username == payload.username))
    created = False

    if user is None:
        if not settings.allow_registration:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS)
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
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS
                ) from None
        else:
            created = True
    else:
        if not verify_password(user.password_hash, payload.password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS)
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


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user
