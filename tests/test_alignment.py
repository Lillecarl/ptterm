"""
DECALN ("ESC # 8"): fill the screen with "E".

It is the alignment test of the DEC terminals, and a program that
checks a terminal starts with it. The pattern is the easy part; where
the cursor ends up is the part that the emulators disagree on.
"""

import pytest

from pyte.screen import Screen
from pyte.streams import Stream

from kitty_oracle import differences, kitty_is_available
from pyte.sequences import Sharp, sharp
from pyte import escape
from pyte.sequences import csi, esc
from pyte.modes import PrivateMode
from pyte.sequences import set_mode


def _screen(lines=4, columns=6):
    screen = Screen(lines, columns, write_process_input=lambda data: None)
    stream = Stream(screen)
    return screen, stream


def test_every_cell_holds_an_e():
    screen, stream = _screen()
    stream.feed(sharp(Sharp.DECALN))
    buffer = screen.page.data_buffer
    for y in range(screen.line_offset, screen.line_offset + 4):
        assert "".join(buffer[y][x].char for x in range(6)) == "EEEEEE"


def test_the_cursor_goes_home():
    "The DEC manuals say so, and kitty does it."
    screen, stream = _screen()
    stream.feed("ab" + sharp(Sharp.DECALN))
    assert (screen.pt_cursor_position.y, screen.pt_cursor_position.x) == (
        screen.line_offset,
        0,
    )


def test_the_pattern_covers_the_scrolling_region_too():
    "DECALN draws over the whole screen, region or no region."
    screen, stream = _screen()
    stream.feed(csi(escape.DECSTBM, 2, 3) + sharp(Sharp.DECALN))
    buffer = screen.page.data_buffer
    for y in range(screen.line_offset, screen.line_offset + 4):
        assert "".join(buffer[y][x].char for x in range(6)) == "EEEEEE"


def test_the_margins_go_back_to_the_whole_screen():
    "The DEC manuals say so, and kitty does it."
    screen, stream = _screen()
    stream.feed(csi(escape.DECSTBM, 2, 3) + sharp(Sharp.DECALN))
    assert screen.margins is None


@pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)
@pytest.mark.parametrize(
    "data",
    [
        sharp(Sharp.DECALN),
        "ab" + sharp(Sharp.DECALN) + "X",
        csi(escape.VPA, 4) + sharp(Sharp.DECALN) + "\n",
        csi(escape.DECSTBM, 2, 3) + sharp(Sharp.DECALN) + "X",
        "0" + sharp(Sharp.DECALN) + csi(escape.DECSTBM, 1, 1) + "0",
        csi(escape.DECSTBM, 2, 3) + sharp(Sharp.DECALN) + esc(escape.RI),
        (
            csi(escape.DECSTBM, 2, 3)
            + sharp(Sharp.DECALN)
            + set_mode(PrivateMode.ORIGIN)
            + "X"
        ),
        (
            csi(escape.DECSTBM, 2, 3)
            + set_mode(PrivateMode.ORIGIN)
            + sharp(Sharp.DECALN)
            + "X"
        ),
    ],
)
def test_kitty_draws_the_same_screen(data):
    assert not differences(data, lines=4, columns=6)
