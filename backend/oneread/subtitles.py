"""Render cue lists as SubRip (.srt) or WebVTT (.vtt)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

Cue = Mapping[str, object]


def _clock(seconds: float, millis_sep: str) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}{millis_sep}{ms:03d}"


def _text_of(cue: Cue) -> str:
    return re.sub(r"\s+", " ", str(cue.get("text", ""))).strip()


def to_srt(cues: Iterable[Cue]) -> str:
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        start = _clock(float(cue["start"]), ",")
        end = _clock(float(cue["end"]), ",")
        blocks.append(f"{index}\n{start} --> {end}\n{_text_of(cue)}\n")
    return "\n".join(blocks)


def to_vtt(cues: Iterable[Cue]) -> str:
    blocks = ["WEBVTT\n"]
    for index, cue in enumerate(cues, start=1):
        start = _clock(float(cue["start"]), ".")
        end = _clock(float(cue["end"]), ".")
        blocks.append(f"{index}\n{start} --> {end}\n{_text_of(cue)}\n")
    return "\n".join(blocks)


_SLUG_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_SPACE = re.compile(r"[\s_-]+")


def slugify(title: str, fallback: str = "oneread") -> str:
    """Filename-safe version of an entry title."""
    slug = _SLUG_SPACE.sub("-", _SLUG_STRIP.sub("", title).strip()).strip("-")
    return (slug[:60] or fallback).lower()
