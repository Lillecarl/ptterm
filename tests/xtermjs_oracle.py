"""
Compare the screen of ptterm against xterm.js.

xterm.js is the terminal that VS Code draws in, written in TypeScript.
`@xterm/headless` is the same emulator with no drawing attached.
`PTTERM_XTERMJS` names a program that feeds it and reads the screen
back.

The judge is named `xtermjs` and not `xterm`, because `xterm_oracle.py`
drives xterm itself. The two are different emulators that share three
letters, and a panel that called one of them `xterm` read wrong.

**It answers about an underline.** The buffer API of xterm.js says
whether a cell carries a line and nothing more. The judge reaches past
it, to `getUnderlineStyle` and the underline colour, so xterm.js votes
on the shape of a line and on its colour like everybody else.

**It answers about a hyperlink.** `IBufferCell` reports none, and the
judge reaches past it: `cell.extended.urlId` is the name xterm.js gives
one link, and `_core._oscLinkService` turns that name into the target.
Both are private paths of the version the tests pin, and the judge says
so where it uses them.

**A link overwrites the shape of the line.** xterm.js draws a link as a
dashed underline and writes it into the cell. A link on its own reads as
no line, because the mark lives in the extended attributes and
`getUnderlineStyle` reaches them only when a program asked for a line
too. A link over a curly line reads as dashed, both ways round, and the
curl is gone. So `_as_xtermjs_sees` drops the whole underline of a
linked cell from both sides. It keeps the link.

A judge that cannot hold something has to say so. One that answers
anyway is worse than one that abstains, because the panel counts its
vote.
"""
from typing import List, Optional, Tuple

from kitty_oracle import Cell
from line_judge import LineJudge

__all__ = ["xtermjs_is_available", "xtermjs_cells", "_as_xtermjs_sees"]

_JUDGE = LineJudge("PTTERM_XTERMJS", ("xtermjs",))


def xtermjs_is_available() -> bool:
    "True when `PTTERM_XTERMJS` names a program that runs."
    return _JUDGE.is_available()


def xtermjs_cells(
    data: str, lines: int, columns: int, resize: Optional[Tuple[int, int]] = None
) -> List[List[Cell]]:
    "Feed `data` to xterm.js and read the screen back."
    return _JUDGE.cells("xtermjs", data, lines, columns, resize)


def _as_xtermjs_sees(cell: Cell) -> Cell:
    """
    The part of a cell that xterm.js can hold.

    A cell that carries a link keeps no underline, on either side.
    xterm.js marks a link with a dashed line and writes it over whatever
    the program asked for, so its answer there is its own decoration and
    not a reading of the program.
    `test_the_panel.py::test_a_link_overwrites_the_shape_of_a_line`
    holds the raw answer.

    It holds no baseline either. xterm.js has no "SGR 73", so every
    glyph sits on the line.
    """
    if cell.hyperlink is not None:
        return cell._replace(underline=0, underline_color=None, baseline=0)
    return cell._replace(baseline=0)
