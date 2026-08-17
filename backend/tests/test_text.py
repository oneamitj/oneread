from __future__ import annotations

from oneread.segmenter import MAX_SEGMENT_CHARS, segment_text
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
