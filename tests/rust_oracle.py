"""
Compare the screen of ptterm against WezTerm and Alacritty.

Both are written in Rust and both keep a screen model of their own,
which `tests/judges` reads back through a small program. One process
answers one request after another, because the hunt asks tens of
thousands of times.

`PTTERM_JUDGES` names that program. The tests skip when it is not set.

These two know everything that a cell of ours holds, the shape of an
underline and the colour of the line included, so nothing is dropped
before the comparison.

The shape of a cell, and the reader that turns a ptterm screen into
cells, live in `kitty_oracle`. This adds two more readers.
"""
from typing import List

from kitty_oracle import (
    Cell,
    as_seen,
    as_text,
    ptterm_cells,
)
from line_judge import LineJudge

__all__ = [
    "judges_are_available",
    "JUDGE_NAMES",
    "judge_cells",
    "judge_differences",
]

#: The emulators that the program answers for.
JUDGE_NAMES = ("wezterm", "alacritty")

_JUDGE = LineJudge("PTTERM_JUDGES", JUDGE_NAMES)


def judges_are_available() -> bool:
    "True when `PTTERM_JUDGES` names a program that runs."
    return _JUDGE.is_available()


def judge_cells(name: str, data: str, lines: int, columns: int) -> List[List[Cell]]:
    "Feed `data` to one of the judges and read the screen back."
    return _JUDGE.cells(name, data, lines, columns)


def _keeper(strict: bool, blank_style: bool):
    if strict:
        return lambda cell: cell
    return as_seen if blank_style else as_text


def judge_differences(
    name: str,
    data: str,
    lines: int = 6,
    columns: int = 20,
    strict: bool = False,
    blank_style: bool = True,
) -> List[str]:
    "Every cell where ptterm and one judge do not agree, as readable lines."
    ours = ptterm_cells(data, lines, columns)
    theirs = judge_cells(name, data, lines, columns)
    keep = _keeper(strict, blank_style)

    reported = []
    for y in range(lines):
        for x in range(columns):
            mine, other = keep(ours[y][x]), keep(theirs[y][x])
            if mine != other:
                reported.append(
                    "cell %d,%d: ptterm %r, %s %r" % (y, x, mine, name, other)
                )
    return reported
