"""How many people used the site, printed as a table.

    python -m oneread.stats --days 30

Reads what `visits.py` wrote and nothing else. It deliberately never calls
`init_db`: that runs DDL and re-segments older readings, which is not something
a second process should do to a live database while the app is serving.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from .db import session_scope
from .models import DailyCount

COLUMNS = ("day", "views", "visitors", "signups", "signins")

FOOTNOTE = (
    "visitors is per day and deliberately doesn't add up: the salt behind it is\n"
    "destroyed at midnight, so the same reader on two days is two visitors."
)


def rows(days: int) -> list[DailyCount]:
    """The most recent `days` rows, newest first."""
    with session_scope() as session:
        found = list(
            session.scalars(
                select(DailyCount).order_by(DailyCount.day.desc()).limit(days)
            )
        )
        session.expunge_all()
        return found


def render(counts: list[DailyCount]) -> str:
    if not counts:
        return "No counts yet."

    table = [
        [
            str(row.day),
            str(row.views),
            str(row.visitors),
            str(row.signups),
            str(row.signins),
        ]
        for row in counts
    ]
    # No total under `visitors`, because summing daily uniques is meaningless
    # and a column of numbers with one total under it invites exactly that.
    total = [
        "total",
        str(sum(row.views for row in counts)),
        "-",
        str(sum(row.signups for row in counts)),
        str(sum(row.signins for row in counts)),
    ]

    widths = [
        max(len(header), *(len(line[index]) for line in (*table, total)))
        for index, header in enumerate(COLUMNS)
    ]

    def line(cells: list[str] | tuple[str, ...]) -> str:
        head = cells[0].ljust(widths[0])
        rest = "  ".join(cell.rjust(widths[index + 1]) for index, cell in enumerate(cells[1:]))
        return f"{head}  {rest}".rstrip()

    rule = "-" * len(line(total))
    body = "\n".join(line(cells) for cells in table)
    return f"{line(COLUMNS)}\n{body}\n{rule}\n{line(total)}\n\n{FOOTNOTE}"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="oneread.stats", description="Site usage, one row per UTC day."
    )
    parser.add_argument("--days", type=int, default=30, help="how many days to show")
    days = max(1, parser.parse_args().days)
    try:
        counts = rows(days)
    except OperationalError:
        # A database from before the table existed. Not an error worth a stack.
        print("No counts yet.")
        return
    print(render(counts))


if __name__ == "__main__":
    main()
