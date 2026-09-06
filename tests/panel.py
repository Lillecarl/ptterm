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
xterm.js says only whether a line is there. libvterm, Ghostty and
xterm.js hold no hyperlink: the two libraries name none in their
headers, and the buffer API of xterm.js reports none. Their answers are
read through a projection that drops what they cannot hold.

A judge that cannot hold the difference in front of it does not vote.
It **abstains**, which is not the same as agreeing: `abstained()` tells
the two apart. The raw answers differ and the projection makes them
equal, so the difference is exactly what that judge misses.

`verdict()` says one of:

- "agree": every judge draws what ptterm draws.
- "ptterm-wrong": every judge that can see the difference differs from
  ptterm, and those judges agree with each other. Nobody has to decide
  anything.
- "split": the judges that can see it do not agree with each other, so
  the difference is a choice and not a bug.
"""
from typing import Callable, Dict, List, NamedTuple, Optional

from kitty_oracle import Cell, as_seen, as_text, kitty_is_available, ptterm_cells

__all__ = ["Judge", "judges", "verdict", "report", "abstained"]


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
        from ghostty_oracle import (
            _as_ghostty_sees,
            ghostty_cells,
            ghostty_is_available,
        )
    except ImportError:
        pass
    else:
        if ghostty_is_available():
            found.append(Judge("ghostty", ghostty_cells, _as_ghostty_sees))

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


class _Answer(NamedTuple):
    "What one judge says about one program."
    #: Every cell where the judge and ptterm differ, as readable lines.
    found: List[str]
    #: The judge, as this comparison reads it.
    screen: List[List[Cell]]
    #: True when the two screens differ and the projection hides it.
    #: The judge cannot hold what the difference is about, so it says
    #: nothing and does not vote.
    blind: bool


def _ask(
    data: str, lines: int, columns: int, keep, panel: List[Judge]
) -> Dict[str, _Answer]:
    "Put one program to every judge, and read each answer."
    ours = [[keep(cell) for cell in row] for row in ptterm_cells(data, lines, columns)]

    answers = {}
    for judge in panel:
        project = judge.projection or (lambda cell: cell)
        theirs = [
            [keep(cell) for cell in row] for row in judge.cells(data, lines, columns)
        ]
        found = []
        raw_differs = False
        for y in range(lines):
            for x in range(columns):
                mine, other = ours[y][x], theirs[y][x]
                if mine != other:
                    raw_differs = True
                seen, shown = project(mine), project(other)
                if seen != shown:
                    found.append(
                        "cell %d,%d: ptterm %r, %s %r" % (y, x, seen, judge.name, shown)
                    )
        answers[judge.name] = _Answer(found, theirs, raw_differs and not found)
    return answers


def report(
    data: str,
    lines: int = 6,
    columns: int = 20,
    strict: bool = False,
    blank_style: bool = True,
) -> Dict[str, List[str]]:
    """
    What every judge says about one program, as readable lines.

    A judge with an empty list draws what ptterm draws, or holds nothing
    that says otherwise. `abstained()` tells those two apart.
    """
    panel = judges()
    assert panel, "no judge is available"
    keep = _keeper(strict, blank_style)
    return {
        name: answer.found
        for name, answer in _ask(data, lines, columns, keep, panel).items()
    }


def abstained(
    data: str,
    lines: int = 6,
    columns: int = 20,
    strict: bool = False,
    blank_style: bool = True,
) -> List[str]:
    """
    The judges that cannot see the difference, in name order.

    Such a judge draws something else than ptterm and the projection
    drops the part that differs, so its answer is not an opinion. It is
    the absence of one.
    """
    panel = judges()
    assert panel, "no judge is available"
    keep = _keeper(strict, blank_style)
    answers = _ask(data, lines, columns, keep, panel)
    return sorted(name for name, answer in answers.items() if answer.blind)


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
    answers = _ask(data, lines, columns, keep, panel)

    voting = [judge for judge in panel if not answers[judge.name].blind]
    against = [judge for judge in voting if answers[judge.name].found]
    if not against:
        return "agree"
    if len(against) < len(voting):
        return "split"

    #: What every judge that votes can hold. A comparison of those
    #: judges against each other has to drop what any of them misses.
    #: The judges that abstain are not in it: their projections would
    #: drop the very thing that the vote is about.
    def common(cell: Cell) -> Cell:
        for judge in voting:
            if judge.projection is not None:
                cell = judge.projection(cell)
        return cell

    def project(rows):
        return [[common(cell) for cell in row] for row in rows]

    # Every judge that can see the difference differs from ptterm. They
    # only answer the question when they also agree with each other.
    first = project(answers[voting[0].name].screen)
    for judge in voting[1:]:
        if project(answers[judge.name].screen) != first:
            return "split"
    return "ptterm-wrong"
