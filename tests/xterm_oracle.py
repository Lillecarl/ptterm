"""
Compare the screen of ptterm against xterm.js.

xterm.js is the terminal that VS Code draws in, written in TypeScript.
`@xterm/headless` is the same emulator with no drawing attached.
`PTTERM_XTERM` names a program that feeds it and reads the screen back.

**It cannot answer about an underline.** The buffer API of xterm.js
says whether a cell carries a line and nothing more: not the shape of
the line, and not its colour. So this judge reports a line as a plain
single one, and `_as_xterm_sees` drops the shape and the colour from
both sides before the comparison.

A judge that cannot hold something has to say so. One that answers
anyway is worse than one that abstains, because the panel counts its
vote.
"""
from typing import List

from kitty_oracle import Cell
from line_judge import LineJudge

__all__ = ["xterm_is_available", "xterm_cells", "_as_xterm_sees"]

_JUDGE = LineJudge("PTTERM_XTERM", ("xterm",))


def xterm_is_available() -> bool:
    "True when `PTTERM_XTERM` names a program that runs."
    return _JUDGE.is_available()


def xterm_cells(data: str, lines: int, columns: int) -> List[List[Cell]]:
    "Feed `data` to xterm.js and read the screen back."
    return _JUDGE.cells("xterm", data, lines, columns)


def _as_xterm_sees(cell: Cell) -> Cell:
    "The part of a cell that xterm.js can hold."
    if cell.underline == 0 and cell.underline_color is None:
        return cell
    return cell._replace(
        underline=1 if cell.underline else 0,
        underline_color=None,
    )
