"""
The panel: every judge that is there, and what they say together.

ptterm is not a judge. It is the thing on trial, so the vote is taken
among emulators that other people wrote:

- kitty, in C, through the python extension that kitty ships.
- WezTerm and Alacritty, in Rust, through `tests/judges`.
- libvterm, in C, the one that Vim and Neovim carry.
- Ghostty, in Zig, through libghostty-vt and `tests/judges-c`.
- xterm.js, in TypeScript, the one VS Code draws in, through
  `tests/judges-js`.

Each comes from a different line, which is the point. A difference
from one judge is a question; a difference from all of them is an
answer.

A judge that cannot hold something says nothing about it. libvterm
knows three shapes of underline and no colour for the line, and
xterm.js says only whether a line is there. Their answers are read
through a projection that drops what they cannot hold. kitty, Ghostty
and the two written in Rust hold everything a cell of ours holds.

`verdict()` says one of:

- "agree": every judge draws what ptterm draws.
- "ptterm-wrong": every judge differs from ptterm, and the judges
  agree with each other. Nobody has to decide anything.
- "split": the judges do not agree with each other, so the difference
  is a choice and not a bug.
"""
from typing import Callable, Dict, List, NamedTuple, Optional

from kitty_oracle import Cell, as_seen, as_text, kitty_is_available, ptterm_cells

__all__ = ["Judge", "judges", "verdict", "report"]


class Judge(NamedTuple):
    "One emulator, and what it can hold."
    name: str
    #: Feed data to it and read the screen back.
    cells: Callable[[str, int, int], List[List[Cell]]]
    #: Drop what this judge cannot hold, or None when it holds all.
    projection: Optional[Callable[[Cell], Cell]]


def judges() -> List[Judge]:
    "Every judge that this machine can run, in a stable order."
    found = []

    if kitty_is_available():
        from kitty_oracle import kitty_cells

        found.append(Judge("kitty", kitty_cells, None))

    try:
        from rust_oracle import JUDGE_NAMES, judge_cells, judges_are_available
    except ImportError:
        pass
    else:
        if judges_are_available():
            for name in JUDGE_NAMES:
                found.append(
                    Judge(
                        name,
                        lambda data, lines, columns, name=name: judge_cells(
                            name, data, lines, columns
                        ),
                        None,
                    )
                )

    try:
        from vterm_oracle import _as_libvterm_sees, libvterm_is_available, vterm_cells
    except ImportError:
        pass
    else:
        if libvterm_is_available():
            found.append(Judge("libvterm", vterm_cells, _as_libvterm_sees))

    try:
        from ghostty_oracle import ghostty_cells, ghostty_is_available
    except ImportError:
        pass
    else:
        if ghostty_is_available():
            found.append(Judge("ghostty", ghostty_cells, None))

    try:
        from xterm_oracle import _as_xterm_sees, xterm_cells, xterm_is_available
    except ImportError:
        pass
    else:
        if xterm_is_available():
            found.append(Judge("xterm", xterm_cells, _as_xterm_sees))

    return found


def _keeper(strict: bool, blank_style: bool) -> Callable[[Cell], Cell]:
    if strict:
        return lambda cell: cell
    return as_seen if blank_style else as_text


def _screens(
    data: str, lines: int, columns: int, keep, panel: List[Judge]
) -> Dict[str, List[List[Cell]]]:
    return {
        judge.name: [[keep(cell) for cell in row] for row in judge.cells(data, lines, columns)]
        for judge in panel
    }


def report(
    data: str,
    lines: int = 6,
    columns: int = 20,
    strict: bool = False,
    blank_style: bool = True,
) -> Dict[str, List[str]]:
    """
    What every judge says about one program, as readable lines.

    A judge with an empty list draws what ptterm draws.
    """
    panel = judges()
    assert panel, "no judge is available"
    keep = _keeper(strict, blank_style)
    ours = [[keep(cell) for cell in row] for row in ptterm_cells(data, lines, columns)]

    answers = {}
    for judge in panel:
        project = judge.projection or (lambda cell: cell)
        theirs = judge.cells(data, lines, columns)
        found = []
        for y in range(lines):
            for x in range(columns):
                mine = project(ours[y][x])
                other = project(keep(theirs[y][x]))
                if mine != other:
                    found.append(
                        "cell %d,%d: ptterm %r, %s %r" % (y, x, mine, judge.name, other)
                    )
        answers[judge.name] = found
    return answers


def verdict(
    data: str,
    lines: int = 6,
    columns: int = 20,
    strict: bool = False,
    blank_style: bool = True,
) -> str:
    "What the panel says: agree, ptterm-wrong or split."
    panel = judges()
    assert panel, "no judge is available"
    keep = _keeper(strict, blank_style)
    ours = [[keep(cell) for cell in row] for row in ptterm_cells(data, lines, columns)]
    screens = _screens(data, lines, columns, keep, panel)

    #: What every judge in this panel can hold. A comparison of the
    #: judges against each other has to drop what any of them misses.
    def common(cell: Cell) -> Cell:
        for judge in panel:
            if judge.projection is not None:
                cell = judge.projection(cell)
        return cell

    def project(rows, function):
        return [[function(cell) for cell in row] for row in rows]

    against = [
        judge.name
        for judge in panel
        if project(ours, judge.projection or (lambda cell: cell))
        != project(screens[judge.name], judge.projection or (lambda cell: cell))
    ]
    if not against:
        return "agree"
    if len(against) < len(panel):
        return "split"

    # Every judge differs from ptterm. They only answer the question
    # when they also agree with each other.
    first = project(screens[panel[0].name], common)
    for judge in panel[1:]:
        if project(screens[judge.name], common) != first:
            return "split"
    return "ptterm-wrong"
