"""The engine's own backstop for characters the loaded model can't pronounce."""

from __future__ import annotations

from oneread.tts_engine import TTSEngine


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
