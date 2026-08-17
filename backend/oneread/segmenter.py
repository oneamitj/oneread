"""Split text into sentence-sized pieces, one per subtitle cue."""

from __future__ import annotations

import re

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
    """Return the pieces to synthesize, in order.

    Each piece becomes one subtitle cue, so the goal is a readable line: a whole
    sentence where possible, never longer than the model takes in one pass.
    """
    limit = max_chars_for(lang)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text.strip()) if p.strip()]

    raw: list[str] = []
    for paragraph in paragraphs:
        paragraph = re.sub(r"\s+", " ", paragraph)
        buffer = ""
        for piece in _SENTENCE_BREAK.split(paragraph):
            piece = (piece or "").strip()
            if not piece:
                continue
            buffer = _join(buffer, piece) if buffer else piece
            if _ends_on_abbreviation(buffer):
                continue  # "Dr." wasn't the end of anything
            raw.append(buffer)
            buffer = ""
        if buffer:
            raw.append(buffer)

    segments: list[str] = []
    for sentence in _merge_stubs(raw, limit):
        if len(sentence) <= limit:
            segments.append(sentence)
            continue
        for part in chunk_text(sentence, limit):
            segments.extend(_hard_wrap(part.strip(), limit))
    return segments or ([text.strip()] if text.strip() else [])


def _merge_stubs(sentences: list[str], limit: int) -> list[str]:
    """Glue fragments like "Yes." onto whatever follows them."""
    out: list[str] = []
    for sentence in sentences:
        if (
            out
            and _weight(out[-1]) < MIN_SEGMENT_WEIGHT
            and len(out[-1]) + len(sentence) + 1 <= limit
        ):
            out[-1] = _join(out[-1], sentence)
        else:
            out.append(sentence)
    # A trailing stub has nothing after it, so pull it back one.
    if len(out) > 1 and _weight(out[-1]) < MIN_SEGMENT_WEIGHT:
        if len(out[-2]) + len(out[-1]) + 1 <= limit:
            tail = out.pop()
            out[-1] = _join(out[-1], tail)
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
