"""
SU and SD move the lines of the scrolling region, and leave the cursor.

pyte has neither. A program that scrolls with "CSI S" instead of a
linefeed saw nothing happen before.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def _screen(lines=4, columns=8):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    return screen, stream


def _rows(screen):
    buffer = screen.pt_screen.data_buffer
    offset = screen.line_offset
    return [
        "".join(buffer[y][x].char for x in range(screen.columns)).rstrip()
        for y in range(offset, offset + screen.lines)
    ]


def test_scroll_up_moves_the_lines_up():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc\x1b[1S")
    assert _rows(screen) == ["b", "c", "", ""]


def test_scroll_up_takes_a_count():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc\x1b[2S")
    assert _rows(screen) == ["c", "", "", ""]


def test_scroll_down_moves_the_lines_down():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc\x1b[2T")
    assert _rows(screen) == ["", "", "a", "b"]


def test_a_count_past_the_screen_clears_it():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc\x1b[9S")
    assert _rows(screen) == ["", "", "", ""]


def test_scrolling_stays_inside_the_margins():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc\r\nd\x1b[2;3r\x1b[1S")
    assert _rows(screen) == ["a", "c", "", "d"]


def test_the_cursor_does_not_move():
    screen, stream = _screen()
    stream.feed("a\r\nb\x1b[1;3H\x1b[1S")
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (2, 0)
