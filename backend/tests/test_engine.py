"""The engine's own backstop for characters the loaded model can't pronounce."""

from __future__ import annotations

import numpy as np

from oneread.tts_engine import TTSEngine, trim_silence


class Picky(TTSEngine):
    """Stands in for a model with a gap in its pronunciation table."""

    def __init__(self, unsupported: list[str]) -> None:
        self.unsupported = unsupported

    def check_text(self, text: str) -> list[str]:
        return [char for char in self.unsupported if char in text]


def test_a_character_the_model_cannot_say_is_dropped():
    assert Picky(["↳"]).speakable("First ↳ second.") == "First second."


def test_dropping_a_character_does_not_run_words_together():
    assert Picky(["★"]).speakable("north★south") == "north south"


def test_text_the_model_can_say_is_handed_over_untouched():
    text = "Warm the pan first.\n\nThen the butter goes in."
    assert Picky([]).speakable(text) == text


def test_line_breaks_survive_so_the_segmenter_still_sees_paragraphs():
    assert Picky(["✿"]).speakable("One.✿\n\nTwo.") == "One.\n\nTwo."


def _clip(sample_rate: int, lead_s: float, sound_s: float, tail_s: float) -> np.ndarray:
    """Speech-shaped noise with silence padded onto both ends."""
    sound = 0.5 * np.sin(
        2 * np.pi * 220 * np.arange(int(sound_s * sample_rate)) / sample_rate
    )
    return np.concatenate(
        [
            np.zeros(int(lead_s * sample_rate)),
            sound,
            np.zeros(int(tail_s * sample_rate)),
        ]
    ).astype(np.float32)


def test_trimming_takes_the_padding_off_both_ends():
    trimmed = trim_silence(_clip(44100, 0.4, 1.0, 0.6), 44100)
    # The sound plus the margins kept deliberately either side of it.
    assert 1.0 * 44100 <= trimmed.shape[0] <= 1.09 * 44100


def test_trimming_keeps_the_tail_margin():
    """A fricative dies away quietly; cutting flush would clip it."""
    trimmed = trim_silence(_clip(44100, 0.0, 0.5, 0.5), 44100)
    assert trimmed.shape[0] > 0.5 * 44100


def test_a_silent_clip_is_left_alone():
    silent = np.zeros(4410, dtype=np.float32)
    assert trim_silence(silent, 44100).shape[0] == 4410


def test_a_clip_shorter_than_one_frame_is_left_alone():
    tiny = np.full(100, 0.3, dtype=np.float32)
    assert trim_silence(tiny, 44100).shape[0] == 100
