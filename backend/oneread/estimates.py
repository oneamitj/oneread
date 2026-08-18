"""How long will this take, and how long will it be.

Both answers come from measurement where possible. Every finished rendition
records how many characters it read, how much audio came out, and how long the
machine took, so the next estimate is calibrated to this voice on this hardware
rather than to a number someone wrote down once.
"""

from __future__ import annotations

from dataclasses import dataclass

from .pacing import DEFAULT_SENTENCE_GAP_S, MODEL_INNER_GAP_S, total_gap_s
from .segmenter import BY_PARAGRAPH, BY_SENTENCE, Segment, group_spans, segment_spans

# Fallbacks for the very first estimate, measured on an M-series laptop:
# 3,120 characters produced 230.9 s of audio in 53.2 s at speed 1.05.
BASE_SECONDS_PER_CHAR = 0.0683
BASE_SPEED = 1.05
BASE_WALL_PER_AUDIO_SECOND = 0.231


@dataclass(frozen=True)
class Calibration:
    """Rates learned from work already done."""

    seconds_per_char: float = BASE_SECONDS_PER_CHAR
    wall_per_audio_second: float = BASE_WALL_PER_AUDIO_SECOND
    measured: bool = False

    @classmethod
    def from_rendition(
        cls, *, spoken_chars: int, duration_s: float, wall_s: float, speed: float,
        segments: int, mode: str = BY_SENTENCE,
    ) -> Calibration | None:
        """Back out the per-character rate from one finished rendition."""
        if spoken_chars < 200 or duration_s <= 0 or wall_s <= 0:
            return None  # too small to learn anything reliable from
        # Only the segment count survives on a rendition, not where its
        # paragraphs ended, so this takes the shorter gap and reads the rate a
        # touch slow. It is a floor, and it corrects itself as readings land.
        # A chunked reading pauses between sentences too, but the model does it
        # rather than us, and a little longer.
        per_gap = MODEL_INNER_GAP_S if mode == BY_PARAGRAPH else DEFAULT_SENTENCE_GAP_S
        speech = max(0.0, duration_s - max(0, segments - 1) * per_gap)
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
    mode: str = BY_SENTENCE,
    chunk_chars: int | None = None,
) -> Estimate:
    return estimate_spans(
        segment_spans(spoken, lang=lang),
        speed=speed,
        calibration=calibration,
        mode=mode,
        chunk_chars=chunk_chars,
    )


def estimate_spans(
    segments: list[Segment],
    *,
    speed: float,
    calibration: Calibration | None = None,
    mode: str = BY_SENTENCE,
    chunk_chars: int | None = None,
) -> Estimate:
    """The same answer for pieces already segmented — a slider range, say.

    Going back through text would lose where the paragraphs were, and with them
    the difference between a breath and a stop.

    Under "paragraph" the same sentences are grouped first: fewer gaps of ours,
    and one of the model's own inside every chunk. The count that comes back is
    still sentences, so the two modes can be compared.
    """
    rates = calibration or Calibration()
    characters = sum(len(segment.text) for segment in segments)
    per_char = rates.seconds_per_char * (BASE_SPEED / max(speed, 0.1))

    pieces = segments
    inside = 0.0
    if mode == BY_PARAGRAPH:
        pieces = (
            group_spans(segments, target=chunk_chars)
            if chunk_chars
            else group_spans(segments)
        )
        inside = sum(piece.parts - 1 for piece in pieces) * MODEL_INNER_GAP_S

    audio_s = characters * per_char + total_gap_s(pieces) + inside
    return Estimate(
        audio_s=round(audio_s, 1),
        wall_s=round(audio_s * rates.wall_per_audio_second, 1),
        segments=len(segments),
        characters=characters,
        measured=rates.measured,
    )
