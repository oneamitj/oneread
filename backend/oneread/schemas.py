"""Request and response shapes."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .auth import MIN_PASSWORD_LEN, USERNAME_RE
from .markdown_speech import DEFAULT_FORMAT, FORMATS
from .models import SCOPES
from .tts_engine import MAX_SPEED, MIN_SPEED, VOICE_IDS

__all__ = ["MAX_SPEED", "MIN_SPEED"]

MAX_TAGS = 12
MAX_TAG_LEN = 32


class Credentials(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        value = value.strip()
        if not USERNAME_RE.match(value):
            raise ValueError(
                "A user id is 3 to 32 characters, using letters, numbers, "
                "dot, dash or underscore."
            )
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        if len(value) < MIN_PASSWORD_LEN:
            raise ValueError(f"Passwords need at least {MIN_PASSWORD_LEN} characters.")
        if len(value) > 256:
            raise ValueError("That password is too long.")
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    created_at: datetime


class SessionOut(BaseModel):
    user: UserOut
    created: bool = False


def _clean_tags(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = re.split(r"[,\n]", value)
    seen: dict[str, str] = {}
    for raw in value:  # type: ignore[union-attr]
        tag = re.sub(r"\s+", " ", str(raw)).strip().strip("#")
        if not tag:
            continue
        tag = tag[:MAX_TAG_LEN]
        seen.setdefault(tag.casefold(), tag)
    return list(seen.values())[:MAX_TAGS]


class EntryIn(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    body: str
    format: str = DEFAULT_FORMAT
    tags: list[str] = []
    #: How many minutes to read on creation. Null uses the configured default.
    sample_minutes: int | None = None
    voice: str = "F1"
    lang: str = "en"
    speed: float = 1.05
    #: A file already read by POST /api/uploads, to keep alongside the entry.
    upload_id: str | None = None

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        value = re.sub(r"\s+", " ", value).strip()
        if not value:
            raise ValueError("Give the entry a title.")
        return value

    @field_validator("body")
    @classmethod
    def _clean_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Add some text to read out.")
        return value

    @field_validator("format")
    @classmethod
    def _format(cls, value: str) -> str:
        if value not in FORMATS:
            raise ValueError(f"Pick one of {', '.join(FORMATS)}, not {value!r}.")
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, value: object) -> list[str]:
        return _clean_tags(value)

    @field_validator("voice")
    @classmethod
    def _voice(cls, value: str) -> str:
        if value not in VOICE_IDS:
            raise ValueError(f"There is no voice called {value!r}.")
        return value

    @field_validator("sample_minutes")
    @classmethod
    def _sample_minutes(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 120:
            raise ValueError("A sample runs between 1 and 120 minutes.")
        return value

    @field_validator("speed")
    @classmethod
    def _speed(cls, value: float) -> float:
        if not MIN_SPEED <= value <= MAX_SPEED:
            raise ValueError(f"Speed goes from {MIN_SPEED} to {MAX_SPEED}.")
        return round(value, 2)


class EntryUpdate(EntryIn):
    pass


class Cue(BaseModel):
    i: int
    start: float
    end: float
    text: str


class RenditionOut(BaseModel):
    """One reading of a document. `cues` only comes back from the detail route."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    entry_id: str
    scope: str
    limit_s: int | None
    status: str
    stop_requested: bool
    complete: bool
    progress: float
    segments_done: int
    segments_total: int
    document_segments: int
    opening: str | None
    duration_s: float | None
    spoken_chars: int
    wall_s: float | None
    error: str | None
    voice: str
    lang: str
    speed: float
    format: str
    start_segment: int
    end_segment: int | None
    #: The entry leads with this one, so it can't be removed on its own.
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


class RenditionDetail(RenditionOut):
    cues: list[Cue] | None


class VoiceChoice(BaseModel):
    """Settings for one reading. Anything left out falls back to the entry's."""

    voice: str | None = None
    lang: str | None = None
    speed: float | None = None

    @field_validator("voice")
    @classmethod
    def _voice(cls, value: str | None) -> str | None:
        if value is not None and value not in VOICE_IDS:
            raise ValueError(f"There is no voice called {value!r}.")
        return value

    @field_validator("speed")
    @classmethod
    def _speed(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not MIN_SPEED <= value <= MAX_SPEED:
            raise ValueError(f"Speed goes from {MIN_SPEED} to {MAX_SPEED}.")
        return round(value, 2)


class RenditionIn(VoiceChoice):
    scope: str = "full"
    minutes: int | None = None
    #: Half-open span of sentences, for scope "range".
    start: int = 0
    end: int | None = None

    @field_validator("scope")
    @classmethod
    def _scope(cls, value: str) -> str:
        if value not in SCOPES:
            raise ValueError(f"Pick one of {', '.join(SCOPES)}.")
        return value

    @field_validator("minutes")
    @classmethod
    def _minutes(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if not 1 <= value <= 120:
            raise ValueError("A sample runs between 1 and 120 minutes.")
        return value

    @model_validator(mode="after")
    def _range_makes_sense(self) -> RenditionIn:
        if self.scope != "range":
            return self
        if self.start < 0:
            raise ValueError("A range starts at the first sentence or later.")
        if self.end is not None and self.end <= self.start:
            raise ValueError("The end of a range comes after its start.")
        return self


class SourceFile(BaseModel):
    """The file an entry's text was taken out of, when there was one."""

    name: str
    media_type: str
    bytes: int


class UploadOut(BaseModel):
    """A file that has been read, waiting for the editor to do something with it."""

    id: str
    filename: str
    media_type: str
    bytes: int
    kind: str
    #: What the entry's format should become: "plain" or "markdown".
    format: str
    #: A title worth suggesting: the document's own, or its filename tidied up.
    title: str
    #: The words that came out, for the editor to show and let people change.
    text: str
    #: True when the file was longer than the limit and the tail was left off.
    truncated: bool


class EntryOut(BaseModel):
    """One entry in full, with every reading made of it."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    body: str
    format: str
    spoken: str | None
    tags: list[str]
    voice: str
    lang: str
    speed: float
    source: SourceFile | None = None
    #: True while a full reading is running. Filled in by the route, not the model.
    locked: bool = False
    renditions: list[RenditionOut] = []
    created_at: datetime
    updated_at: datetime


class EntrySummary(BaseModel):
    """What the library grid needs.

    A hundred-thousand-character entry carries megabytes of text and cues, and
    the grid shows neither, so the list leaves both behind.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    excerpt: str
    body_chars: int
    format: str
    tags: list[str]
    voice: str
    lang: str
    speed: float
    source: SourceFile | None = None
    locked: bool
    rendition_count: int
    #: The reading the card should play: the most complete one available.
    playable: RenditionOut | None
    #: Whatever is running right now, so the card can show progress.
    active: RenditionOut | None
    created_at: datetime
    updated_at: datetime


class EntryList(BaseModel):
    entries: list[EntrySummary]
    tags: list[str]
    total: int


class EstimateOut(BaseModel):
    """Roughly what a reading will cost, before anyone commits to it."""

    scope: str
    audio_s: float
    wall_s: float
    segments: int
    characters: int
    #: True once the numbers come from work this machine has actually done.
    measured: bool


class SegmentOut(BaseModel):
    """One sentence, and where it lands on the estimated timeline."""

    i: int
    text: str
    chars: int
    start_s: float
    end_s: float


class SegmentList(BaseModel):
    """The document as the reader sees it, for drawing a range picker."""

    segments: list[SegmentOut]
    audio_s: float
    measured: bool


class Meta(BaseModel):
    voices: list[dict]
    languages: list[str]
    default_voice: str
    default_lang: str
    default_speed: float
    max_text_chars: int
    min_speed: float
    max_speed: float
    formats: list[str]
    sample_minutes: int
    sample_minute_choices: list[int]
    allow_registration: bool
    #: Every extension the uploader accepts, with a name for each.
    upload_types: list[dict]
    max_upload_bytes: int
