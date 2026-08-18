from __future__ import annotations

from oneread.markdown_speech import to_speech
from oneread.segmenter import (
    MAX_SEGMENT_CHARS,
    segment_spans,
    segment_text,
)
from oneread.subtitles import slugify, to_srt, to_vtt


def test_sentences_split_on_terminators():
    assert segment_text("Warm the pan. Then add butter! Is the oven hot yet?") == [
        "Warm the pan.",
        "Then add butter!",
        "Is the oven hot yet?",
    ]


def test_a_dangling_fragment_joins_the_line_before_it():
    assert segment_text("The oven needs twenty minutes to warm up. Ready?") == [
        "The oven needs twenty minutes to warm up. Ready?"
    ]


def test_abbreviations_do_not_end_a_sentence():
    assert segment_text("Dr. Smith went to Washington. He stayed for a week.") == [
        "Dr. Smith went to Washington.",
        "He stayed for a week.",
    ]


def test_cjk_splits_without_spaces():
    assert segment_text("第一句话。第二句话！") == ["第一句话。", "第二句话！"]


def test_stubs_join_their_neighbour():
    assert segment_text("Yes. The oven needs twenty minutes to warm up.") == [
        "Yes. The oven needs twenty minutes to warm up."
    ]


def test_long_text_is_capped():
    segments = segment_text("word " * 300)
    assert segments
    assert max(len(s) for s in segments) <= MAX_SEGMENT_CHARS


def test_korean_gets_a_shorter_cap():
    segments = segment_text("가나다라마바사 " * 40, lang="ko")
    assert max(len(s) for s in segments) <= 120


def test_paragraphs_stay_apart():
    assert segment_text("First paragraph here.\n\nSecond paragraph here.") == [
        "First paragraph here.",
        "Second paragraph here.",
    ]


def test_empty_text_gives_nothing():
    assert segment_text("   ") == []


def _blocks(text: str, lang: str | None = None) -> list[bool]:
    return [span.ends_block for span in segment_spans(text, lang)]


def _ends(text: str, lang: str | None = None) -> list[str]:
    return [span.ends for span in segment_spans(text, lang)]


def test_only_the_last_sentence_of_a_paragraph_closes_it():
    text = "Warm the pan. Add butter.\n\nThen the eggs go in. Stir slowly."
    assert _blocks(text) == [False, True, False, True]


def test_a_lone_sentence_closes_its_paragraph():
    assert _blocks("All there is to say.") == [True]


def test_splitting_an_over_long_sentence_moves_the_block_end_to_the_last_piece():
    flags = _blocks("word " * 300)
    assert flags[-1] is True
    assert not any(flags[:-1])


def test_a_stub_does_not_swallow_the_next_paragraph():
    text = "Yes.\n\nThe oven needs twenty minutes to warm up."
    assert segment_text(text) == ["Yes.", "The oven needs twenty minutes to warm up."]
    assert _blocks(text) == [True, True]


def test_a_line_that_finishes_a_sentence_gets_its_own_pause():
    text = "Warm the pan.\nAdd the butter.\nWait for it to foam."
    assert _ends(text) == ["line", "line", "block"]


def test_a_newline_mid_sentence_is_only_a_wrap():
    text = (
        "Warm the pan over a low flame and wait until the\n"
        "butter stops foaming. Then crack three eggs into\n"
        "a bowl and beat them well."
    )
    assert segment_text(text) == [
        "Warm the pan over a low flame and wait until the butter stops foaming.",
        "Then crack three eggs into a bowl and beat them well.",
    ]
    assert _ends(text) == ["sentence", "block"]


def test_lines_that_never_finish_a_sentence_are_read_one_by_one():
    """A shopping list, an address, a verse: the newline is the whole point."""
    assert _ends("Eggs\nButter\nSalt") == ["line", "line", "block"]
    assert segment_text("Eggs\nButter\nSalt") == ["Eggs", "Butter", "Salt"]


def test_every_markdown_list_item_ends_a_block():
    spoken = to_speech("- First point\n- Second point\n", "markdown")
    assert _blocks(spoken) == [True, True]


CUES = [
    {"i": 0, "start": 0.0, "end": 1.5, "text": "Hello  there."},
    {"i": 1, "start": 1.8, "end": 3671.045, "text": "Bye."},
]


def test_srt_format():
    assert to_srt(CUES) == (
        "1\n00:00:00,000 --> 00:00:01,500\nHello there.\n\n"
        "2\n00:00:01,800 --> 01:01:11,045\nBye.\n"
    )


def test_vtt_starts_with_its_header():
    text = to_vtt(CUES)
    assert text.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:01.500" in text


def test_slugify():
    assert slugify("Chapter 1: My Notes!") == "chapter-1-my-notes"
    assert slugify("***") == "oneread"
    assert len(slugify("x" * 200)) <= 60
