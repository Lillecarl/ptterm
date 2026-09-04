"""
Inserting and deleting lines.

An empty line that one of these leaves takes the background that is
set, the same way an erased cell does.
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


def test_insert_lines_leaves_the_lines_above_the_cursor():
    # "CSI 2 L" on the second row used to drag the first row down.
    screen, stream = _screen(lines=5)
    stream.feed("a\r\nb\r\nc\r\nd\x1b[2;1H\x1b[2L")
    assert _rows(screen) == ["a", "", "", "b", "c"]


def test_insert_lines_by_one():
    screen, stream = _screen(lines=5)
    stream.feed("a\r\nb\r\nc\r\nd\x1b[2;1H\x1b[1L")
    assert _rows(screen) == ["a", "", "b", "c", "d"]


def test_delete_lines_moves_the_lines_below_up():
    screen, stream = _screen(lines=5)
    stream.feed("a\r\nb\r\nc\r\nd\x1b[2;1H\x1b[2M")
    assert _rows(screen) == ["a", "d", "", "", ""]


def _cursor(screen):
    return (screen.pt_cursor_position.y - screen.line_offset,
            screen.pt_cursor_position.x)


def test_delete_lines_moves_the_cursor_to_the_first_column():
    screen, stream = _screen()
    stream.feed("ab\r\ncd\x1b[1;2H\x1b[1M")
    assert _cursor(screen) == (0, 0)


def test_insert_lines_moves_the_cursor_to_the_first_column():
    screen, stream = _screen()
    stream.feed("ab\r\ncd\x1b[1;2H\x1b[1L")
    assert _cursor(screen) == (0, 0)
