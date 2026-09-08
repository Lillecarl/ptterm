"""
The widget builds a row again only when the screen wrote it.

`_TerminalControl` keeps what it drew for each row and the write count
of the screen that it drew it at. A row whose count has not moved is a
row it hands back as it stands, so a frame after a program wrote one
line builds one line and not the whole screen. Lillecarl/pymux#126.

**A row that is kept and should not have been is a wrong screen, not a
slow one.** So this file does not check the rule. It runs two controls
side by side over what real programs wrote: one keeps what it drew,
and one is emptied before every frame so that it builds everything.
Every row of every frame has to match.

The two differ in nothing else. Neither builds `fragment` differently,
because both run the same code; the only question is which rows they
run it on.
"""
import asyncio
import pathlib

import pytest

from no_backend import NoBackend
from ptterm.terminal import _TerminalControl
from pyte import escape
from pyte.modes import PrivateMode
from pyte.sequences import csi, set_mode

CORPUS = pathlib.Path(__file__).parent / "corpus"

#: How much of a capture goes in at a time. A program writes over a pty
#: in pieces and a pane draws a frame between them, so this is where a
#: row that was kept and should not have been shows.
CHUNK = 256

LINES = 24
COLUMNS = 80


@pytest.fixture(autouse=True)
def _a_loop():
    "`Process` reads the running event loop, and pytest starts none."
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    asyncio.set_event_loop(None)
    loop.close()


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
    "One that keeps what it drew, and one that keeps nothing."
    controls = []
    for _ in range(2):
        control = _TerminalControl(backend=NoBackend())
        control.create_content(COLUMNS, LINES)
        controls.append(control)
    return controls


@pytest.mark.parametrize("name", _captures())
def test_a_real_program_draws_the_same_rows(name):
    text = (CORPUS / name).read_bytes().decode("utf-8", "replace")
    keeping, building = two_controls()

    for at in range(0, len(text), CHUNK):
        chunk = text[at:at + CHUNK]
        keeping.stream.feed(chunk)
        building.stream.feed(chunk)

        kept = frame(keeping, forget=False)
        built = frame(building, forget=True)
        assert kept == built, (
            "%s: the frame after byte %d differs on %d of %d rows"
            % (
                name,
                at + len(chunk),
                sum(1 for a, b in zip(kept, built) if a != b),
                len(built),
            )
        )


# ----------------------------------------------------------------------
# The two things outside a row that a row is drawn from.


def test_reverse_video_reaches_a_row_that_nothing_wrote():
    """
    DECSCNM belongs to the whole screen, and a row built before it was
    set says nothing about the screen after it. So what the control
    remembers goes when the mode turns.

    The cell a program already reversed is where it shows. `_Window`
    paints the reverse over the whole pane, so a plain cell needs
    nothing; a cell that "SGR 7" reversed turns the other way and is
    drawn "noreverse" to cancel it.
    """
    control = _TerminalControl(backend=NoBackend())
    control.create_content(COLUMNS, LINES)
    control.stream.feed("\x1b[7mhello")

    before = frame(control, forget=False)
    control.stream.feed(set_mode(PrivateMode.REVERSE_VIDEO))
    after = frame(control, forget=False)
    assert after == frame(control, forget=True)
    assert after != before


def test_the_row_the_cursor_stands_on_is_never_kept():
    """
    It is padded out to the column the cursor stands in, so its answer
    depends on where the cursor is and not only on what it holds.
    """
    control = _TerminalControl(backend=NoBackend())
    control.create_content(COLUMNS, LINES)
    control.stream.feed("hello")

    # The cursor moves along the row it already drew, and nothing is
    # written. A row that was kept would come back too short.
    control.stream.feed(csi(escape.CUP, 1, 20))
    assert frame(control, forget=False) == frame(control, forget=True)


def test_a_row_that_nothing_wrote_is_the_object_that_was_drawn():
    "The point of the whole thing: it is not built a second time."
    control = _TerminalControl(backend=NoBackend())
    control.create_content(COLUMNS, LINES)
    control.stream.feed("first\r\nsecond\r\nthird")

    content = control.create_content(COLUMNS, LINES)
    once = content.get_line(0)
    content = control.create_content(COLUMNS, LINES)
    assert content.get_line(0) is once


def test_a_row_that_was_written_is_built_again():
    control = _TerminalControl(backend=NoBackend())
    control.create_content(COLUMNS, LINES)
    control.stream.feed("first\r\nsecond")

    once = control.create_content(COLUMNS, LINES).get_line(0)
    control.stream.feed("\x1b[1;1Hagain")
    again = control.create_content(COLUMNS, LINES).get_line(0)
    assert again is not once
    assert again == control.create_content(COLUMNS, LINES).get_line(0)
