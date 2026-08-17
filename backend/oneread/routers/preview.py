"""Hear a voice before committing to generating a whole entry."""

from __future__ import annotations

import hashlib
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from ..auth import CurrentUser, require_csrf
from ..config import Settings, get_settings
from ..markdown_speech import DEFAULT_FORMAT, FORMATS, to_speech
from ..ratelimit import RateLimiter, enforce
from ..schemas import MAX_SPEED, MIN_SPEED
from ..segmenter import segment_text
from ..tts_engine import VOICE_IDS, SynthesisError, TTSEngine, get_engine

log = logging.getLogger("oneread.preview")

router = APIRouter(prefix="/api/preview", tags=["preview"])

# Previews are tiny and identical settings come back constantly, so they're
# cached on disk. Past this many files the oldest go.
CACHE_LIMIT = 300

_preview_limiter: RateLimiter | None = None


def preview_limiter(settings: Annotated[Settings, Depends(get_settings)]) -> RateLimiter:
    global _preview_limiter
    if _preview_limiter is None:
        _preview_limiter = RateLimiter(
            rate=settings.preview_per_hour,
            per_seconds=3600.0,
            burst=max(10, settings.preview_per_hour // 4),
        )
    return _preview_limiter


def reset_limiters() -> None:
    if _preview_limiter is not None:
        _preview_limiter.reset()


class PreviewIn(BaseModel):
    voice: str
    lang: str = "en"
    speed: float = 1.05
    text: str = ""
    format: str = DEFAULT_FORMAT

    @field_validator("format")
    @classmethod
    def _format(cls, value: str) -> str:
        if value not in FORMATS:
            raise ValueError(f"Pick one of {', '.join(FORMATS)}, not {value!r}.")
        return value

    @field_validator("voice")
    @classmethod
    def _voice(cls, value: str) -> str:
        if value not in VOICE_IDS:
            raise ValueError(f"There is no voice called {value!r}.")
        return value

    @field_validator("speed")
    @classmethod
    def _speed(cls, value: float) -> float:
        if not MIN_SPEED <= value <= MAX_SPEED:
            raise ValueError(f"Speed goes from {MIN_SPEED} to {MAX_SPEED}.")
        return round(value, 2)


def sample_line(text: str, settings: Settings, fmt: str = DEFAULT_FORMAT) -> str:
    """One sentence of the reader's own text, so the preview is in their language."""
    cleaned = to_speech(text, fmt).strip()
    if not cleaned:
        return settings.preview_sample_text
    first = next(iter(segment_text(cleaned)), cleaned)
    if len(first) <= settings.preview_max_chars:
        return first
    # A single very long sentence: cut at the last space that fits.
    clipped = first[: settings.preview_max_chars]
    head, space, _ = clipped.rpartition(" ")
    return (head if space else clipped).rstrip(",;:") + "…"


def _prune(directory, keep: int) -> None:
    files = sorted(directory.glob("*.wav"), key=lambda f: f.stat().st_mtime)
    for stale in files[:-keep]:
        stale.unlink(missing_ok=True)


@router.post("", dependencies=[Depends(require_csrf)])
def preview(
    payload: PreviewIn,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(preview_limiter)],
    engine: Annotated[TTSEngine, Depends(get_engine)],
) -> FileResponse:
    enforce(limiter, user.id, "That's a lot of previews. Give it a minute.")

    line = sample_line(payload.text, settings, payload.format)
    fingerprint = hashlib.sha256(
        f"{line}\x00{payload.voice}\x00{payload.lang}\x00{payload.speed}"
        f"\x00{settings.tts_steps}".encode()
    ).hexdigest()[:32]
    path = settings.preview_dir / f"{fingerprint}.wav"

    headers = {"Cache-Control": "private, max-age=86400"}

    if not path.is_file():
        try:
            engine.synthesize_to_file(
                line,
                voice=payload.voice,
                lang=payload.lang,
                speed=payload.speed,
                out_path=path,
            )
        except SynthesisError as problem:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, str(problem)
            ) from problem
        except Exception as problem:
            log.exception("preview failed")
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Couldn't make that preview. Try a different voice.",
            ) from problem
        _prune(settings.preview_dir, CACHE_LIMIT)
    else:
        path.touch()  # keep the ones people actually use

    return FileResponse(path, media_type="audio/wav", headers=headers)


class SpokenText(BaseModel):
    text: str
    characters: int


class SpeechIn(BaseModel):
    text: str = ""
    format: str = DEFAULT_FORMAT

    @field_validator("format")
    @classmethod
    def _format(cls, value: str) -> str:
        if value not in FORMATS:
            raise ValueError(f"Pick one of {', '.join(FORMATS)}, not {value!r}.")
        return value


@router.post("/text", dependencies=[Depends(require_csrf)])
def spoken_text(payload: SpeechIn, user: CurrentUser) -> SpokenText:
    """What the reader will actually say. No synthesis, so it's free to call."""
    del user  # the session check is the point; the flattening is stateless
    spoken = to_speech(payload.text, payload.format)
    return SpokenText(text=spoken, characters=len(spoken))
