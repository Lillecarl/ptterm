"""
What a program does after copy mode opened never reaches the copy.

Copy mode reads a copy of the buffer while the program runs on, and the
copy shares the rows of the history with the screen: copying fifty
thousand rows for every person who opens copy mode would cost what a
key press may not. That is right only while the program never writes a
row of the history in place. Lillecarl/pymux#470.

So each case here opens copy mode over a history, does one thing a
program or a person can do to the screen, and says the copy holds the
cells it held. **It compares cells and not text**: a writer that put an
equal looking cell in a shared row would still be a write. And it styles
every line again, past the cache, so the drawing is judged and not the
memory of an earlier one.
"""

from __future__ import annotations

import pytest
from no_backend import NoBackend
from pyte import escape
from pyte.modes import PrivateMode
from pyte.sequences import csi, set_mode

from ptterm.terminal import Terminal

LINES = 6
COLUMNS = 20

#: More lines than the screen, so most of them are history, and one
#: longer than the screen is wide, so a wrap mark is in it.
HISTORY = (
    "".join("history %d\r\n" % number for number in range(30))
    + csi(escape.SGR, 31)
    + "a red line that is longer than the pane\r\n"
    + csi(escape.SGR, 0)
    + "".join("screen %d\r\n" % number for number in range(LINES - 1))
)

#: Enough lines to scroll every row of the screen into the history.
MORE = "".join("later %d\r\n" % number for number in range(3 * LINES))


def _resize(lines, columns):
    def resize(control):
        control.create_content(columns, lines)

    return resize


def _feed(data):
    def feed(control):
        control.stream.feed(data)

    return feed


#: What a program or a person does to the screen, by name.
CHANGES = {
    "output": _feed(MORE),
    "erase the screen": _feed(csi(escape.ED, 2) + MORE),
    "erase the history": _feed(csi(escape.ED, 3)),
    "reset": _feed("\x1bc" + MORE),
    "the alternate screen": _feed(set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR) + MORE + "\x1b[?1049l" + MORE),
    "a scrolling region": _feed("\x1b[2;4r" + "\x1b[3S" + "\x1b[2T" + "\x1b[r" + MORE),
    "insert and delete lines": _feed("\x1b[H" + "\x1b[2L" + "\x1b[3M" + MORE),
    "reverse index at the top": _feed("\x1b[H" + "\x1bM" * 8 + "over the top" + MORE),
    "write over the screen": _feed("\x1b[H" + ("x" * COLUMNS + "\r\n") * LINES),
    "erase in line": _feed("\x1b[H" + "\x1b[2K\r\n" * LINES),
    "a hyperlink": _feed("\x1b]8;;https://example.com\x1b\\linked\x1b]8;;\x1b\\" + MORE),
    "narrower": _resize(LINES, COLUMNS - 7),
    "wider": _resize(LINES, COLUMNS + 9),
    "shorter": _resize(LINES - 3, COLUMNS),
    # A taller screen can take rows of the history back onto it, where
    # the program writes them in place.
    "taller, then written": lambda control: (
        control.create_content(COLUMNS, LINES + 4),
        control.stream.feed("\x1b[H" + ("y" * COLUMNS + "\r\n") * (LINES + 4)),
    ),
    "narrower, then taller, then written": lambda control: (
        control.create_content(COLUMNS - 7, LINES),
        control.create_content(COLUMNS - 7, LINES + 4),
        control.stream.feed("\x1b[H" + ("z" * COLUMNS + "\r\n") * (LINES + 4)),
    ),
}


def _what_the_copy_holds(view):
    "Each row's cells, the document, and every line styled from scratch."
    view._styled_lines = {}
    return (
        {number: row.image() for number, row in view.page.data_buffer.items()},
        view.buffer.text,
        [view.styled_line(number) for number in range(len(view.lines))],
    )


@pytest.mark.parametrize("change", CHANGES.values(), ids=CHANGES.keys())
def test_the_copy_holds_what_it_held(change):
    terminal = Terminal(backend=NoBackend())
    control = terminal.terminal_control
    control.create_content(COLUMNS, LINES)
    control.stream.feed(HISTORY)
    view = terminal.enter_copy_mode()
    before = _what_the_copy_holds(view)

    change(control)

    assert _what_the_copy_holds(view) == before


def test_a_history_at_its_limit_drops_rows_the_copy_keeps():
    "The limit takes rows off the top of the history, and the copy keeps them."
    terminal = Terminal(backend=NoBackend(), get_history_limit=lambda: 10)
    control = terminal.terminal_control
    control.create_content(COLUMNS, LINES)
    control.stream.feed(HISTORY)
    view = terminal.enter_copy_mode()
    before = _what_the_copy_holds(view)

    control.stream.feed(MORE * 20)

    assert min(control.screen.page.data_buffer) > min(view.page.data_buffer)
    assert _what_the_copy_holds(view) == before
