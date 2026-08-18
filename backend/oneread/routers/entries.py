"""The library: create, search, edit, and ask for a reading."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import String, cast, func, or_, select, text
from sqlalchemy.orm import Session

from ..auth import CurrentUser, require_csrf
from ..config import Settings, get_settings
from ..db import get_session
from ..estimates import estimate as estimate_cost
from ..estimates import estimate_spans
from ..markdown_speech import to_speech
from ..models import LIVE_STATUSES, Entry, Rendition, pick_default, utcnow
from ..pacing import gap_after
from ..ratelimit import RateLimiter, enforce
from ..schemas import (
    EntryIn,
    EntryList,
    EntryOut,
    EntrySummary,
    EntryUpdate,
    EstimateOut,
    RenditionIn,
    RenditionOut,
    SegmentList,
    SegmentOut,
    SourceFile,
)
from ..security import content_disposition
from ..segmenter import BY_SENTENCE, READING_MODES, segment_spans
from ..subtitles import slugify
from ..worker import Worker, calibration_for, get_worker
from .uploads import claim, forget

router = APIRouter(prefix="/api/entries", tags=["entries"])

_generate_limiter: RateLimiter | None = None
_text_limiter: RateLimiter | None = None

# What makes a reading stale. Title and tags are just labels.
REGENERATING_FIELDS = ("body", "format", "voice", "lang", "speed")

EXCERPT_CHARS = 320


def generate_limiter(settings: Annotated[Settings, Depends(get_settings)]) -> RateLimiter:
    global _generate_limiter
    if _generate_limiter is None:
        _generate_limiter = RateLimiter(
            rate=settings.generate_per_hour,
            per_seconds=3600.0,
            burst=settings.generate_per_hour,
        )
    return _generate_limiter


def text_limiter(settings: Annotated[Settings, Depends(get_settings)]) -> RateLimiter:
    """For the routes that measure a document rather than read it.

    `segments` and `estimate` make no audio, so they escape the hourly
    generation limit — but both segment up to `max_text_chars` against one
    process. Loose enough that dragging the range picker is fine.
    """
    global _text_limiter
    if _text_limiter is None:
        _text_limiter = RateLimiter(
            rate=settings.text_per_minute, per_seconds=60.0, burst=settings.text_per_minute
        )
    return _text_limiter


TOO_MUCH_TEXT_WORK = "That's a lot of requests at once. Give it a moment."


def reset_limiters() -> None:
    for limiter in (_generate_limiter, _text_limiter):
        if limiter is not None:
            limiter.reset()


# --- lookups ----------------------------------------------------------------


def _owned(session: Session, entry_id: str, user_id: str) -> Entry:
    entry = session.scalar(
        select(Entry).where(Entry.id == entry_id, Entry.user_id == user_id)
    )
    if entry is None:
        # Same answer whether it never existed or belongs to someone else.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No entry with that id.")
    return entry


def active_full_reading(session: Session, entry_id: str) -> Rendition | None:
    """A full reading in flight. While one exists the entry is frozen."""
    return session.scalar(
        select(Rendition).where(
            Rendition.entry_id == entry_id,
            Rendition.scope == "full",
            Rendition.status.in_(LIVE_STATUSES),
            Rendition.stop_requested.is_(False),
        )
    )


def _require_unlocked(session: Session, entry_id: str) -> None:
    if active_full_reading(session, entry_id) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This entry is being read in full. Stop that first if you want to change it.",
        )


def _live_count(session: Session, user_id: str) -> int:
    return session.scalar(
        select(func.count(Rendition.id)).where(
            Rendition.user_id == user_id, Rendition.status.in_(LIVE_STATUSES)
        )
    ) or 0


def _check_queue_room(
    session: Session, user_id: str, settings: Settings, limiter: RateLimiter
) -> None:
    queued = _live_count(session, user_id)
    if queued >= settings.max_queued_per_user:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"You already have {queued} readings running. Wait for one to finish.",
        )
    enforce(
        limiter,
        user_id,
        "You've hit the hourly limit for generating audio. Try again later.",
    )


def _check_length(body: str, settings: Settings) -> None:
    if len(body) > settings.max_text_chars:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"That's {len(body)} characters. The limit for one entry is "
            f"{settings.max_text_chars}.",
        )


# --- search -----------------------------------------------------------------

_FTS_TOKEN = re.compile(r"[\w']+", re.UNICODE)


def _fts_query(raw: str) -> str:
    """Turn whatever the user typed into a safe FTS5 expression.

    Every token is quoted, so `AND`, `*`, `"` and friends are literal text. The
    last token gets a prefix star so search feels live as you type.
    """
    tokens = _FTS_TOKEN.findall(raw)
    if not tokens:
        return ""
    quoted = [f'"{token}"' for token in tokens[:-1]]
    quoted.append(f'"{tokens[-1]}"*')
    return " AND ".join(quoted)


def _search_ids(session: Session, user_id: str, raw_query: str) -> list[str] | None:
    """Ranked entry ids for a search, best first. None means "no search"."""
    expression = _fts_query(raw_query)
    if not expression:
        return None
    statement = text(
        "SELECT f.id FROM entries_fts f "
        "JOIN entries e ON e.id = f.id "
        "WHERE f.entries_fts MATCH :q AND e.user_id = :uid "
        "ORDER BY bm25(entries_fts, 0.0, 4.0, 1.0, 2.0)"
    )
    try:
        return list(session.scalars(statement, {"q": expression, "uid": user_id}))
    except Exception:
        # FTS index missing or the expression upset it. Fall back to LIKE.
        like = f"%{raw_query.strip()}%"
        rows = session.scalars(
            select(Entry.id)
            .where(
                Entry.user_id == user_id,
                or_(
                    Entry.title.like(like),
                    Entry.body.like(like),
                    cast(Entry.tags, String).like(like),
                ),
            )
            .order_by(Entry.created_at.desc())
        )
        return list(rows)


# --- listing ----------------------------------------------------------------

# Everything the grid draws, and nothing it doesn't. Pulling `body` and `spoken`
# here would mean shipping the whole library's text on every keystroke.
SUMMARY_COLUMNS = (
    Entry.id,
    Entry.title,
    func.substr(func.coalesce(Entry.spoken, Entry.body), 1, EXCERPT_CHARS + 1),
    func.length(Entry.body),
    Entry.format,
    Entry.tags,
    Entry.voice,
    Entry.lang,
    Entry.speed,
    Entry.source_name,
    Entry.source_type,
    Entry.source_bytes,
    Entry.created_at,
    Entry.updated_at,
)


def _as_default(reading: Rendition | None) -> RenditionOut | None:
    if reading is None:
        return None
    out = RenditionOut.model_validate(reading)
    out.is_default = True
    return out


def _source(name: str | None, media_type: str | None, size: int | None) -> SourceFile | None:
    if not name:
        return None
    return SourceFile(name=name, media_type=media_type or "", bytes=size or 0)


def _summary(row, renditions: list[Rendition]) -> EntrySummary:
    (
        entry_id, title, head, body_chars, fmt, tags, voice, lang, speed,
        source_name, source_type, source_bytes, created_at, updated_at,
    ) = row
    excerpt = head or ""
    if len(excerpt) > EXCERPT_CHARS:
        excerpt = excerpt[:EXCERPT_CHARS].rstrip() + "…"
    locked = any(
        r.scope == "full" and r.status in LIVE_STATUSES and not r.stop_requested
        for r in renditions
    )
    active = next((r for r in reversed(renditions) if r.status in LIVE_STATUSES), None)
    playable = pick_default(renditions)
    return EntrySummary(
        id=entry_id,
        title=title,
        excerpt=excerpt,
        body_chars=body_chars or 0,
        format=fmt,
        tags=tags or [],
        voice=voice,
        lang=lang,
        speed=speed,
        source=_source(source_name, source_type, source_bytes),
        locked=locked,
        rendition_count=len(renditions),
        playable=_as_default(playable),
        active=RenditionOut.model_validate(active) if active else None,
        created_at=created_at,
        updated_at=updated_at,
    )


@router.get("", response_model=EntryList)
def list_entries(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    q: Annotated[str, Query(max_length=200)] = "",
    tag: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI reads this shape
) -> EntryList:
    ranked = _search_ids(session, user.id, q)

    statement = select(*SUMMARY_COLUMNS).where(Entry.user_id == user.id)
    if ranked is not None:
        if not ranked:
            return EntryList(entries=[], tags=_all_tags(session, user.id), total=0)
        statement = statement.where(Entry.id.in_(ranked))
    rows = list(session.execute(statement.order_by(Entry.created_at.desc())))

    by_entry: dict[str, list[Rendition]] = {row[0]: [] for row in rows}
    if by_entry:
        for rendition in session.scalars(
            select(Rendition)
            .where(Rendition.entry_id.in_(by_entry))
            .order_by(Rendition.created_at)
        ):
            by_entry[rendition.entry_id].append(rendition)

    entries = [_summary(row, by_entry[row[0]]) for row in rows]

    if ranked is not None:
        order = {entry_id: i for i, entry_id in enumerate(ranked)}
        entries.sort(key=lambda e: order.get(e.id, len(order)))

    wanted = {t.casefold() for t in tag if t.strip()}
    if wanted:
        entries = [e for e in entries if wanted <= {t.casefold() for t in e.tags}]

    return EntryList(
        entries=entries, tags=_all_tags(session, user.id), total=len(entries)
    )


def _all_tags(session: Session, user_id: str) -> list[str]:
    seen: dict[str, str] = {}
    for tags in session.scalars(select(Entry.tags).where(Entry.user_id == user_id)):
        for tag in tags or []:
            seen.setdefault(tag.casefold(), tag)
    return sorted(seen.values(), key=str.casefold)


def _detail(session: Session, entry: Entry) -> EntryOut:
    out = EntryOut.model_validate(entry)
    # The file lives across four columns rather than one attribute, so it has
    # to be assembled here rather than picked up by from_attributes.
    out.source = _source(entry.source_name, entry.source_type, entry.source_bytes)
    out.locked = active_full_reading(session, entry.id) is not None
    default = pick_default(entry.renditions)
    for reading in out.renditions:
        reading.is_default = default is not None and reading.id == default.id
    return out


# --- entries ----------------------------------------------------------------


def _queue_reading(
    session: Session,
    entry: Entry,
    *,
    scope: str,
    mode: str = BY_SENTENCE,
    minutes: int | None = None,
    start: int = 0,
    end: int | None = None,
    voice: str | None = None,
    lang: str | None = None,
    speed: float | None = None,
    settings: Settings,
    worker: Worker,
) -> Rendition:
    limit_s = None
    if scope == "sample":
        limit_s = (minutes or settings.sample_minutes) * 60
    if scope != "range":
        start, end = 0, None

    # Settings chosen for this reading become the entry's defaults, because the
    # next one almost always wants the same thing.
    entry.voice = voice or entry.voice
    entry.lang = lang or entry.lang
    entry.speed = speed if speed is not None else entry.speed

    rendition = Rendition(
        entry_id=entry.id,
        user_id=entry.user_id,
        scope=scope,
        mode=mode,
        limit_s=limit_s,
        start_segment=start,
        end_segment=end,
        status="pending",
        voice=entry.voice,
        lang=entry.lang,
        speed=entry.speed,
        format=entry.format,
        chars=len(entry.body),
    )
    session.add(rendition)
    session.commit()
    session.refresh(rendition)
    worker.enqueue(rendition.id)
    return rendition


def _attach(
    session: Session,
    entry: Entry,
    upload_id: str,
    user_id: str,
    settings: Settings,
) -> None:
    """Keep the file an entry's text came out of, replacing any earlier one."""
    if entry.source_path:
        forget(session, entry.id)

    upload = claim(
        session,
        upload_id,
        user_id=user_id,
        entry_id=entry.id,
        title=entry.title,
        settings=settings,
    )
    entry.source_name = upload.filename
    entry.source_type = upload.media_type
    entry.source_bytes = upload.bytes
    entry.source_path = upload.path


@router.post("", response_model=EntryOut, status_code=201, dependencies=[Depends(require_csrf)])
def create_entry(
    payload: EntryIn,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(generate_limiter)],
    worker: Annotated[Worker, Depends(get_worker)],
) -> EntryOut:
    """Create the entry and read the first few minutes of it.

    Reading a book takes half an hour, and the first question is usually whether
    the voice is right. So creation always makes a sample; the full reading is a
    second, deliberate press.
    """
    _check_length(payload.body, settings)
    _check_queue_room(session, user.id, settings, limiter)

    entry = Entry(
        user_id=user.id,
        title=payload.title,
        body=payload.body,
        format=payload.format,
        tags=payload.tags,
        voice=payload.voice,
        lang=payload.lang,
        speed=payload.speed,
    )
    session.add(entry)
    session.flush()
    if payload.upload_id:
        _attach(session, entry, payload.upload_id, user.id, settings)
    session.commit()
    session.refresh(entry)

    _queue_reading(
        session, entry, scope="sample", minutes=payload.sample_minutes,
        settings=settings, worker=worker,
    )
    session.refresh(entry)
    return _detail(session, entry)


@router.get("/{entry_id}", response_model=EntryOut)
def get_entry(
    entry_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> EntryOut:
    return _detail(session, _owned(session, entry_id, user.id))


@router.put("/{entry_id}", response_model=EntryOut, dependencies=[Depends(require_csrf)])
def update_entry(
    entry_id: str,
    payload: EntryUpdate,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(generate_limiter)],
    worker: Annotated[Worker, Depends(get_worker)],
) -> EntryOut:
    _check_length(payload.body, settings)
    entry = _owned(session, entry_id, user.id)
    _require_unlocked(session, entry_id)

    changed = {
        field
        for field in REGENERATING_FIELDS
        if getattr(entry, field) != getattr(payload, field)
    }
    if changed:
        _check_queue_room(session, user.id, settings, limiter)

    entry.title = payload.title
    entry.body = payload.body
    entry.format = payload.format
    entry.tags = payload.tags
    entry.voice = payload.voice
    entry.lang = payload.lang
    entry.speed = payload.speed
    entry.updated_at = utcnow()
    if payload.upload_id:
        _attach(session, entry, payload.upload_id, user.id, settings)
    session.commit()

    if changed:
        # The old readings are still playable, but they're of the old text, so a
        # fresh sample goes in the queue the way it does on creation.
        _cancel_live(session, entry_id)
        _queue_reading(
            session, entry, scope="sample", minutes=payload.sample_minutes,
            settings=settings, worker=worker,
        )
    session.refresh(entry)
    return _detail(session, entry)


def _cancel_live(session: Session, entry_id: str) -> None:
    """Flag the live readings. The worker notices between sentences."""
    for rendition in session.scalars(
        select(Rendition).where(
            Rendition.entry_id == entry_id, Rendition.status.in_(LIVE_STATUSES)
        )
    ):
        rendition.stop_requested = True
    session.commit()


@router.delete("/{entry_id}", status_code=204, dependencies=[Depends(require_csrf)])
def delete_entry(
    entry_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    entry = _owned(session, entry_id, user.id)
    _require_unlocked(session, entry_id)
    paths = [
        r.audio_path
        for r in session.scalars(select(Rendition).where(Rendition.entry_id == entry_id))
        if r.audio_path
    ]
    forget(session, entry_id)
    session.delete(entry)
    session.commit()
    for path in paths:
        Path(path).unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- the files behind an entry ----------------------------------------------


@router.get("/{entry_id}/source")
def get_source(
    entry_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    """The file this entry's text was taken out of, exactly as uploaded."""
    entry = _owned(session, entry_id, user.id)
    path = Path(entry.source_path or "")
    if not entry.source_path or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no file behind this entry.")
    return FileResponse(
        path,
        media_type=entry.source_type or "application/octet-stream",
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": content_disposition(entry.source_name or path.name),
        },
    )


@router.get("/{entry_id}/text.txt", response_class=PlainTextResponse)
def get_spoken_text(
    entry_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> PlainTextResponse:
    """The words the voice reads, which for markdown is not the same document."""
    entry = _owned(session, entry_id, user.id)
    return PlainTextResponse(
        _spoken_of(entry),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": content_disposition(f"{slugify(entry.title)}.txt")},
    )


# --- readings ---------------------------------------------------------------


def _spoken_of(entry: Entry) -> str:
    return entry.spoken or to_speech(entry.body, entry.format)


@router.get("/{entry_id}/segments", response_model=SegmentList)
def entry_segments(
    entry_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    limiter: Annotated[RateLimiter, Depends(text_limiter)],
    speed: float | None = None,
) -> SegmentList:
    """The sentences the reader will produce, with a guess at when each lands.

    This is what the range picker is drawn from: a slider over sentences means a
    range can never start or end mid-sentence.
    """
    enforce(limiter, user.id, TOO_MUCH_TEXT_WORK)
    entry = _owned(session, entry_id, user.id)
    rates = calibration_for(session, user.id, entry_id)
    pieces = segment_spans(_spoken_of(entry), lang=entry.lang)

    cursor = 0.0
    out: list[SegmentOut] = []
    for index, piece in enumerate(pieces):
        one = estimate_spans([piece], speed=speed or entry.speed, calibration=rates)
        out.append(
            SegmentOut(
                i=index,
                text=piece.text,
                chars=len(piece.text),
                start_s=round(cursor, 2),
                end_s=round(cursor + one.audio_s, 2),
            )
        )
        if index < len(pieces) - 1:
            cursor += one.audio_s + gap_after(piece.ends)
        else:
            cursor += one.audio_s

    return SegmentList(segments=out, audio_s=round(cursor, 1), measured=rates.measured)


@router.get("/{entry_id}/estimate", response_model=EstimateOut)
def estimate_entry(
    entry_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(text_limiter)],
    scope: str = "full",
    mode: str = BY_SENTENCE,
    minutes: int | None = None,
    start: int = 0,
    end: int | None = None,
    speed: float | None = None,
) -> EstimateOut:
    """How long the audio will be, and how long the machine will take."""
    enforce(limiter, user.id, TOO_MUCH_TEXT_WORK)
    if mode not in READING_MODES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Pick one of {', '.join(READING_MODES)}.",
        )
    entry = _owned(session, entry_id, user.id)
    spoken = _spoken_of(entry)
    rates = calibration_for(session, user.id, entry_id, mode=mode)
    wanted = speed if speed is not None else entry.speed
    if scope == "range":
        # Estimated from the pieces themselves: rejoining them into text would
        # lose where the paragraphs ended, and with them the long pauses.
        pieces = segment_spans(spoken, lang=entry.lang)[start:end]
        if not pieces:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "That range doesn't cover any text.",
            )
        guess = estimate_spans(
            pieces,
            speed=wanted,
            calibration=rates,
            mode=mode,
            chunk_chars=settings.paragraph_chunk_chars,
        )
    else:
        guess = estimate_cost(
            spoken,
            lang=entry.lang,
            speed=wanted,
            calibration=rates,
            mode=mode,
            chunk_chars=settings.paragraph_chunk_chars,
        )
    if scope == "sample":
        guess = guess.capped((minutes or settings.sample_minutes) * 60)
    return EstimateOut(
        scope=scope,
        audio_s=guess.audio_s,
        wall_s=guess.wall_s,
        segments=guess.segments,
        characters=guess.characters,
        measured=guess.measured,
    )


@router.post(
    "/{entry_id}/renditions",
    response_model=RenditionOut,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def start_reading(
    entry_id: str,
    payload: RenditionIn,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(generate_limiter)],
    worker: Annotated[Worker, Depends(get_worker)],
) -> Rendition:
    entry = _owned(session, entry_id, user.id)
    if active_full_reading(session, entry_id) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This entry is already being read in full."
        )
    _check_queue_room(session, user.id, settings, limiter)
    return _queue_reading(
        session,
        entry,
        scope=payload.scope,
        mode=payload.mode,
        minutes=payload.minutes,
        start=payload.start,
        end=payload.end,
        voice=payload.voice,
        lang=payload.lang,
        speed=payload.speed,
        settings=settings,
        worker=worker,
    )
