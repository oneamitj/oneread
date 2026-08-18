"""How long the reader waits between one piece and the next.

Three lengths, because a newline means three different things. Inside a
paragraph a full stop earns a breath, not a stop. A line of its own — a list
item, an address, a line of verse — earns more. A blank line earns most.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from .segmenter import BLOCK, LINE

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .segmenter import Segment

DEFAULT_SENTENCE_GAP_S = 0.15  # a breath at a full stop
DEFAULT_LINE_GAP_S = 0.35  # one line of a list, an address, a poem
DEFAULT_BLOCK_GAP_S = 0.55  # end of a paragraph, heading or list item

#: What the model leaves between two sentences it was given together. Measured
#: on supertonic-3: 0.24-0.42 s at a full stop, against 0.08-0.16 s at a comma.
#: Nothing sets this — it is what the model does — but an estimate has to allow
#: for it, because a chunked reading is that much longer than the words alone.
MODEL_INNER_GAP_S = 0.3


def gap_after(
    ends: str,
    *,
    sentence_s: float = DEFAULT_SENTENCE_GAP_S,
    line_s: float = DEFAULT_LINE_GAP_S,
    block_s: float = DEFAULT_BLOCK_GAP_S,
) -> float:
    """Seconds of silence to write after a piece."""
    if ends == BLOCK:
        return block_s
    if ends == LINE:
        return line_s
    return sentence_s


def total_gap_s(
    spans: Iterable[Segment],
    *,
    sentence_s: float = DEFAULT_SENTENCE_GAP_S,
    line_s: float = DEFAULT_LINE_GAP_S,
    block_s: float = DEFAULT_BLOCK_GAP_S,
) -> float:
    """Every gap in a run of pieces. The last one is followed by nothing."""
    pieces = list(spans)
    return sum(
        gap_after(span.ends, sentence_s=sentence_s, line_s=line_s, block_s=block_s)
        for span in pieces[:-1]
    )
