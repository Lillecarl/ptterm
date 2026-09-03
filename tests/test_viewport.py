"""
Which lines of the buffer the screen shows.

The buffer keeps every line, including the ones that scrolled away.
`line_offset` names the first line that the reader sees. It follows the
content, and never the cursor: a cursor that moves up may not drag the
screen back into the history and hide the last line.
"""
import pytest

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

from kitty_oracle import differences, kitty_is_available


def _screen(lines=4, columns=8):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream


def test_the_screen_shows_the_last_lines_after_a_scroll():
    screen, stream = _screen()
    stream.feed("\x1b[4d\n0")  # The last line, one line further, a "0".
    assert screen.line_offset == 1


def test_a_move_up_does_not_take_the_screen_with_it():
    screen, stream = _screen()
    stream.feed("\x1b[4d\n0\x1b[1;1H")
    assert screen.line_offset == 1


def test_a_reverse_index_at_the_top_does_not_take_the_screen_with_it():
    screen, stream = _screen()
    # "CSI 2;3r" homes the cursor above the top margin, and the reverse
    # index there moves it up, which used to move the screen as well.
    stream.feed("\x1b[4d\n0\x1b[2;3r\x1bM")
    assert screen.line_offset == 1


@pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)
def test_the_last_line_stays_in_sight():
    assert not differences("\x1b[8d\n0\x1b[2;3r\x1bM", lines=8, columns=6)
