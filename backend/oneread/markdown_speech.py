"""Turn a document into something worth listening to.

Plain text goes through nearly untouched. Markdown gets flattened: the syntax
that exists to be *looked at* (hashes, pipes, asterisks, link targets) is either
dropped or turned into words, so the reader hears the document rather than its
punctuation.
"""

from __future__ import annotations

import html
import re
import unicodedata

from markdown_it import MarkdownIt
from markdown_it.token import Token

FORMATS = ("plain", "markdown")
DEFAULT_FORMAT = "plain"

_md = (
    MarkdownIt("commonmark")
    .enable("table")
    .enable("strikethrough")
)

# Symbols a screen shows fine but a voice can't. Anything left unmapped that the
# model can't pronounce gets dropped rather than failing the whole entry.
SPOKEN_SYMBOLS = {
    "≥": " greater than or equal to ",
    "≤": " less than or equal to ",
    "≠": " not equal to ",
    "≈": " approximately ",
    "→": " to ",
    "←": " from ",
    "↔": " to and from ",
    "⇒": " implies ",
    "±": " plus or minus ",
    "×": " times ",
    "÷": " divided by ",
    "∞": " infinity ",
    "√": " square root of ",
    "∑": " sum of ",
    "≡": " identical to ",
    "°": " degrees ",
    "µ": " micro",
    "†": " ",
    "‡": " ",
    "§": " section ",
    "¶": " paragraph ",
    "•": " ",
    "·": " ",
    "‧": " ",
    "—": ", ",
    "–": ", ",
    "―": ", ",
    "…": "…",
    " ": " ",
    "​": "",
    "‌": "",
    "‍": "",
    "﻿": "",
}

_HTML_TAG = re.compile(r"<[^>]{0,200}>")
_CHECKBOX = re.compile(r"^\[([ xX])\]\s*")
_SPACES = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")
_TERMINATED = re.compile(r"[.!?…:;,。！？]$")


def to_speech(text: str, fmt: str = DEFAULT_FORMAT, *, speak_code: bool = False) -> str:
    """Return the words to read out, in order."""
    if fmt == "markdown":
        text = _flatten_markdown(text, speak_code=speak_code)
    return _tidy(text)


# --- plain-text cleanup -----------------------------------------------------


def _tidy(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for symbol, spoken in SPOKEN_SYMBOLS.items():
        if symbol in text:
            text = text.replace(symbol, spoken)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANKS.sub("\n\n", text).strip()


def _sentence(text: str) -> str:
    """Give a fragment a full stop so it lands as its own subtitle cue."""
    text = text.strip()
    if not text:
        return ""
    return text if _TERMINATED.search(text) else f"{text}."


# --- markdown ---------------------------------------------------------------


def _flatten_markdown(text: str, *, speak_code: bool) -> str:
    tokens = _md.parse(text)
    blocks: list[str] = []
    _walk(tokens, 0, len(tokens), blocks, speak_code=speak_code)
    return "\n\n".join(block for block in blocks if block)


def _walk(
    tokens: list[Token],
    start: int,
    end: int,
    blocks: list[str],
    *,
    speak_code: bool,
    ordinal: int | None = None,
) -> None:
    index = start
    while index < end:
        token = tokens[index]
        kind = token.type

        if kind == "heading_open":
            close = _match(tokens, index, "heading_close")
            blocks.append(_sentence(_inline(tokens[index + 1 : close])))
            index = close + 1

        elif kind == "paragraph_open":
            close = _match(tokens, index, "paragraph_close")
            spoken = _inline(tokens[index + 1 : close])
            spoken = _checkbox(spoken)
            if ordinal is not None and spoken:
                spoken = f"{ordinal}. {spoken}"
                ordinal = None
            if spoken:
                blocks.append(_sentence(spoken))
            index = close + 1

        elif kind in ("bullet_list_open", "ordered_list_open"):
            close = _match(tokens, index, kind.replace("_open", "_close"))
            _list(tokens, index + 1, close, blocks, kind == "ordered_list_open",
                  int(token.attrGet("start") or 1), speak_code=speak_code)
            index = close + 1

        elif kind == "blockquote_open":
            close = _match(tokens, index, "blockquote_close")
            _walk(tokens, index + 1, close, blocks, speak_code=speak_code)
            index = close + 1

        elif kind == "table_open":
            close = _match(tokens, index, "table_close")
            blocks.extend(_table(tokens, index + 1, close))
            index = close + 1

        elif kind in ("fence", "code_block"):
            blocks.append(_code(token, speak_code=speak_code))
            index += 1

        elif kind == "html_block":
            stripped = _HTML_TAG.sub(" ", token.content)
            stripped = html.unescape(stripped).strip()
            if stripped:
                blocks.append(_sentence(stripped))
            index += 1

        elif kind == "inline":
            spoken = _inline([token])
            if spoken:
                blocks.append(_sentence(spoken))
            index += 1

        else:
            # hr, list_item_open/close, thead, and the rest carry no words.
            index += 1


def _match(tokens: list[Token], opening: int, closing_type: str) -> int:
    depth = 0
    opening_type = tokens[opening].type
    for index in range(opening, len(tokens)):
        if tokens[index].type == opening_type:
            depth += 1
        elif tokens[index].type == closing_type:
            depth -= 1
            if depth == 0:
                return index
    return len(tokens) - 1


def _list(
    tokens: list[Token],
    start: int,
    end: int,
    blocks: list[str],
    numbered: bool,
    first: int,
    *,
    speak_code: bool,
) -> None:
    counter = first
    index = start
    while index < end:
        if tokens[index].type != "list_item_open":
            index += 1
            continue
        close = _match(tokens, index, "list_item_close")
        _walk(
            tokens, index + 1, close, blocks,
            speak_code=speak_code,
            ordinal=counter if numbered else None,
        )
        counter += 1
        index = close + 1


def _checkbox(text: str) -> str:
    match = _CHECKBOX.match(text)
    if not match:
        return text
    rest = text[match.end() :]
    return f"{'Done' if match.group(1).lower() == 'x' else 'To do'}: {rest}"


def _code(token: Token, *, speak_code: bool) -> str:
    if speak_code:
        return _sentence(token.content)
    lines = len([line for line in token.content.splitlines() if line.strip()])
    language = (token.info or "").strip().split(" ")[0]
    if language and lines:
        return f"Code block in {language}, {lines} line{'s' if lines != 1 else ''}."
    if lines:
        return f"Code block, {lines} line{'s' if lines != 1 else ''}."
    return "Code block."


def _table(tokens: list[Token], start: int, end: int) -> list[str]:
    """Read a table as sentences, because rows and columns don't survive audio."""
    headers: list[str] = []
    rows: list[list[str]] = []
    current: list[str] | None = None
    in_head = False

    for index in range(start, end):
        token = tokens[index]
        if token.type == "thead_open":
            in_head = True
        elif token.type == "thead_close":
            in_head = False
        elif token.type == "tr_open":
            current = []
        elif token.type == "tr_close":
            if current:
                (headers.extend(current) if in_head else rows.append(current))
            current = None
        elif token.type == "inline" and current is not None:
            current.append(_inline([token]))

    if not headers and not rows:
        return []

    blocks: list[str] = []
    if headers:
        blocks.append(f"Table with columns: {', '.join(h for h in headers if h)}.")
    else:
        blocks.append("Table.")

    for number, row in enumerate(rows, start=1):
        if headers and len(headers) > 1:
            pairs = [
                f"{header}: {value}"
                for header, value in zip(headers, row, strict=False)
                if value
            ]
            spoken = ". ".join(pairs)
        else:
            spoken = ", ".join(value for value in row if value)
        if spoken:
            blocks.append(_sentence(f"Row {number}. {spoken}" if headers else spoken))
    return blocks


def _inline(tokens: list[Token]) -> str:
    parts: list[str] = []
    for token in tokens:
        parts.append(_inline_token(token))
    return _SPACES.sub(" ", "".join(parts)).strip()


def _inline_token(token: Token) -> str:
    kind = token.type

    if kind == "inline":
        return "".join(_inline_token(child) for child in (token.children or []))
    if kind in ("text", "code_inline"):
        return token.content
    if kind in ("softbreak", "hardbreak"):
        return " "
    if kind == "image":
        # The alt text is the only part of an image anyone can hear.
        alt = "".join(_inline_token(child) for child in (token.children or []))
        return f" {alt} " if alt.strip() else " "
    if kind == "html_inline":
        return " "
    if kind == "footnote_ref":
        return ""
    # strong, em, s, link and their closers: markers, not words.
    return ""
