"""Reading a file, so its words can become an entry.

Extraction is guesswork in places — a deck has no reading order, a PDF has no
paragraphs — so the words go back to the editor first and nothing is saved until
Create is pressed. Meanwhile the file waits in `staging_dir` with an `Upload`
row tracking it: claiming moves it next to the entry, and the unclaimed are
swept after a day.
"""

from __future__ import annotations

import logging
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, require_csrf
from ..config import Settings, get_settings
from ..db import get_session
from ..extract import UnreadableFile, extract, media_type_for
from ..models import Upload, utcnow
from ..ratelimit import RateLimiter, enforce
from ..schemas import UploadOut
from ..subtitles import slugify

log = logging.getLogger("oneread.uploads")

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

#: How long an unclaimed file waits before it's swept.
STAGING_LIFE = timedelta(days=1)

_upload_limiter: RateLimiter | None = None


def upload_limiter(settings: Annotated[Settings, Depends(get_settings)]) -> RateLimiter:
    global _upload_limiter
    if _upload_limiter is None:
        _upload_limiter = RateLimiter(
            rate=settings.upload_per_hour,
            per_seconds=3600.0,
            burst=max(5, settings.upload_per_hour // 4),
        )
    return _upload_limiter


def reset_limiters() -> None:
    if _upload_limiter is not None:
        _upload_limiter.reset()


def _read_body(handle: UploadFile, cap: int) -> bytes:
    """Pull the file off the wire, giving up the moment it's too big.

    Reading it whole and then measuring holds a 2 GB request in memory before
    refusing it, which is the attack rather than the defence.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = handle.file.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"That file is bigger than {cap // (1024 * 1024)} MB, which is the limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def sweep(session: Session) -> int:
    """Throw away files that were read but never turned into an entry."""
    cutoff = utcnow() - STAGING_LIFE
    stale = session.scalars(
        select(Upload).where(Upload.entry_id.is_(None), Upload.created_at < cutoff)
    ).all()
    for upload in stale:
        Path(upload.path).unlink(missing_ok=True)
    if stale:
        session.execute(delete(Upload).where(Upload.id.in_([u.id for u in stale])))
        session.commit()
    return len(stale)


@router.post("", response_model=UploadOut, status_code=201, dependencies=[Depends(require_csrf)])
def read_file(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(upload_limiter)],
    file: Annotated[UploadFile, File()],
) -> UploadOut:
    enforce(limiter, user.id, "That's a lot of files at once. Give it a few minutes.")

    name = Path(file.filename or "").name or "document"
    data = _read_body(file, settings.max_upload_bytes)

    try:
        found = extract(
            data,
            name,
            limit=settings.max_text_chars,
            max_unzipped=settings.max_unzipped_bytes,
            soffice=settings.soffice_path,
        )
    except UnreadableFile as problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(problem)) from None

    sweep(session)

    upload = Upload(
        user_id=user.id,
        filename=name,
        # The extension decides, not the browser: a browser that doesn't
        # recognise a type sends application/octet-stream, and that's what
        # would come back on the download and make it a mystery file.
        media_type=media_type_for(name),
        bytes=len(data),
        kind=found.kind,
        format=found.format,
    )
    session.add(upload)
    session.flush()

    room = settings.staging_dir / user.id
    room.mkdir(parents=True, exist_ok=True)
    path = room / f"{upload.id}{Path(name).suffix.lower()}"
    path.write_bytes(data)
    upload.path = str(path)
    session.commit()

    log.info("read %s (%s bytes) for %s", name, len(data), user.id)

    return UploadOut(
        id=upload.id,
        filename=name,
        media_type=upload.media_type,
        bytes=upload.bytes,
        kind=found.kind,
        format=found.format,
        title=found.title,
        text=found.text,
        truncated=found.truncated,
    )


@router.delete("/{upload_id}", status_code=204, dependencies=[Depends(require_csrf)])
def discard(
    upload_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> None:
    """Drop a file the editor decided against, rather than wait for the sweep."""
    upload = session.get(Upload, upload_id)
    if upload is None or upload.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That file is gone.")
    if upload.entry_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That file belongs to an entry now. Delete the entry to remove it.",
        )
    Path(upload.path).unlink(missing_ok=True)
    session.delete(upload)
    session.commit()


# --- claiming, used by the entry routes --------------------------------------


def claim(
    session: Session,
    upload_id: str,
    *,
    user_id: str,
    entry_id: str,
    title: str,
    settings: Settings,
) -> Upload:
    """Move a staged file next to the entry it belongs to.

    Raises the same 404 for somebody else's upload as for one that never
    existed, so a stranger's id can't be confirmed by the error.
    """
    upload = session.get(Upload, upload_id)
    if upload is None or upload.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That file is gone. Upload it again.")
    if upload.entry_id and upload.entry_id != entry_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "That file is already on another entry.")

    suffix = Path(upload.filename).suffix.lower()
    room = settings.upload_dir / user_id / entry_id
    room.mkdir(parents=True, exist_ok=True)
    destination = room / f"{slugify(title, fallback='document')}{suffix}"

    staged = Path(upload.path)
    if staged.is_file():
        shutil.move(str(staged), str(destination))
    elif not destination.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That file is gone. Upload it again.")

    upload.path = str(destination)
    upload.entry_id = entry_id
    return upload


def forget(session: Session, entry_id: str) -> None:
    """Remove an entry's stored source file and the row pointing at it."""
    for upload in session.scalars(select(Upload).where(Upload.entry_id == entry_id)).all():
        Path(upload.path).unlink(missing_ok=True)
        session.delete(upload)
