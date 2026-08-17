"""Database models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """Timestamps that stay in UTC, and admit it.

    SQLite has no timezone type, so a plain DateTime column hands back a naive
    value. Serialized without an offset, a browser reads it as local time and
    every "4 minutes ago" is wrong by the machine's offset. This normalises on
    the way in and re-attaches UTC on the way out, so what leaves the API always
    carries `+00:00`.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Stamped into every session cookie. Session tokens are signed rather than
    # stored, so there is otherwise nothing to delete when one needs to stop
    # working: raising this number is what makes the old ones stop verifying.
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    entries: Mapped[list[Entry]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Entry(Base):
    """A document. The audio for it lives in one or more renditions."""

    __tablename__ = "entries"
    __table_args__ = (Index("ix_entries_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    # How to read `body`: "plain" takes it literally, "markdown" parses it first.
    format: Mapped[str] = mapped_column(String(16), default="plain")
    # The flattened text, cached from the last time it was read out.
    spoken: Mapped[str | None] = mapped_column(Text, default=None)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Where the text came from, when it came from a file. The file itself is
    # kept: extraction is a one-way trip, and being able to open the original
    # is the only way to check what the reading left out.
    source_name: Mapped[str | None] = mapped_column(String(255), default=None)
    source_type: Mapped[str | None] = mapped_column(String(128), default=None)
    source_bytes: Mapped[int | None] = mapped_column(Integer, default=None)
    source_path: Mapped[str | None] = mapped_column(String(512), default=None)

    # Defaults for the next rendition. Each rendition keeps its own copy.
    voice: Mapped[str] = mapped_column(String(16), default="F1")
    lang: Mapped[str] = mapped_column(String(8), default="en")
    speed: Mapped[float] = mapped_column(Float, default=1.05)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="entries")
    renditions: Mapped[list[Rendition]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="Rendition.created_at",
    )


# A rendition is one attempt at reading a document out loud. A short "sample"
# covers the first few minutes; a "full" one goes to the end. Stopping either
# one keeps whatever was read up to that point, so the work isn't wasted.
SCOPES = ("sample", "range", "full")
LIVE_STATUSES = ("pending", "processing")


class Rendition(Base):
    __tablename__ = "renditions"
    __table_args__ = (Index("ix_renditions_entry_created", "entry_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("entries.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(32), index=True)

    scope: Mapped[str] = mapped_column(String(16), default="sample")
    # Where a sample stops, in seconds of audio. Null means read to the end.
    limit_s: Mapped[int | None] = mapped_column(Integer, default=None)
    # For a range: the half-open span of sentences that was read.
    start_segment: Mapped[int] = mapped_column(Integer, default=0)
    end_segment: Mapped[int | None] = mapped_column(Integer, default=None)

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    complete: Mapped[bool] = mapped_column(Boolean, default=False)

    segments_done: Mapped[int] = mapped_column(Integer, default=0)
    segments_total: Mapped[int] = mapped_column(Integer, default=0)
    # Sentences in the whole document, so a reading can say what share it covers.
    document_segments: Mapped[int] = mapped_column(Integer, default=0)
    # The first sentence. Two "first minute" recordings look identical without it.
    opening: Mapped[str | None] = mapped_column(String(200), default=None)

    audio_path: Mapped[str | None] = mapped_column(String(512), default=None)
    duration_s: Mapped[float | None] = mapped_column(Float, default=None)
    cues: Mapped[list[dict] | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    # What was read, and what it cost. Used to estimate the next one.
    chars: Mapped[int] = mapped_column(Integer, default=0)
    spoken_chars: Mapped[int] = mapped_column(Integer, default=0)
    wall_s: Mapped[float | None] = mapped_column(Float, default=None)

    # The settings in force when this was generated, not the entry's current ones.
    voice: Mapped[str] = mapped_column(String(16), default="F1")
    lang: Mapped[str] = mapped_column(String(8), default="en")
    speed: Mapped[float] = mapped_column(Float, default=1.05)
    format: Mapped[str] = mapped_column(String(16), default="plain")

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow
    )

    entry: Mapped[Entry] = relationship(back_populates="renditions")

    @property
    def progress(self) -> float:
        if self.status == "ready":
            return 1.0
        if not self.segments_total:
            return 0.0
        return round(min(1.0, self.segments_done / self.segments_total), 4)


class Upload(Base):
    """A file that has been read, waiting to be attached to an entry.

    Extraction hands the text back to the editor before anything is saved, so
    the file itself sits in limbo meanwhile. Claimed uploads point at their
    entry; the rest are swept once they're a day old.
    """

    __tablename__ = "uploads"
    __table_args__ = (Index("ix_uploads_unclaimed", "entry_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(128), default="")
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(String(512), default="")
    kind: Mapped[str] = mapped_column(String(16), default="")
    format: Mapped[str] = mapped_column(String(16), default="plain")

    entry_id: Mapped[str | None] = mapped_column(String(32), default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


def pick_default(renditions: list[Rendition]) -> Rendition | None:
    """The reading an entry leads with.

    The newest complete reading wins; failing that, whichever covers the most.
    It's what a card plays and the one that can't be deleted, so an entry with
    audio never loses all of it by accident.
    """
    playable = [
        r for r in renditions if r.status in ("ready", "stopped") and r.audio_path
    ]
    if not playable:
        return None
    return max(
        playable,
        key=lambda r: (r.complete, 0.0 if r.complete else (r.duration_s or 0.0), r.created_at),
    )
