"""
A backspace in the first column, and the two modes that let it wrap.

A backspace normally stops in the first column. Two private modes send
it to the end of the line above instead, so that a program can rub out
a line it wrapped:

- "?45" goes back only over a line that was reached by wrapping. The
  backspace undoes the typing and stops where the typing began.
- "?1045" goes back over any line, and from the top of the scrolling
  region to the bottom of it.

xterm carried only "?45", with the "?1045" behaviour, until 2023. It
then split the two apart, because a program that wanted to rub out a
wrapped line did not want the cursor leaving the line it typed.
"""
import pytest

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

#: A screen small enough to read, and wide enough to wrap on purpose.
LINES, COLUMNS = 6, 10

#: The sequences under test, so a test names the mode and not a number.
AUTOWRAP = "\x1b[?7h"
INLINE = "\x1b[?45h"
ANYWHERE = "\x1b[?1045h"
BACKSPACE = "\x08"


@pytest.fixture
def pane():
    screen = BetterScreen(LINES, COLUMNS, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    return screen, stream


def at(screen):
    "Where the cursor is, as the column and the row a report gives."
    return screen.reported_column, screen.pt_cursor_position.y


def test_a_backspace_in_the_first_column_stays_there(pane):
    screen, stream = pane
    stream.feed(AUTOWRAP + "\x1b[3;1H" + BACKSPACE)
    assert at(screen) == (0, 2)


def test_a_backspace_needs_autowrap_to_go_back(pane):
    # A terminal that does not wrap forward has nothing to unwrap.
    screen, stream = pane
    stream.feed("\x1b[?7l" + ANYWHERE + "\x1b[3;1H" + BACKSPACE)
    assert at(screen) == (0, 2)


# ----------------------------------------------------------------------
# "?1045": back over any line.


def test_the_wider_mode_goes_back_over_a_line_that_did_not_wrap(pane):
    screen, stream = pane
    stream.feed(AUTOWRAP + ANYWHERE + "\x1b[3;1H" + BACKSPACE)
    assert at(screen) == (COLUMNS - 1, 1)


def test_the_wider_mode_goes_from_the_first_row_to_the_last(pane):
    screen, stream = pane
    stream.feed(AUTOWRAP + ANYWHERE + "\x1b[1;1H" + BACKSPACE)
    assert at(screen) == (COLUMNS - 1, LINES - 1)


def test_the_wider_mode_stays_inside_the_scrolling_region(pane):
    # The region is rows 2 to 4, so the first row of it goes back to
    # the last row of it and not to the last row of the screen.
    screen, stream = pane
    stream.feed(AUTOWRAP + ANYWHERE + "\x1b[2;4r" + "\x1b[2;1H" + BACKSPACE)
    assert at(screen) == (COLUMNS - 1, 3)


def test_the_wider_mode_lands_on_the_right_margin(pane):
    screen, stream = pane
    stream.feed(AUTOWRAP + ANYWHERE + "\x1b[?69h" + "\x1b[3;6s")
    stream.feed("\x1b[3;3H" + BACKSPACE)
    assert at(screen) == (5, 1)


# ----------------------------------------------------------------------
# "?45": back only over a line that was reached by wrapping.


def test_the_inline_mode_stays_after_a_line_feed(pane):
    # "ESC E" moves to the next line without wrapping, so the line
    # below was not reached by typing and the backspace stops.
    screen, stream = pane
    stream.feed(AUTOWRAP + INLINE + "\x1b[1;1H" + "\x1bE" + BACKSPACE)
    assert at(screen) == (0, 1)


def test_the_inline_mode_goes_back_over_a_line_that_wrapped(pane):
    screen, stream = pane
    # Eleven characters on a screen ten wide: the eleventh wraps.
    stream.feed(AUTOWRAP + INLINE + "\x1b[1;1H" + "a" * (COLUMNS + 1))
    assert at(screen) == (1, 1)
    stream.feed(BACKSPACE + BACKSPACE)
    assert at(screen) == (COLUMNS - 1, 0)


def test_the_inline_mode_stops_where_the_typing_began(pane):
    # Two wrapped rows, then more backspaces than there are columns.
    # The cursor walks back to where the typing started and stops.
    screen, stream = pane
    stream.feed(AUTOWRAP + INLINE + "\x1b[2;1H" + "a" * (COLUMNS * 2 + 1))
    stream.feed(BACKSPACE * (COLUMNS * 4))
    assert at(screen) == (0, 1)


# ----------------------------------------------------------------------
# The wait to wrap.


def test_a_backspace_takes_back_the_column_that_was_written(pane):
    # After the last column is written the cursor waits to wrap: it
    # sits one column further, and the character it wrote is behind
    # it. A backspace takes back that character, not the one before.
    screen, stream = pane
    stream.feed(AUTOWRAP + "\x1b[1;%iH" % (COLUMNS - 1) + "ab")
    assert at(screen) == (COLUMNS - 1, 0)
    stream.feed(BACKSPACE + "X")
    assert screen.data_buffer[0][COLUMNS - 2].char == "X"
    assert screen.data_buffer[0][COLUMNS - 1].char == "b"
