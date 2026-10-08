"""
What a scroll moves is drawn where it lands, not built again.

A program scrolls a region and the rows already stand in order, so
`_TerminalControl` moves what it drew for them along instead of
building every row again. Only the rows the scroll uncovers are
built, and a row written after the scroll stays where it is.

**A row that is kept and should not have been is a wrong screen, not
a slow one.** So, like `test_the_rows_that_changed.py`, this runs two
controls side by side over what real programs wrote: one rotates what
it drew, and one is emptied before every frame so that it builds
everything. Every row of every frame has to match.
Lillecarl/pymux#516.
"""

from __future__ import annotations

import pathlib

import pytest
from no_backend import NoBackend
from pyte import escape
from pyte.sequences import Csi, csi

from ptterm.terminal import _TerminalControl

CORPUS = pathlib.Path(__file__).parent / "corpus"

#: How much of a capture goes in at a time. A program writes over a pty
#: in pieces and a pane draws a frame between them, so this is where a
#: row that was kept and should not have been shows.
CHUNK = 256

LINES = 24
COLUMNS = 80


def _captures():
    return sorted(path.name for path in CORPUS.glob("*.bin"))


def frame(control, forget: bool):
    """
    One frame of a control, as the rows a person would see.

    `forget` empties what the control remembers first, which makes it
    build every row.
    """
    if forget:
        control._drawn.clear()
        control._drawn_at.clear()

    content = control.create_content(COLUMNS, LINES)
    first = max(0, content.line_count - LINES)
    return [content.get_line(number) for number in range(first, content.line_count)]


def two_controls():
    "One that rotates what it drew, and one that keeps nothing."
    controls = []
    for _ in range(2):
        control = _TerminalControl(backend=NoBackend())
        control.create_content(COLUMNS, LINES)
        controls.append(control)
    return controls


@pytest.mark.parametrize("name", _captures())
def test_a_real_program_scrolls_the_same_rows(name):
    text = (CORPUS / name).read_bytes().decode("utf-8", "replace")
    keeping, building = two_controls()

    for at in range(0, len(text), CHUNK):
        chunk = text[at : at + CHUNK]
        keeping.stream.feed(chunk)
        building.stream.feed(chunk)

        kept = frame(keeping, forget=False)
        built = frame(building, forget=True)
        assert kept == built, "%s: the frame after byte %d differs on %d of %d rows" % (
            name,
            at + len(chunk),
            sum(1 for a, b in zip(kept, built) if a != b),
            len(built),
        )


# ----------------------------------------------------------------------
# What rotation keeps, moves, and rebuilds.


def _control(lines=6, columns=10):
    control = _TerminalControl(backend=NoBackend())
    control.create_content(columns, lines)
    return control


def _feed(control, text):
    control.stream.feed(text)


def _rows(control, columns=10, lines=6):
    content = control.create_content(columns, lines)
    return [content.get_line(number) for number in range(content.line_count)]


def test_scrolled_rows_are_the_objects_that_were_drawn():
    """
    The point of the whole thing: a region scroll moves what was
    drawn along, and no row in it is built again.
    """
    control = _control()
    _feed(control, "a\r\nb\r\nc\r\nd\r\ne")
    before = _rows(control)
    _feed(control, csi(escape.DECSTBM, 2, 4) + csi(Csi.SU, 1))
    after = _rows(control)

    assert after[1] is before[2]
    assert after[2] is before[3]
    assert "".join(text for _, text in after[1]) == "c"
    assert "".join(text for _, text in after[2]) == "d"


def test_uncovered_rows_are_built_again():
    """
    The row the scroll brings in has no past: it is built, and what
    fell out of the region is forgotten.
    """
    control = _control()
    _feed(control, "a\r\nb\r\nc\r\nd\r\ne")
    before = _rows(control)
    _feed(control, csi(escape.DECSTBM, 2, 4) + csi(Csi.SU, 1))
    after = _rows(control)

    assert after[3] is not before[3]
    assert "".join(text for _, text in after[3]).strip() == ""


def test_a_row_written_after_the_scroll_stays_where_it_is():
    """
    Rotation is for rows no later write touched. A row written after
    the scroll carries a larger count: it stays where it is and is
    built again, and the row its content left rebuilds too.
    """
    control = _control()
    _feed(control, "a\r\nb\r\nc\r\nd\r\ne")
    before = _rows(control)
    _feed(control, csi(escape.DECSTBM, 2, 4) + csi(Csi.SU, 1))
    _feed(control, csi(escape.CUP, 3, 1) + "z")
    after = _rows(control)

    assert "".join(text for _, text in after[2]).startswith("z")
    assert "".join(text for _, text in after[1]) == "c"
    assert after[1] is not before[1]
    assert after[1] is not before[2]
    assert after[2] is not before[2]


def _visible(control, columns=10, lines=6):
    "The rows on the screen, oldest visible first."
    content = control.create_content(columns, lines)
    first = max(0, content.line_count - lines)
    return [content.get_line(number) for number in range(first, content.line_count)]


def test_a_slide_keeps_its_rows_where_they_are():
    """
    A full screen scroll slides the screen over the buffer: the rows
    do not move, so there is nothing to rotate with and everything
    stays valid where it is. The row that was second is the first
    thing seen, and it is the same object.
    """
    control = _control()
    _feed(control, "a\r\nb\r\nc\r\nd\r\ne\r\nf")
    before = _visible(control)
    _feed(control, "\r\n")
    after = _visible(control)

    assert ["".join(text for _, text in row) for row in after[:5]] == ["b", "c", "d", "e", "f"]
    for number in range(4):
        assert after[number] is before[number + 1]
