"""
Private mode 41: the tab that `more` wrote at the end of a row.

A character in the last column leaves the cursor waiting to wrap. A
tab leaves that wait alone, so the tab moves nothing. `more` drew a
full row and then wrote a tab, and lost it that way. xterm added a
mode that makes the tab wrap first.

The mode is off unless a program asks for it, so the ordinary tab is
unchanged.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

MORE_FIX = "\x1b[?41h"


def make_screen(lines=4, columns=16):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    return screen, BetterStream(screen)


def fill_the_row_and_tab(stream, columns=16):
    stream.feed("x" * columns + "\t")


def test_a_tab_after_a_full_row_stands_still_by_default():
    screen, stream = make_screen()
    fill_the_row_and_tab(stream)
    assert screen.pt_cursor_position.y == 0
    assert screen.pt_cursor_position.x == 16


def test_the_mode_makes_the_tab_wrap_first():
    screen, stream = make_screen()
    stream.feed(MORE_FIX)
    fill_the_row_and_tab(stream)
    assert screen.pt_cursor_position.y == 1
    assert screen.pt_cursor_position.x == 8


def test_what_comes_after_the_tab_lands_on_the_new_row():
    screen, stream = make_screen()
    stream.feed(MORE_FIX)
    fill_the_row_and_tab(stream)
    stream.feed("1")
    assert screen.data_buffer[1][8].char == "1"


def test_the_mode_leaves_a_tab_that_is_not_at_the_edge_alone():
    screen, stream = make_screen()
    stream.feed(MORE_FIX + "ab\t")
    assert screen.pt_cursor_position.y == 0
    assert screen.pt_cursor_position.x == 8


def test_a_reset_of_the_mode_brings_the_old_tab_back():
    screen, stream = make_screen()
    stream.feed(MORE_FIX + "\x1b[?41l")
    fill_the_row_and_tab(stream)
    assert screen.pt_cursor_position.y == 0
    assert screen.pt_cursor_position.x == 16


def test_the_row_the_tab_left_counts_as_wrapped():
    "A backspace with reverse wraparound on steps back over it."
    screen, stream = make_screen()
    stream.feed(MORE_FIX + "\x1b[?45h")
    fill_the_row_and_tab(stream)
    stream.feed("\x1b[1G\x08")
    assert screen.pt_cursor_position.y == 0
    assert screen.pt_cursor_position.x == 15
