"""Split text into sentence-sized pieces, one per subtitle cue."""

from __future__ import annotations

import re
from dataclasses import dataclass

from supertonic.utils import chunk_text

MAX_SEGMENT_CHARS = 200
MAX_SEGMENT_CHARS_KO = 120
MIN_SEGMENT_WEIGHT = 12  # below this a piece is a stub, not a line

# Latin terminators need trailing whitespace to count; CJK ones don't, because
# CJK text is written without spaces between sentences.
_TERMINATORS = r"[.!?…]"
_CJK_TERMINATORS = r"[。！？]"
_CLOSERS = r"[\"'”’»)\]】」』]*"

_SENTENCE_BREAK = re.compile(
    rf"(?<={_TERMINATORS}){_CLOSERS}\s+|(?<={_CJK_TERMINATORS}){_CLOSERS}"
)

# A line that ends on a terminator finished its sentence there.
_LINE_END = re.compile(rf"(?:{_TERMINATORS}|{_CJK_TERMINATORS}){_CLOSERS}$")

_CJK = re.compile(
    r"[　-〿぀-ヿ㐀-䶿一-鿿가-힯＀-￯]"
)

# Words that end in a period without ending a sentence.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "vs", "etc", "e.g",
    "i.e", "approx", "fig", "no", "vol", "dept", "inc", "ltd", "co", "corp",
    "univ", "est", "al", "ca", "cf", "op", "pp", "ed", "am", "pm",
}
_ABBREV_TAIL = re.compile(r"(?:^|\s)([A-Za-z][A-Za-z.]{0,7})\.$")


# What follows a piece, longest pause last. A block is what a blank line
# separates — a paragraph, a heading, a list item. A line is a single newline
# that meant something: one line of a list, of an address, of a poem.
SENTENCE = "sentence"
LINE = "line"
BLOCK = "block"


@dataclass(frozen=True)
class Segment:
    """One piece to speak, and what kind of break comes after it."""

    text: str
    ends: str = SENTENCE

    @property
    def ends_block(self) -> bool:
        return self.ends == BLOCK


def max_chars_for(lang: str | None) -> int:
    return MAX_SEGMENT_CHARS_KO if lang == "ko" else MAX_SEGMENT_CHARS


def _ends_on_abbreviation(text: str) -> bool:
    match = _ABBREV_TAIL.search(text.strip())
    if not match:
        return False
    return match.group(1).rstrip(".").lower() in _ABBREVIATIONS


def _weight(text: str) -> int:
    """Rough "how much line is this" measure.

    A five-character Chinese sentence carries as much as a dozen Latin
    characters, so CJK counts for more.
    """
    return len(text) + 2 * len(_CJK.findall(text))


def _join(left: str, right: str) -> str:
    if left and _CJK.match(left[-1]):
        return left + right
    return f"{left} {right}"


def segment_text(text: str, lang: str | None = None) -> list[str]:
    """The pieces to synthesize, as plain strings.

    Callers that also need to know where the paragraphs end want
    `segment_spans` instead.
    """
    return [span.text for span in segment_spans(text, lang)]


def segment_spans(text: str, lang: str | None = None) -> list[Segment]:
    """Return the pieces to synthesize, in order, each flagged with its break.

    Each piece becomes one subtitle cue, so the goal is a readable line: a whole
    sentence where possible, never longer than the model takes in one pass. The
    flag says what comes after it — another sentence, a new line, a new block —
    which is what the reader turns into a pause.
    """
    limit = max_chars_for(lang)
    blocks = [b for b in re.split(r"\n\s*\n+", text.strip()) if b.strip()]

    raw: list[Segment] = []
    for block in blocks:
        opened_block = len(raw)
        for line in _lines_of(block):
            opened_line = len(raw)
            buffer = ""
            for piece in _SENTENCE_BREAK.split(line):
                piece = (piece or "").strip()
                if not piece:
                    continue
                buffer = _join(buffer, piece) if buffer else piece
                if _ends_on_abbreviation(buffer):
                    continue  # "Dr." wasn't the end of anything
                raw.append(Segment(buffer))
                buffer = ""
            if buffer:
                raw.append(Segment(buffer))
            if len(raw) > opened_line:  # the last sentence of a line closes it
                raw[-1] = Segment(raw[-1].text, LINE)
        if len(raw) > opened_block:  # ...and the last line closes the block
            raw[-1] = Segment(raw[-1].text, BLOCK)

    segments: list[Segment] = []
    for sentence in _merge_stubs(raw, limit):
        if len(sentence.text) <= limit:
            segments.append(sentence)
            continue
        parts: list[str] = []
        for part in chunk_text(sentence.text, limit):
            parts.extend(_hard_wrap(part.strip(), limit))
        # Splitting one sentence creates no new breaks: only the last piece
        # still finishes what the whole sentence finished.
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            segments.append(Segment(part, sentence.ends if last else SENTENCE))
    if segments:
        return segments
    return [Segment(text.strip(), BLOCK)] if text.strip() else []


def _lines_of(block: str) -> list[str]:
    """Split a block where its newlines were meant, joining the rest.

    A newline is ambiguous. In text wrapped at some column it is nothing — the
    sentence carries on. In a list, an address or a poem it is the whole point.
    A line that finishes a sentence is taken at its word; anything else is
    treated as a wrap and joined to what follows, unless the block never
    finishes a sentence at all, which is what a list of fragments looks like.
    """
    lines = [line.strip() for line in block.split("\n")]
    lines = [re.sub(r"\s+", " ", line) for line in lines if line]
    if not lines:
        return []
    if not any(_finishes_a_sentence(line) for line in lines):
        return lines  # nothing here ends in a full stop: read it line by line

    out: list[str] = []
    buffer = ""
    for line in lines:
        buffer = _join(buffer, line) if buffer else line
        if _finishes_a_sentence(line):
            out.append(buffer)
            buffer = ""
    if buffer:
        out.append(buffer)
    return out


def _finishes_a_sentence(line: str) -> bool:
    return bool(_LINE_END.search(line)) and not _ends_on_abbreviation(line)


def _merge_stubs(sentences: list[Segment], limit: int) -> list[Segment]:
    """Glue fragments like "Yes." onto whatever follows them."""
    out: list[Segment] = []
    for sentence in sentences:
        if (
            out
            and out[-1].ends == SENTENCE  # never pull one line into the next
            and _weight(out[-1].text) < MIN_SEGMENT_WEIGHT
            and len(out[-1].text) + len(sentence.text) + 1 <= limit
        ):
            out[-1] = Segment(_join(out[-1].text, sentence.text), sentence.ends)
        else:
            out.append(sentence)
    # A trailing stub has nothing after it, so pull it back one.
    if (
        len(out) > 1
        and out[-2].ends == SENTENCE
        and _weight(out[-1].text) < MIN_SEGMENT_WEIGHT
        and len(out[-2].text) + len(out[-1].text) + 1 <= limit
    ):
        tail = out.pop()
        out[-1] = Segment(_join(out[-1].text, tail.text), tail.ends)
    return out


def _hard_wrap(text: str, limit: int) -> list[str]:
    """Last resort for text with no sentence breaks at all."""
    if len(text) <= limit:
        return [text] if text else []
    parts: list[str] = []
    current = ""
    for word in text.split(" "):
        while len(word) > limit:  # one absurdly long token
            if current:
                parts.append(current)
                current = ""
            parts.append(word[:limit])
            word = word[limit:]
        candidate = f"{current} {word}".strip()
        if len(candidate) > limit:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts
