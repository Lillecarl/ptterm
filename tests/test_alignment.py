"""
DECALN ("ESC # 8"): fill the screen with "E".

It is the alignment test of the DEC terminals, and a program that
checks a terminal starts with it. The pattern is the easy part; where
the cursor ends up is the part that the emulators disagree on.
"""
import pytest

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

from kitty_oracle import differences, kitty_is_available


def _screen(lines=4, columns=6):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream


def test_every_cell_holds_an_e():
    screen, stream = _screen()
    stream.feed("\x1b#8")
    buffer = screen.pt_screen.data_buffer
    for y in range(screen.line_offset, screen.line_offset + 4):
        assert "".join(buffer[y][x].char for x in range(6)) == "EEEEEE"


def test_the_cursor_goes_home():
    "The DEC manuals say so, and kitty does it."
    screen, stream = _screen()
    stream.feed("ab\x1b#8")
    assert (screen.pt_cursor_position.y, screen.pt_cursor_position.x) == (
        screen.line_offset,
        0,
    )


def test_the_pattern_covers_the_scrolling_region_too():
    "DECALN draws over the whole screen, region or no region."
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1b#8")
    buffer = screen.pt_screen.data_buffer
    for y in range(screen.line_offset, screen.line_offset + 4):
        assert "".join(buffer[y][x].char for x in range(6)) == "EEEEEE"


def test_the_margins_go_back_to_the_whole_screen():
    "The DEC manuals say so, and kitty does it."
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1b#8")
    assert screen.margins is None


@pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)
@pytest.mark.parametrize(
    "data",
    [
        "\x1b#8",
        "ab\x1b#8X",
        "\x1b[4d\x1b#8\n",
        "\x1b[2;3r\x1b#8X",
        "0\x1b#8\x1b[1;1r0",
        "\x1b[2;3r\x1b#8\x1bM",
        "\x1b[2;3r\x1b#8\x1b[?6hX",
        "\x1b[2;3r\x1b[?6h\x1b#8X",
    ],
)
def test_kitty_draws_the_same_screen(data):
    assert not differences(data, lines=4, columns=6)
