"""Things the frontend needs to draw its pickers, plus the health probe."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings
from ..extract import accepted
from ..markdown_speech import FORMATS
from ..schemas import Meta
from ..tts_engine import MAX_SPEED, MIN_SPEED, VOICES, get_engine

router = APIRouter(tags=["meta"])

# Falls back to the full published list if the model hasn't loaded yet, so the
# first page view never has to wait on ONNX.
_FALLBACK_LANGUAGES = [
    "ar", "bn", "de", "en", "es", "fa", "fr", "he", "hi", "id", "it", "ja",
    "ko", "ms", "nl", "pl", "pt", "ru", "sw", "ta", "th", "tr", "uk", "ur",
    "vi", "zh", "na",
]


@router.get("/api/meta", response_model=Meta)
def meta(settings: Annotated[Settings, Depends(get_settings)]) -> Meta:
    engine = get_engine()
    try:
        languages = engine.languages()
    except Exception:
        languages = _FALLBACK_LANGUAGES
    return Meta(
        voices=VOICES,
        languages=languages,
        default_voice=settings.default_voice,
        default_lang=settings.default_lang,
        default_speed=settings.default_speed,
        max_text_chars=settings.max_text_chars,
        min_speed=MIN_SPEED,
        max_speed=MAX_SPEED,
        formats=list(FORMATS),
        sample_minutes=settings.sample_minutes,
        sample_minute_choices=list(settings.sample_minute_choices),
        allow_registration=settings.allow_registration,
        upload_types=accepted(),
        max_upload_bytes=settings.max_upload_bytes,
    )


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    return {"status": "ok"}
