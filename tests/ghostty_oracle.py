"""
Compare the screen of ptterm against Ghostty.

Ghostty keeps its terminal in libghostty-vt, a library with a C API
that is meant to be embedded. `tests/judges-c` reads a screen back
through it, and `PTTERM_GHOSTTY` names that program.

Ghostty holds everything a cell of ours holds: the shape of an
underline and the colour of the line included. So nothing is dropped
before the comparison, and this judge answers every question the panel
asks.
"""
from typing import List

from kitty_oracle import Cell
from line_judge import LineJudge

__all__ = ["ghostty_is_available", "ghostty_cells"]

_JUDGE = LineJudge("PTTERM_GHOSTTY", ("ghostty",))


def ghostty_is_available() -> bool:
    "True when `PTTERM_GHOSTTY` names a program that runs."
    return _JUDGE.is_available()


def ghostty_cells(data: str, lines: int, columns: int) -> List[List[Cell]]:
    "Feed `data` to Ghostty and read the screen back."
    return _JUDGE.cells("ghostty", data, lines, columns)
