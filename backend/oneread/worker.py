"""Background reading: one queue, one worker thread, rendition rows as the log."""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from sqlalchemy import select, update

from .config import get_settings
from .db import session_scope
from .estimates import Calibration
from .markdown_speech import to_speech
from .models import Entry, Rendition, utcnow
from .segmenter import BY_SENTENCE
from .tts_engine import DISCARD, KEEP, Cancelled, SynthesisError, TTSEngine, get_engine

log = logging.getLogger("oneread.worker")

_STOP = object()


def audio_path_for(user_id: str, entry_id: str, rendition_id: str) -> Path:
    return get_settings().audio_dir / user_id / entry_id / f"{rendition_id}.wav"


def calibration_for(
    session,
    user_id: str,
    entry_id: str | None = None,
    mode: str = BY_SENTENCE,
) -> Calibration:
    """Learn the machine's pace from finished work, newest first."""
    statement = (
        select(Rendition)
        .where(
            Rendition.user_id == user_id,
            Rendition.status.in_(("ready", "stopped")),
            Rendition.wall_s.is_not(None),
        )
        .order_by(Rendition.created_at.desc())
        .limit(8)
    )
    rows = list(session.scalars(statement))
    # Prefer this entry's own history, and a reading cut up the same way: same
    # text, same voice, same pauses, closest match.
    rows.sort(key=lambda r: (r.entry_id != entry_id, r.mode != mode))
    for rendition in rows:
        learned = Calibration.from_rendition(
            spoken_chars=rendition.spoken_chars,
            duration_s=rendition.duration_s or 0.0,
            wall_s=rendition.wall_s or 0.0,
            speed=rendition.speed,
            segments=rendition.segments_done,
            mode=rendition.mode,
        )
        if learned is not None:
            return learned
    return Calibration()


class Worker:
    def __init__(self, engine: TTSEngine | None = None) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._engine = engine
        self._idle = threading.Event()
        self._idle.set()
        self._stopping = threading.Event()
        # A book takes long enough that writing progress on every sentence would
        # be pure write amplification. Once a second is plenty for a poll loop.
        self.progress_interval_s = 1.0

    @property
    def engine(self) -> TTSEngine:
        return self._engine or get_engine()

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="oneread-tts", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        if not self._thread:
            return
        # Tell a running job to put its pen down. Whatever it has read by then is
        # kept, because on a long document that can be half an hour of audio.
        self._stopping.set()
        self._queue.put(_STOP)
        self._thread.join(timeout=timeout)
        self._thread = None
        self._stopping.clear()

    def enqueue(self, rendition_id: str) -> None:
        self._idle.clear()
        self._queue.put(rendition_id)

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Used by tests; the app itself never blocks on this."""
        return self._idle.wait(timeout)

    def requeue_unfinished(self) -> int:
        """Pick up jobs that were queued but never started when we went down."""
        with session_scope() as session:
            ids = list(
                session.scalars(
                    select(Rendition.id).where(
                        Rendition.status == "pending", Rendition.stop_requested.is_(False)
                    )
                )
            )
        for rendition_id in ids:
            self.enqueue(rendition_id)
        if ids:
            log.info("requeued %d unfinished reading(s)", len(ids))
        return len(ids)

    # --- the loop -----------------------------------------------------------

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                self._process(str(item))
            except Exception:  # a bad job must not take the worker down
                log.exception("reading failed outside its own error handling")
            finally:
                self._queue.task_done()
                if self._queue.empty():
                    self._idle.set()

    def _process(self, rendition_id: str) -> None:
        with session_scope() as session:
            rendition = session.get(Rendition, rendition_id)
            if rendition is None or rendition.status != "pending":
                return
            if rendition.stop_requested:
                rendition.status = "stopped"
                rendition.error = "Stopped before it started."
                return
            entry = session.get(Entry, rendition.entry_id)
            if entry is None:
                return

            spoken = to_speech(entry.body, entry.format)
            rendition.status = "processing"
            rendition.segments_done = 0
            rendition.error = None
            rendition.chars = len(entry.body)
            entry.spoken = spoken

            job = {
                "user_id": rendition.user_id,
                "entry_id": rendition.entry_id,
                "text": spoken,
                "format": rendition.format,
                "voice": rendition.voice,
                "lang": rendition.lang,
                "speed": rendition.speed,
                "limit_s": rendition.limit_s,
                "start_segment": rendition.start_segment,
                "end_segment": rendition.end_segment,
                "mode": rendition.mode,
            }

        if not job["text"].strip():
            self._fail(
                rendition_id,
                "Once the formatting was stripped there were no words left to read."
                if job["format"] == "markdown"
                else "There is no text to read.",
            )
            return

        out_path = audio_path_for(job["user_id"], job["entry_id"], rendition_id)
        last_write = [0.0]

        def on_progress(done: int, total: int, _seconds: float) -> None:
            now = time.monotonic()
            if now - last_write[0] < self.progress_interval_s and done < total:
                return
            last_write[0] = now
            with session_scope() as session:
                session.execute(
                    update(Rendition)
                    .where(Rendition.id == rendition_id)
                    .values(segments_done=done, segments_total=total)
                )

        def should_stop() -> str | None:
            with session_scope() as session:
                current = session.get(Rendition, rendition_id)
                if current is None:
                    return DISCARD  # deleted while we were reading
                if current.stop_requested:
                    return KEEP
            # A restart keeps what has been read; there may be an hour of it.
            # If nothing has been written yet the engine says so, and the job
            # goes back in the queue instead of leaving an empty file behind.
            return KEEP if self._stopping.is_set() else None

        started = time.monotonic()
        try:
            result = self.engine.synthesize_to_file(
                job["text"],
                voice=job["voice"],
                lang=job["lang"],
                speed=job["speed"],
                out_path=out_path,
                limit_s=job["limit_s"],
                start_segment=job["start_segment"],
                end_segment=job["end_segment"],
                mode=job["mode"],
                on_progress=on_progress,
                should_stop=should_stop,
            )
        except Cancelled:
            log.info("rendition %s dropped before anything was written", rendition_id)
            self._drop(rendition_id)
            return
        except SynthesisError as exc:
            self._fail(rendition_id, str(exc))
            return
        except Exception:
            # `rendition.error` is shown in the interface, and a library's own
            # message tends to be a file path or an internal name. So the
            # traceback goes to the log and the reader gets a sentence.
            log.exception("synthesis blew up for rendition %s", rendition_id)
            self._fail(
                rendition_id,
                "Something went wrong while generating audio. Try again; if it "
                "keeps happening, the server log has the details.",
            )
            return

        wall_s = round(time.monotonic() - started, 2)
        with session_scope() as session:
            rendition = session.get(Rendition, rendition_id)
            if rendition is None:
                out_path.unlink(missing_ok=True)
                return
            # A sample that reached its cap did exactly what it was asked to do.
            # Only an interruption counts as stopped.
            rendition.status = "stopped" if result.reason == "stopped" else "ready"
            rendition.complete = result.complete
            rendition.audio_path = str(out_path)
            rendition.duration_s = result.duration_s
            rendition.cues = result.cues
            rendition.segments_done = result.segments_done
            rendition.segments_total = result.segments_total
            rendition.spoken_chars = result.spoken_chars
            rendition.document_segments = result.document_segments
            rendition.opening = result.opening or None
            rendition.wall_s = wall_s
            rendition.updated_at = utcnow()
            if rendition.status == "stopped":
                rendition.error = "Stopped early. Everything read up to here is kept."
            else:
                rendition.error = None

    def _drop(self, rendition_id: str) -> None:
        """A reading that produced nothing goes back in the queue on next boot."""
        with session_scope() as session:
            rendition = session.get(Rendition, rendition_id)
            if rendition is None:
                return
            if rendition.stop_requested:
                rendition.status = "stopped"
                rendition.error = "Stopped before any audio was made."
            else:
                rendition.status = "pending"
                rendition.segments_done = 0

    def _fail(self, rendition_id: str, message: str) -> None:
        with session_scope() as session:
            rendition = session.get(Rendition, rendition_id)
            if rendition is None:
                return
            rendition.status = "failed"
            rendition.error = message[:500]
            rendition.updated_at = utcnow()


_worker: Worker | None = None
_worker_lock = threading.Lock()


def get_worker() -> Worker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = Worker()
        return _worker


def set_worker(worker: Worker | None) -> None:
    global _worker
    with _worker_lock:
        _worker = worker
