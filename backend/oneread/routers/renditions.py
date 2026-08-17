"""Readings: play them, stop them, download them, throw them away."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, require_csrf
from ..db import get_session
from ..models import LIVE_STATUSES, Entry, Rendition, pick_default, utcnow
from ..schemas import RenditionDetail
from ..subtitles import slugify, to_srt, to_vtt

router = APIRouter(prefix="/api/renditions", tags=["renditions"])

PLAYABLE = ("ready", "stopped")


def _owned(session: Session, rendition_id: str, user_id: str) -> Rendition:
    rendition = session.scalar(
        select(Rendition).where(
            Rendition.id == rendition_id, Rendition.user_id == user_id
        )
    )
    if rendition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No reading with that id.")
    return rendition


def _playable(session: Session, rendition_id: str, user_id: str) -> Rendition:
    rendition = _owned(session, rendition_id, user_id)
    if rendition.status not in PLAYABLE or not rendition.audio_path:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "There's no audio for this reading yet."
        )
    return rendition


def _filename(session: Session, rendition: Rendition) -> str:
    entry = session.get(Entry, rendition.entry_id)
    stem = slugify(entry.title if entry else "oneread")
    if rendition.scope == "sample":
        return f"{stem}-sample"
    if rendition.scope == "range":
        return f"{stem}-extract"
    return stem if rendition.complete else f"{stem}-partial"


def _is_default(session: Session, rendition: Rendition) -> bool:
    siblings = list(
        session.scalars(
            select(Rendition).where(Rendition.entry_id == rendition.entry_id)
        )
    )
    default = pick_default(siblings)
    return default is not None and default.id == rendition.id


@router.get("/{rendition_id}", response_model=RenditionDetail)
def get_rendition(
    rendition_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> RenditionDetail:
    rendition = _owned(session, rendition_id, user.id)
    out = RenditionDetail.model_validate(rendition)
    out.is_default = _is_default(session, rendition)
    return out


@router.post(
    "/{rendition_id}/stop",
    response_model=RenditionDetail,
    dependencies=[Depends(require_csrf)],
)
def stop_rendition(
    rendition_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> Rendition:
    """Ask the reader to stop.

    Whatever has been read is kept and stays playable. The worker checks between
    sentences, so it lands within a second or two rather than immediately.
    """
    rendition = _owned(session, rendition_id, user.id)
    if rendition.status not in LIVE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That reading has already finished."
        )
    rendition.stop_requested = True
    rendition.updated_at = utcnow()
    session.commit()
    session.refresh(rendition)
    return rendition


@router.delete("/{rendition_id}", status_code=204, dependencies=[Depends(require_csrf)])
def delete_rendition(
    rendition_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    rendition = _owned(session, rendition_id, user.id)
    if rendition.status in LIVE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Stop this reading before deleting it."
        )
    if _is_default(session, rendition):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is the recording the entry plays. Make another one first, or "
            "delete the whole entry.",
        )
    path = rendition.audio_path
    session.delete(rendition)
    session.commit()
    if path:
        Path(path).unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{rendition_id}/audio")
def get_audio(
    rendition_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    download: bool = False,
) -> FileResponse:
    rendition = _playable(session, rendition_id, user.id)
    path = Path(rendition.audio_path or "")
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The audio file is missing.")
    headers = {"Cache-Control": "private, max-age=3600"}
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="{_filename(session, rendition)}.wav"'
        )
    return FileResponse(path, media_type="audio/wav", headers=headers)


def _with_cues(session: Session, rendition_id: str, user_id: str) -> Rendition:
    rendition = _playable(session, rendition_id, user_id)
    if not rendition.cues:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This reading has no subtitle timings. Generate it again to get them.",
        )
    return rendition


@router.get("/{rendition_id}/subtitles.srt", response_class=PlainTextResponse)
def get_srt(
    rendition_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> PlainTextResponse:
    rendition = _with_cues(session, rendition_id, user.id)
    return PlainTextResponse(
        to_srt(rendition.cues or []),
        media_type="application/x-subrip; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_filename(session, rendition)}.srt"'
            )
        },
    )


@router.get("/{rendition_id}/subtitles.vtt", response_class=PlainTextResponse)
def get_vtt(
    rendition_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    download: bool = False,
) -> PlainTextResponse:
    rendition = _with_cues(session, rendition_id, user.id)
    headers = {}
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="{_filename(session, rendition)}.vtt"'
        )
    return PlainTextResponse(
        to_vtt(rendition.cues or []),
        media_type="text/vtt; charset=utf-8",
        headers=headers,
    )
