"""Application settings, read from the environment (or a .env file)."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from .pacing import (
    DEFAULT_BLOCK_GAP_S,
    DEFAULT_LINE_GAP_S,
    DEFAULT_SENTENCE_GAP_S,
)
from .segmenter import CHUNK_MAX_CHARS, CHUNK_TARGET_CHARS

#: A list setting written as a comma-separated string rather than JSON.
#:
#: pydantic-settings runs `json.loads` over any list-typed field before a
#: `mode="before"` validator sees it, so `ONEREAD_ALLOWED_HOSTS=example.com`
#: would raise `SettingsError` at import. `NoDecode` turns that off and leaves
#: the string to `_split_csv` / `_split_ints`.
CommaSeparated = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ONEREAD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- core ---------------------------------------------------------------
    secret_key: str = ""  # generated into data_dir on first run if unset
    data_dir: Path = Path("./data")
    database_url: str = ""  # derived from data_dir when empty

    #: Level for the app's own loggers (`oneread.*`). Production runs this at
    #: ERROR: nginx keeps no access log and uvicorn is started with
    #: --no-access-log, so what's left in `docker compose logs` is the app
    #: saying something went wrong and nothing else. WARNING is the setting to
    #: reach for first when something is off but not yet failing.
    log_level: str = "INFO"

    # --- http ---------------------------------------------------------------
    allowed_hosts: CommaSeparated = ["*"]
    #: Origins allowed to call the API from a browser. Normally empty: the
    #: frontend is served from this same origin, so nothing cross-site is
    #: needed. "*" is refused outright — see `_no_wildcard_origin`.
    cors_origins: CommaSeparated = []
    #: Ceiling on a request body, for everything except uploads (which carry
    #: their own, larger limit). A 100k-character entry is comfortably inside
    #: this even once JSON escaping has had its way with it.
    max_request_bytes: int = 2 * 1024 * 1024
    cookie_secure: bool = False
    cookie_name: str = "oneread_session"
    session_max_age_s: int = 60 * 60 * 24 * 30
    #: Once a session is older than this, using the app renews it. Someone who
    #: keeps reading never gets signed out; someone who walks away eventually is.
    session_refresh_after_s: int = 60 * 60 * 24

    # --- accounts -----------------------------------------------------------
    allow_registration: bool = True

    # --- visits -------------------------------------------------------------
    #: The cookieless headcount: page views, unique visitors, signups and
    #: sign-ins, four integers per UTC day. Nothing is written to the browser
    #: and no address reaches the disk, which is why it runs without asking.
    #: See `visits.py`. Off means the table simply stays empty.
    count_visits: bool = True
    #: How long a crash can cost. The counts live in memory between flushes, so
    #: this is the window, and one row a minute is nothing next to what the
    #: synthesis worker already writes.
    visits_flush_interval_s: float = 60.0

    # --- synthesis ----------------------------------------------------------
    max_text_chars: int = 100_000
    tts_steps: int = 8
    default_voice: str = "F1"
    default_lang: str = "en"
    default_speed: float = 1.05
    max_queued_per_user: int = 3
    # A new entry gets read this far, so nobody waits half an hour to find out
    # they picked the wrong voice. The full reading is a deliberate second step.
    sample_minutes: int = 1
    sample_minute_choices: Annotated[list[int], NoDecode] = [1, 3, 5]
    preview_max_chars: int = 180
    preview_sample_text: str = (
        "This is how I sound. Give me a paragraph and I'll read the whole thing."
    )
    preload_model: bool = True  # load ONNX at startup so the first entry isn't slow
    # Pacing. A paragraph is read through; the stop belongs at its end. The
    # model also leaves its own silence on each clip, which is trimmed off
    # first, so these are the pauses actually heard.
    silence_between_sentences_s: float = DEFAULT_SENTENCE_GAP_S
    silence_between_lines_s: float = DEFAULT_LINE_GAP_S
    silence_between_blocks_s: float = DEFAULT_BLOCK_GAP_S
    trim_segment_silence: bool = True
    #: How much text the experimental "refined" reading hands the model at once,
    #: in characters (CJK counts triple). Whole sentences only, and never past
    #: `CHUNK_MAX_CHARS`, where the duration predictor saturates and the speech
    #: comes out rushed. See `segmenter.CHUNK_TARGET_CHARS`.
    paragraph_chunk_chars: int = CHUNK_TARGET_CHARS

    # --- uploads ------------------------------------------------------------
    #: Refused outright above this. 25 MB is a long book as a PDF.
    max_upload_bytes: int = 25 * 1024 * 1024
    #: Office files are zips. This is the ceiling on what one is allowed to
    #: become once unpacked, so a small file can't fill the disk.
    max_unzipped_bytes: int = 200 * 1024 * 1024
    #: Path to LibreOffice, which is the only way to read the 1990s .doc and
    #: .ppt formats. Left empty, those two are politely refused.
    soffice_path: str = ""

    # --- rate limits --------------------------------------------------------
    login_per_minute: int = 10
    #: Sign-in attempts are also counted against the address that opened the
    #: connection, so rotating `X-Forwarded-For` can't shake the limit off. That
    #: bucket is this many times the per-client one, because behind a proxy
    #: every visitor shares it. Raise it if a busy shared proxy hits the ceiling.
    login_peer_factor: int = 5
    #: Wrong passwords for one user id per minute, whatever address they appear
    #: to come from. Addresses can be rewritten and connections can be reopened;
    #: the account being guessed at is the one thing an attacker after it can't
    #: vary. Only failures count, so this never stands between someone and their
    #: own account.
    login_failures_per_minute: int = 10
    generate_per_hour: int = 30
    preview_per_hour: int = 120
    upload_per_hour: int = 60
    #: The routes that reflow text without synthesizing it: what the voice will
    #: say, the sentence list behind the range picker, and the cost estimate.
    #: None of them make audio, so none was metered — but each one parses and
    #: segments up to `max_text_chars`, and there is a single worker to occupy.
    #: Generous enough that a range picker dragging in real time never notices.
    text_per_minute: int = 120

    # --- frontend -----------------------------------------------------------
    static_dir: Path = Path("./frontend/dist")

    # --- public site --------------------------------------------------------
    #: The address this instance answers on, e.g. https://oneread.example. Used
    #: for the canonical link, the sitemap and the absolute URLs in the share
    #: cards. Empty means "don't claim an address", and the pages fall back to
    #: relative links.
    public_url: str = ""
    #: Whether this instance is meant to be found. Off by default, because most
    #: of them are somebody's laptop or a box on a home network: robots.txt then
    #: refuses every crawler, /about carries `noindex`, and /sitemap.xml is a
    #: 404. Turn it on for an instance you actually want in search results and
    #: in the answers assistants give.
    public_site: bool = False

    @field_validator("paragraph_chunk_chars")
    @classmethod
    def _within_the_models_reach(cls, value: int) -> int:
        if not 40 <= value <= CHUNK_MAX_CHARS:
            raise ValueError(
                f"ONEREAD_PARAGRAPH_CHUNK_CHARS={value} is outside 40-{CHUNK_MAX_CHARS}. "
                "Above that the model predicts one duration for more speech than "
                "fits in it, and the reading is rushed."
            )
        return value

    @field_validator("log_level")
    @classmethod
    def _known_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(
                f"ONEREAD_LOG_LEVEL={value!r} isn't a level. Use one of DEBUG, "
                "INFO, WARNING, ERROR, CRITICAL."
            )
        return level

    @field_validator("public_url")
    @classmethod
    def _no_trailing_slash(cls, value: str) -> str:
        """So that `public_url + "/about"` never comes out with two slashes."""
        return value.strip().rstrip("/")

    @field_validator("sample_minute_choices", mode="before")
    @classmethod
    def _split_ints(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(item) for item in value.split(",") if item.strip()]
        return value

    @field_validator("allowed_hosts", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_origin(cls, value: list[str]) -> list[str]:
        """Refuse "*", because the app sends cookies cross-origin.

        Starlette reads `allow_origins=["*"]` with `allow_credentials=True` as
        "reflect whichever Origin asked", so any site would get
        `Access-Control-Allow-Credentials: true` — every signed-in reader's
        library, plus a passing preflight that lifts the `X-Requested-With`
        CSRF check. A mistake, not a setting, so the app refuses to start.
        """
        if "*" in value:
            raise ValueError(
                "ONEREAD_CORS_ORIGINS can't be '*': sessions are cookie-based, and a "
                "wildcard would let any site read and change a signed-in reader's "
                "library. Name the origins instead, e.g. https://oneread.example."
            )
        return value

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def preview_dir(self) -> Path:
        return self.data_dir / "previews"

    @property
    def upload_dir(self) -> Path:
        """Original files, kept beside the entries that were made from them."""
        return self.data_dir / "uploads"

    @property
    def staging_dir(self) -> Path:
        """Files that have been read but not yet attached to an entry."""
        return self.data_dir / "staging"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite+pysqlite:///{(self.data_dir / 'oneread.db').resolve()}"


@lru_cache(maxsize=1)
def _load_settings() -> Settings:
    return prepare(Settings())


def prepare(settings: Settings) -> Settings:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    settings.preview_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.staging_dir.mkdir(parents=True, exist_ok=True)
    if not settings.secret_key:
        settings.secret_key = _stored_secret(settings.data_dir)
    return settings


def _stored_secret(data_dir: Path) -> str:
    """Read the signing key from the data directory, making one if it's absent.

    Without this a restart invents a new key and invalidates every session
    cookie. ONEREAD_SECRET_KEY takes precedence; the file is then never touched.
    """
    path = data_dir / "secret.key"
    try:
        existing = path.read_text().strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass

    # Created at 0600 rather than chmod'ed afterwards: `write_text` opens under
    # the umask, leaving a window where any local account can read a key that
    # signs a cookie for any user. O_EXCL settles the other race — two workers
    # starting together, the loser reading what the winner wrote.
    key = secrets.token_urlsafe(48)
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip() or key
    with os.fdopen(handle, "w") as sink:
        sink.write(key)
    return key


_override: Settings | None = None


def get_settings() -> Settings:
    return _override if _override is not None else _load_settings()


def set_settings(settings: Settings | None) -> None:
    """Test hook: point the whole process at a throwaway config."""
    global _override
    _override = prepare(settings) if settings is not None else None
    _load_settings.cache_clear()
