"""
Inserting and deleting characters.

A blank that one of these leaves takes the background that is set, the
same way an erased cell does.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream
from ptterm.style import style_of


def _screen(lines=4, columns=8):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    return screen, stream


def _rows(screen):
    buffer = screen.page.data_buffer
    offset = screen.line_offset
    return [
        "".join(buffer[y][x].char for x in range(screen.columns)).rstrip()
        for y in range(offset, offset + screen.lines)
    ]


def _background(row, column):
    "The colour that one cell of a row is painted with, or None."
    return row[column].appearance.rendition.bgcolor


def test_inserted_characters_take_the_background():
    screen, stream = _screen()
    stream.feed("abcdef\x1b[1;3H\x1b[42m\x1b[2@")
    row = screen.page.data_buffer[screen.line_offset]
    assert row[0].char == "a"
    assert _background(row, 2) is not None and row[2].char == " "
    assert _background(row, 3) is not None
    assert row[4].char == "c"


def test_inserted_characters_fall_off_the_right_edge():
    screen, stream = _screen(columns=6)
    stream.feed("abcdef\x1b[1;1H\x1b[2@")
    assert _rows(screen) == ["  abcd", "", "", ""]


def test_deleted_characters_take_the_background_at_the_edge():
    screen, stream = _screen(columns=6)
    stream.feed("abcdef\x1b[1;1H\x1b[41m\x1b[2P")
    row = screen.page.data_buffer[screen.line_offset]
    assert row[0].char == "c"
    assert _background(row, 4) is not None and row[4].char == " "
    assert _background(row, 5) is not None
