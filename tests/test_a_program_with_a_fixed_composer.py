"""
Copy mode reaches the transcript of a program that holds a composer.

codex, and every other ratatui program with an inline viewport, draws
a transcript above an input box that stays at the bottom of the pane.
It prints a finished message by setting a scrolling region from the
first row to the row above the box and feeding lines at the bottom of
that region. So the transcript leaves through the top of a region, and
never through the top of the screen.

The pane held none of it. A person scrolled a codex pane and got the
current screen, where plain kitty had the whole session. pyte dropped
the rows that left a region, whatever the region was, and every
terminal with a scrollback keeps the ones that leave a region starting
at the first row. Lillecarl/pymux#423.

This is the end of that story: the rows are history, and copy mode is
where a person reads them.
"""

import asyncio

import pytest

from no_backend import NoBackend
from ptterm.terminal import Terminal
from pyte import escape
from pyte.sequences import csi

LINES = 8
COLUMNS = 20

#: How many rows the input box holds at the bottom of the pane.
COMPOSER = 3

MESSAGES = 20


@pytest.fixture(autouse=True)
def _a_loop():
    "`Process` reads the running event loop, and pytest starts none."
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    asyncio.set_event_loop(None)
    loop.close()


def _what_a_composer_draws() -> str:
    """
    A screenful, then a transcript printed above a fixed input box.

    The region ends one row above the box, the cursor stands on the
    last row of it, and each message is a linefeed there.
    """
    region = LINES - COMPOSER
    data = ["\r\n".join("filler %d" % row for row in range(LINES))]
    data.append(csi(escape.DECSTBM, 1, region))
    data.append(csi(escape.CUP, region, 1))
    for number in range(MESSAGES):
        data.append("\r\nmessage %d" % number)
    data.append(csi(escape.DECSTBM))
    for row in range(COMPOSER):
        data.append(csi(escape.CUP, region + 1 + row, 1) + "composer %d" % row)
    return "".join(data)


def _a_terminal(data: str) -> Terminal:
    terminal = Terminal(backend=NoBackend())
    control = terminal.terminal_control
    control.create_content(COLUMNS, LINES)
    control.stream.feed(data)
    terminal.copy_reverse_video = control.screen.has_reverse_video
    terminal.read_the_screen_into_the_copy_buffer()
    return terminal


def test_copy_mode_holds_every_message():
    terminal = _a_terminal(_what_a_composer_draws())
    lines = terminal.copy_buffer.document.text.splitlines()

    for number in range(MESSAGES):
        assert "message %d" % number in lines


def test_the_composer_is_the_bottom_of_the_pane_and_not_the_document():
    "The box the program holds still stands where it drew it."
    terminal = _a_terminal(_what_a_composer_draws())
    screen = terminal.terminal_control.screen
    offset = screen.line_offset

    bottom = [
        "".join(
            screen.page.data_buffer[offset + row][column].char
            for column in range(COLUMNS)
        ).rstrip()
        for row in range(LINES - COMPOSER, LINES)
    ]
    assert bottom == ["composer %d" % row for row in range(COMPOSER)]


def test_the_history_grew_by_one_row_for_each_message():
    terminal = _a_terminal(_what_a_composer_draws())
    screen = terminal.terminal_control.screen

    # The screen was full before the first message, so every one of
    # them pushed exactly one row out of the top of the region.
    assert screen.line_offset == MESSAGES
