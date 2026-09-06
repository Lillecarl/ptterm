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

**It cannot answer about a hyperlink either.** `IBufferCell` reports
none. xterm.js holds a link out of sight, behind a link service of its
own, and reaching for that would tie the judge to a private path that
the next version moves. So the link goes the same way as the shape of
the line.

What it does report is an underline on every cell of a link. That is
how xterm.js marks one, and its API cannot tell that line from one that
a program drew. So through this judge a linked cell and an underlined
cell are one cell, and `_as_xterm_sees` reads a link on either side as
a line.

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
    """
    The part of a cell that xterm.js can hold.

    A cell of a link reads as an underlined cell, on both sides. That is
    not a guess about what ptterm should draw: it is what this judge
    reports either way, and a comparison that kept the two apart would
    report the mark of xterm.js as a difference in the rendition.
    `test_the_panel.py::test_xterm_js_marks_a_link_with_an_underline`
    holds the raw answer.
    """
    return cell._replace(
        underline=1 if (cell.underline or cell.hyperlink is not None) else 0,
        underline_color=None,
        hyperlink=None,
        hyperlink_id=None,
    )
