"""
REP ("CSI Pn b"): draw the last character again.

It saves a program the bytes of a run of one character, which is what
a box or a rule is made of. The repeat draws the way the typing would
have, so it wraps at the right margin and scrolls at the bottom one.
"""
import pytest

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

LINES, COLUMNS = 5, 10


@pytest.fixture
def pane():
    screen = BetterScreen(LINES, COLUMNS, write_process_input=lambda data: None)
    return screen, BetterStream(screen)


def row(screen, index):
    "One row of the screen, with a space for a cell nobody wrote."
    line = screen.data_buffer[index]
    return "".join(line[column].char for column in range(COLUMNS))


def test_a_repeat_with_no_count_draws_one_more(pane):
    screen, stream = pane
    stream.feed("a\x1b[b")
    assert row(screen, 0) == "aa" + " " * (COLUMNS - 2)


def test_a_repeat_draws_the_count_it_is_given(pane):
    screen, stream = pane
    stream.feed("a\x1b[2b")
    assert row(screen, 0) == "aaa" + " " * (COLUMNS - 3)


def test_a_repeat_of_zero_draws_one(pane):
    # Zero is what an empty parameter gives, and an empty parameter
    # means the default.
    screen, stream = pane
    stream.feed("a\x1b[0b")
    assert row(screen, 0) == "aa" + " " * (COLUMNS - 2)


def test_a_repeat_before_anything_is_drawn_draws_nothing(pane):
    # There is no character to repeat, and a space would be a guess.
    screen, stream = pane
    stream.feed("\x1b[5b")
    assert row(screen, 0) == " " * COLUMNS
    assert screen.reported_column == 0


def test_a_repeat_takes_the_last_character_of_a_run(pane):
    screen, stream = pane
    stream.feed("abc\x1b[2b")
    assert row(screen, 0) == "abccc" + " " * (COLUMNS - 5)


def test_a_repeat_wraps_at_the_right_margin(pane):
    screen, stream = pane
    stream.feed("\x1b[?69h\x1b[2;4s")  # A region from column 2 to 4.
    stream.feed("\x1b[1;2Ha\x1b[3b")
    assert row(screen, 0) == " aaa" + " " * (COLUMNS - 4)
    assert row(screen, 1) == " a" + " " * (COLUMNS - 2)


def test_a_repeat_scrolls_at_the_bottom_margin(pane):
    screen, stream = pane
    stream.feed("\x1b[2;4r")  # A region from row 2 to 4.
    stream.feed("\x1b[4;%iHa" % (COLUMNS - 2))
    stream.feed("\x1b[3b")
    # The row that was full moved up, and the last repeat starts the
    # row below it.
    assert row(screen, 2) == " " * (COLUMNS - 3) + "aaa"
    assert row(screen, 3) == "a" + " " * (COLUMNS - 1)


def test_a_repeat_carries_the_rendition_that_is_set(pane):
    screen, stream = pane
    stream.feed("\x1b[31ma\x1b[2b")
    line = screen.data_buffer[0]
    assert row(screen, 0) == "aaa" + " " * (COLUMNS - 3)
    assert line[0].style == line[2].style
