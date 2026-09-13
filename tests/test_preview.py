"""
A drawing of a screen, for a chooser to show. Lillecarl/pymux#325.

The rules are tmux's, from `screen_write_preview` in `screen-write.c`:
the window follows the cursor, a third of the way in, and clamps to the
screen. A preview reads and never writes -- the screen it is a picture
of belongs to a program that nobody is looking at.
"""

import pytest

from prompt_toolkit.formatted_text import fragment_list_to_text

from ptterm.preview import preview_lines, preview_text
from pyte.screen import Screen
from pyte.streams import Stream


def screen_of(text: str, lines: int = 6, columns: int = 20) -> Screen:
    "A screen with this written on it."
    screen = Screen(lines, columns, write_process_input=lambda answer: None)
    Stream(screen).feed(text)
    return screen


def text_of(lines) -> list:
    "What each row draws, as plain text."
    return [fragment_list_to_text(line) for line in lines]


def test_the_rows_are_what_the_screen_holds():
    screen = screen_of("one\r\ntwo\r\nthree")
    assert text_of(preview_lines(screen, 6, 20))[:3] == ["one", "two", "three"]


def test_nothing_comes_back_for_no_room():
    screen = screen_of("one")
    assert preview_lines(screen, 0, 20) == []
    assert preview_lines(screen, 6, 0) == []


def test_a_row_is_cut_to_the_width():
    screen = screen_of("abcdefghij")
    # With no cursor to follow, the window is the top left one.
    screen.page.show_cursor = False
    assert text_of(preview_lines(screen, 6, 4)) == ["abcd"]


def test_fewer_rows_than_asked_for_when_the_screen_has_fewer():
    screen = screen_of("one\r\ntwo")
    assert len(preview_lines(screen, 6, 20)) == 2


def test_the_window_follows_the_cursor_down():
    """
    Twelve rows written on a screen of six, and a preview of two.

    The cursor is on the last row. A preview that started at the top of
    the screen would show the rows before it, which is the output a
    person is not waiting for.
    """
    screen = screen_of("\r\n".join("row%i" % i for i in range(12)), lines=6)
    shown = text_of(preview_lines(screen, 2, 20))
    assert "row11" in shown


def test_the_window_follows_the_cursor_right():
    "A long row, and a preview four columns wide."
    screen = screen_of("abcdefghijklmnop", columns=16)
    # The cursor waits at column 15, so the window starts a third of the
    # way in from there and clamps to the right edge of the screen.
    shown = text_of(preview_lines(screen, 6, 4))
    assert shown == ["mnop"]


def test_a_screen_with_no_cursor_starts_at_the_top_left():
    screen = screen_of("\r\n".join("row%i" % i for i in range(12)), lines=6)
    screen.page.show_cursor = False
    shown = text_of(preview_lines(screen, 2, 20))
    assert shown == ["row6", "row7"]


def test_the_style_of_a_cell_comes_with_it():
    screen = screen_of("\x1b[31mred")
    line = preview_lines(screen, 6, 20)[0]
    assert all("ansired" in style for style, _text in line)


def test_the_text_form_puts_a_newline_between_the_rows():
    screen = screen_of("one\r\ntwo")
    assert fragment_list_to_text(preview_text(screen, 6, 20)) == "one\ntwo"


def test_a_preview_writes_nothing_to_the_screen():
    """
    The screen belongs to a program. Asking what is on it must not
    make a row, move the cursor or touch a version: a chooser draws
    this on every frame while somebody scrolls through the list.
    """
    screen = screen_of("one\r\ntwo")
    before = dict(screen.page.data_buffer)
    cursor = screen.pt_cursor_position

    preview_lines(screen, 40, 200)

    assert dict(screen.page.data_buffer) == before
    assert screen.pt_cursor_position == cursor


@pytest.mark.parametrize("rows,columns", [(1, 1), (3, 7), (40, 200)])
def test_no_size_asks_for_a_row_the_buffer_does_not_have(rows, columns):
    "Every row that comes back is a row the screen really holds."
    screen = screen_of("one\r\ntwo\r\nthree")
    assert len(preview_lines(screen, rows, columns)) <= 3
