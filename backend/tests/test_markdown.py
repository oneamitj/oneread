from __future__ import annotations

from oneread.markdown_speech import to_speech


def speak(text: str, **kwargs) -> list[str]:
    return to_speech(text, "markdown", **kwargs).split("\n\n")


def test_plain_text_is_left_alone():
    assert to_speech("Hello **world**.", "plain") == "Hello **world**."


def test_headings_lose_their_hashes():
    assert speak("# Release notes\n\nBody text.") == ["Release notes.", "Body text."]


def test_emphasis_and_inline_code_keep_their_words():
    assert speak("Some **bold** and *soft* and `code` text.") == [
        "Some bold and soft and code text."
    ]


def test_links_read_the_label_not_the_url():
    assert speak("See [the docs](https://example.com/deep/path) for more.") == [
        "See the docs for more."
    ]


def test_images_read_their_alt_text():
    assert speak("![a diagram of the pipeline](pipe.png)") == [
        "a diagram of the pipeline."
    ]


def test_bullets_become_separate_lines():
    assert speak("- first item\n- second item") == ["first item.", "second item."]


def test_numbered_lists_keep_their_numbers():
    assert speak("1. step one\n2. step two") == ["1. step one.", "2. step two."]


def test_nested_bullets_are_flattened_in_order():
    assert speak("- outer\n  - inner one\n  - inner two") == [
        "outer.",
        "inner one.",
        "inner two.",
    ]


def test_task_lists_say_whether_they_are_done():
    assert speak("- [x] shipped it\n- [ ] write the docs") == [
        "Done: shipped it.",
        "To do: write the docs.",
    ]


def test_blockquotes_drop_the_marker():
    assert speak("> A quote worth hearing.") == ["A quote worth hearing."]


def test_tables_are_read_column_by_column():
    table = (
        "| Name | Role |\n"
        "|------|------|\n"
        "| Ada | Engineer |\n"
        "| Grace | Admiral |\n"
    )
    assert speak(table) == [
        "Table with columns: Name, Role.",
        "Row 1. Name: Ada. Role: Engineer.",
        "Row 2. Name: Grace. Role: Admiral.",
    ]


def test_headerless_table_still_reads():
    assert speak("| one | two |\n| --- | --- |") == [
        "Table with columns: one, two."
    ]


def test_code_fences_are_announced_not_dictated():
    fence = "```python\ndef hi():\n    return 1\n```"
    assert speak(fence) == ["Code block in python, 2 lines."]
    assert speak("```\nsome code\n```") == ["Code block, 1 line."]


def test_code_can_be_read_out_when_asked():
    assert speak("```\nls -la\n```", speak_code=True) == ["ls -la."]


def test_horizontal_rules_are_silent():
    assert speak("Before.\n\n---\n\nAfter.") == ["Before.", "After."]


def test_html_is_stripped_but_its_text_survives():
    assert speak('<div class="note">Careful here</div>') == ["Careful here."]


def test_symbols_a_voice_cannot_pronounce_become_words():
    assert to_speech("Speed ≥ 1.5 and x → y.", "plain") == (
        "Speed greater than or equal to 1.5 and x to y."
    )
    assert to_speech("Cost ± 5%.", "plain") == "Cost plus or minus 5%."


def test_entities_are_decoded():
    assert speak("Tom &amp; Jerry &ge; fun") == ["Tom & Jerry greater than or equal to fun."]


def test_document_with_only_decoration_reads_as_nothing():
    assert to_speech("---\n\n***\n", "markdown") == ""


def test_whitespace_is_normalised():
    assert to_speech("too    many\t\tspaces\n\n\n\n\ngaps", "plain") == (
        "too many spaces\n\ngaps"
    )
