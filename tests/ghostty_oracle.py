"""
Compare the screen of ptterm against Ghostty.

Ghostty keeps its terminal in libghostty-vt, a library with a C API
that is meant to be embedded. `tests/judges-c` reads a screen back
through it, and `PTTERM_GHOSTTY` names that program.

Ghostty holds the rendition of a cell whole: the shape of an underline
and the colour of the line included.

**It answers where a link goes, and not which cells are one link.**
`ghostty_grid_ref_hyperlink_uri` hands over the target of an "OSC 8".
Nothing hands over the name that Ghostty gives that one link, so
`_as_ghostty_sees` drops the name from both sides and keeps the target.

Naming a link after its target would not fix that. It would decide, for
Ghostty, that two openings of one address are one link, and that is the
question the panel is being asked. See Lillecarl/pymux#92.

A judge that cannot hold something has to say so. One that answers
anyway is worse than one that abstains, because the panel counts its
vote.
"""
from typing import List, Optional, Tuple

from kitty_oracle import Cell
from line_judge import LineJudge

__all__ = ["ghostty_is_available", "ghostty_cells", "_as_ghostty_sees"]

_JUDGE = LineJudge("PTTERM_GHOSTTY", ("ghostty",))


def ghostty_is_available() -> bool:
    "True when `PTTERM_GHOSTTY` names a program that runs."
    return _JUDGE.is_available()


def ghostty_cells(
    data: str, lines: int, columns: int, resize: Optional[Tuple[int, int]] = None
) -> List[List[Cell]]:
    "Feed `data` to Ghostty and read the screen back."
    return _JUDGE.cells("ghostty", data, lines, columns, resize)


def _as_ghostty_sees(cell: Cell) -> Cell:
    "The part of a cell that libghostty-vt reports."
    if cell.hyperlink_id is None:
        return cell
    return cell._replace(hyperlink_id=None)
