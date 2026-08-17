"""How long will this take, and how long will it be.

Both answers come from measurement where possible. Every finished rendition
records how many characters it read, how much audio came out, and how long the
machine took, so the next estimate is calibrated to this voice on this hardware
rather than to a number someone wrote down once.
"""

from __future__ import annotations

from dataclasses import dataclass

from .segmenter import segment_text

# Fallbacks for the very first estimate, measured on an M-series laptop:
# 3,120 characters produced 230.9 s of audio in 53.2 s at speed 1.05.
BASE_SECONDS_PER_CHAR = 0.0683
BASE_SPEED = 1.05
BASE_WALL_PER_AUDIO_SECOND = 0.231
GAP_S = 0.3


@dataclass(frozen=True)
class Calibration:
    """Rates learned from work already done."""

    seconds_per_char: float = BASE_SECONDS_PER_CHAR
    wall_per_audio_second: float = BASE_WALL_PER_AUDIO_SECOND
    measured: bool = False

    @classmethod
    def from_rendition(
        cls, *, spoken_chars: int, duration_s: float, wall_s: float, speed: float,
        segments: int,
    ) -> Calibration | None:
        """Back out the per-character rate from one finished rendition."""
        if spoken_chars < 200 or duration_s <= 0 or wall_s <= 0:
            return None  # too small to learn anything reliable from
        speech = max(0.0, duration_s - max(0, segments - 1) * GAP_S)
        if speech <= 0:
            return None
        # Normalise to the reference speed so the rate transfers to other speeds.
        per_char = (speech / spoken_chars) * (speed / BASE_SPEED)
        return cls(
            seconds_per_char=per_char,
            wall_per_audio_second=wall_s / duration_s,
            measured=True,
        )


@dataclass(frozen=True)
class Estimate:
    audio_s: float
    wall_s: float
    segments: int
    characters: int
    measured: bool

    def capped(self, limit_s: int | None) -> Estimate:
        """What a sample of the first `limit_s` seconds would cost."""
        if limit_s is None or self.audio_s <= limit_s:
            return self
        share = limit_s / self.audio_s
        return Estimate(
            audio_s=float(limit_s),
            wall_s=round(self.wall_s * share, 1),
            segments=max(1, round(self.segments * share)),
            characters=round(self.characters * share),
            measured=self.measured,
        )


def estimate(
    spoken: str,
    *,
    lang: str,
    speed: float,
    calibration: Calibration | None = None,
) -> Estimate:
    rates = calibration or Calibration()
    segments = segment_text(spoken, lang=lang)
    characters = sum(len(segment) for segment in segments)
    per_char = rates.seconds_per_char * (BASE_SPEED / max(speed, 0.1))
    audio_s = characters * per_char + max(0, len(segments) - 1) * GAP_S
    return Estimate(
        audio_s=round(audio_s, 1),
        wall_s=round(audio_s * rates.wall_per_audio_second, 1),
        segments=len(segments),
        characters=characters,
        measured=rates.measured,
    )
