"""Engine, session factory, and the FTS5 index that powers search."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

log = logging.getLogger("oneread.db")

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _apply_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


# The FTS table mirrors the searchable columns of `entries`. `id` is stored but
# not indexed so a match can be joined straight back to the row it came from.
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    id UNINDEXED,
    title,
    body,
    tags,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
        INSERT INTO entries_fts(id, title, body, tags)
        VALUES (new.id, new.title, new.body, new.tags);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
        DELETE FROM entries_fts WHERE id = old.id;
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
        DELETE FROM entries_fts WHERE id = old.id;
        INSERT INTO entries_fts(id, title, body, tags)
        VALUES (new.id, new.title, new.body, new.tags);
    END;
    """,
]


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine_for(settings.sqlalchemy_url)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def create_engine_for(url: str) -> Engine:
    from sqlalchemy import create_engine

    engine = create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _apply_pragmas)
    return engine


def init_db(engine: Engine | None = None) -> Engine:
    """Create tables, the FTS index, and its sync triggers."""
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            _add_missing_columns(conn, table)
        _move_audio_into_renditions(conn)
        _backfill_coverage(conn)
        conn.execute(text(FTS_SCHEMA))
        for trigger in FTS_TRIGGERS:
            conn.execute(text(trigger))
        # Backfill anything written before the index existed.
        conn.execute(
            text(
                "INSERT INTO entries_fts(id, title, body, tags) "
                "SELECT id, title, body, tags FROM entries "
                "WHERE id NOT IN (SELECT id FROM entries_fts)"
            )
        )
    return engine


def _add_missing_columns(conn, table) -> None:
    """Bring an older database up to the current model.

    SQLite can add a column to a populated table without rewriting it, and the
    app only ever gains columns, so this covers every schema change so far
    without dragging in a migration tool.
    """
    from sqlalchemy.schema import CreateColumn

    present = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table.name})")}
    if not present:
        return  # table was just created, so it already matches

    for column in table.columns:
        if column.name in present:
            continue
        ddl = str(CreateColumn(column).compile(conn.engine))
        default = column.default.arg if column.default is not None else None
        if not column.nullable and not callable(default):
            literal = "NULL" if default is None else repr(default).replace('"', "'")
            ddl = f"{ddl} DEFAULT {literal}"
        log.info("adding column %s.%s", table.name, column.name)
        conn.exec_driver_sql(f"ALTER TABLE {table.name} ADD COLUMN {ddl}")


# Columns that used to hang off `entries`, before a document could have more
# than one reading. They are moved into `renditions` and then dropped, because
# several were NOT NULL and would reject every new row.
LEGACY_ENTRY_COLUMNS = (
    "status", "progress", "audio_path", "duration_s", "cues", "error", "revision",
)


def _move_audio_into_renditions(conn) -> None:
    columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(entries)")}
    if "audio_path" not in columns:
        return  # already a current database

    moved = conn.exec_driver_sql(
        """
        INSERT INTO renditions (
            id, entry_id, user_id, scope, limit_s, status, stop_requested, complete,
            segments_done, segments_total, audio_path, duration_s, cues, error,
            chars, spoken_chars, wall_s, voice, lang, speed, format,
            created_at, updated_at
        )
        SELECT
            lower(hex(randomblob(16))), e.id, e.user_id, 'full', NULL,
            CASE WHEN e.status = 'ready' THEN 'ready' ELSE 'failed' END,
            0, CASE WHEN e.status = 'ready' THEN 1 ELSE 0 END,
            0, 0, e.audio_path, e.duration_s, e.cues, e.error,
            length(e.body), 0, NULL, e.voice, e.lang, e.speed, e.format,
            e.created_at, e.updated_at
        FROM entries e
        WHERE e.audio_path IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM renditions r WHERE r.entry_id = e.id)
        """
    ).rowcount
    if moved:
        log.info("moved %d existing recording(s) into renditions", moved)

    for index_name in ("ix_entries_status",):
        conn.exec_driver_sql(f"DROP INDEX IF EXISTS {index_name}")
    for column in LEGACY_ENTRY_COLUMNS:
        if column in columns:
            conn.exec_driver_sql(f"ALTER TABLE entries DROP COLUMN {column}")
    log.info("dropped the old single-recording columns from entries")


def _backfill_coverage(conn) -> None:
    """Fill in what older readings never recorded: coverage and opening line.

    Both come out of data already on disk, so a library made before recordings
    tracked this still draws its bars instead of waiting to be read again.
    """
    from .markdown_speech import to_speech
    from .segmenter import segment_text

    rows = conn.exec_driver_sql(
        "SELECT r.id, r.cues, e.body, e.format, e.spoken, e.lang "
        "FROM renditions r JOIN entries e ON e.id = r.entry_id "
        "WHERE r.document_segments = 0 AND r.cues IS NOT NULL"
    ).fetchall()
    if not rows:
        return

    sizes: dict[tuple[str, str], int] = {}
    for rendition_id, raw_cues, body, fmt, spoken, lang in rows:
        try:
            cues = json.loads(raw_cues) if isinstance(raw_cues, str) else raw_cues
        except (TypeError, ValueError):
            continue
        if not cues:
            continue

        text = spoken or to_speech(body or "", fmt or "plain")
        key = (text, lang or "en")
        if key not in sizes:
            sizes[key] = len(segment_text(text, lang=lang))
        conn.exec_driver_sql(
            "UPDATE renditions SET document_segments = ?, opening = ? WHERE id = ?",
            (sizes[key], str(cues[0].get("text", ""))[:160], rendition_id),
        )
    log.info("filled in coverage for %d earlier reading(s)", len(rows))


def set_session_factory(factory: sessionmaker[Session]) -> None:
    """Used by the test suite to point the app at a throwaway database."""
    global _SessionLocal
    _SessionLocal = factory


def session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()
