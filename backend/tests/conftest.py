from __future__ import annotations

import threading
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from oneread import db as db_module
from oneread.config import Settings, get_settings, set_settings
from oneread.main import create_app
from oneread.segmenter import segment_text
from oneread.tts_engine import Synthesis, TTSEngine, set_engine
from oneread.worker import Worker, set_worker

SAMPLE_RATE = 44100


class FakeEngine(TTSEngine):
    """Writes real (silent) wav files at plausible speeds. No ONNX involved."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.calls: list[dict] = []
        self.fail_with: str | None = None
        # Tests that need to interfere with a job in flight hold it here.
        # `hold_at` is the segment index to block on, so a test can let a couple
        # of sentences land before it interferes.
        self.hold: threading.Event | None = None
        self.hold_at = 0
        self.started = threading.Event()

    def load(self) -> None:  # pragma: no cover - nothing to load
        pass

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    def languages(self) -> list[str]:
        return ["en", "ko", "na"]

    def check_text(self, text: str) -> list[str]:
        return []

    def synthesize_to_file(
        self,
        text,
        *,
        voice,
        lang,
        speed,
        out_path: Path,
        limit_s=None,
        start_segment=0,
        end_segment=None,
        on_progress=None,
        should_stop=None,
    ) -> Synthesis:
        from oneread.tts_engine import DISCARD, KEEP, Cancelled, SynthesisError

        self.calls.append(
            {
                "text": text,
                "voice": voice,
                "lang": lang,
                "speed": speed,
                "limit_s": limit_s,
                "start_segment": start_segment,
                "end_segment": end_segment,
            }
        )
        if self.hold is None:
            self.started.set()
        if self.fail_with:
            raise SynthesisError(self.fail_with)

        every = segment_text(text, lang=lang)
        segments = every[start_segment:end_segment]
        if not segments:
            raise SynthesisError("That range doesn't cover any text.")
        gap = self.settings.silence_between_segments_s
        cues: list[dict] = []
        cursor = 0.0
        done = 0
        spoken_chars = 0
        complete = True
        reason = "complete"

        for index, segment in enumerate(segments):
            if self.hold is not None and index == self.hold_at:
                # Signal only once we're parked, so a test that waits on this
                # knows exactly how many sentences exist.
                self.started.set()
                self.hold.wait(5)
            stop = should_stop() if should_stop is not None else None
            if stop == DISCARD:
                raise Cancelled()
            if stop == KEEP:
                complete = False
                reason = "stopped"
                break

            length = max(0.25, len(segment) * 0.06 / speed)
            cues.append(
                {
                    "i": start_segment + index,
                    "start": round(cursor, 3),
                    "end": round(cursor + length, 3),
                    "text": segment,
                }
            )
            cursor += length
            done = index + 1
            spoken_chars += len(segment)

            if limit_s is not None and cursor >= limit_s:
                complete = done >= len(segments)
                reason = "complete" if complete else "limit"
                if on_progress is not None:
                    on_progress(done, len(segments), cursor)
                break
            if index < len(segments) - 1:
                cursor += gap
            if on_progress is not None:
                on_progress(done, len(segments), cursor)

        if not cues:
            raise Cancelled()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(b"\x00\x00" * int(cursor * SAMPLE_RATE))

        return Synthesis(
            duration_s=round(cursor, 3),
            cues=cues,
            sample_rate=SAMPLE_RATE,
            segments_done=done,
            segments_total=len(segments),
            spoken_chars=spoken_chars,
            document_segments=len(every),
            opening=cues[0]["text"][:160] if cues else "",
            complete=complete and start_segment == 0 and len(segments) == len(every),
            reason=reason,
        )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    values = Settings(
        secret_key="test-secret-key",
        data_dir=tmp_path / "data",
        static_dir=tmp_path / "nowhere",
        preload_model=False,
        generate_per_hour=1000,
        login_per_minute=1000,
    )
    set_settings(values)
    yield values
    set_settings(None)


@pytest.fixture
def engine(settings: Settings) -> FakeEngine:
    fake = FakeEngine(settings)
    set_engine(fake)
    return fake


@pytest.fixture
def client(settings: Settings, engine: FakeEngine):
    sql_engine = db_module.create_engine_for(settings.sqlalchemy_url)
    db_module.init_db(sql_engine)
    db_module.set_session_factory(sessionmaker(bind=sql_engine, expire_on_commit=False))

    worker = Worker(engine=engine)
    set_worker(worker)

    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    from oneread.routers import auth as auth_routes
    from oneread.routers import entries as entry_routes
    from oneread.routers import preview as preview_routes
    from oneread.routers import uploads as upload_routes

    auth_routes.reset_limiters()
    entry_routes.reset_limiters()
    preview_routes.reset_limiters()
    upload_routes.reset_limiters()

    with TestClient(app) as test_client:
        test_client.headers.update({"X-Requested-With": "oneread"})
        test_client.worker = worker  # type: ignore[attr-defined]
        test_client.engine = engine  # type: ignore[attr-defined]
        yield test_client

    set_worker(None)
    sql_engine.dispose()


def sign_in(client: TestClient, username: str = "ada.lovelace", password: str = "hunter2hunter"):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def entry_of(client: TestClient, entry_id: str) -> dict:
    response = client.get(f"/api/entries/{entry_id}")
    assert response.status_code == 200, response.text
    return response.json()


def wait_for(
    client: TestClient, entry_id: str, status: str = "ready", timeout: float = 10.0
) -> dict:
    """Wait for the queue to drain, then return the newest reading."""
    client.worker.wait_idle(timeout)  # type: ignore[attr-defined]
    body = entry_of(client, entry_id)
    assert body["renditions"], body
    latest = body["renditions"][-1]
    assert latest["status"] == status, latest
    return latest
