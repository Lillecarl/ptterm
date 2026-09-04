"""
DECSTR ("CSI ! p"): the soft reset.

It keeps the text and the cursor, and puts the settings back. A program
sends it when it starts and when it ends, so that the terminal that the
next program finds is the one it knows.
"""
from pyte import modes as mo

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def _screen(lines=5, columns=10):
    answers = []
    screen = BetterScreen(lines, columns, write_process_input=answers.append)
    stream = BetterStream(screen)
    return screen, stream, answers


def test_the_cursor_stays_where_it_is():
    screen, stream, _answers = _screen()
    stream.feed("\x1b[3;5H\x1b[!p")
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (4, 2)


def test_the_text_stays_on_the_screen():
    screen, stream, _answers = _screen()
    stream.feed("hello\x1b[!p")
    assert screen.data_buffer[0][0].char == "h"


def test_the_rows_of_the_region_go_back():
    screen, stream, _answers = _screen()
    stream.feed("\x1b[2;4r\x1b[!p")
    assert screen.margins is None


def test_the_columns_of_the_region_go_back():
    screen, stream, _answers = _screen()
    stream.feed("\x1b[?69h\x1b[3;7s\x1b[!p")
    assert screen.horizontal_margins is None
    assert (LEFT_RIGHT_MODE << 5) not in screen.mode


LEFT_RIGHT_MODE = 69


def test_origin_mode_goes_off():
    screen, stream, _answers = _screen()
    stream.feed("\x1b[2;4r\x1b[?6h\x1b[!p")
    assert mo.DECOM not in screen.mode


def test_insert_mode_goes_off():
    screen, stream, _answers = _screen()
    stream.feed("\x1b[4h\x1b[!p")
    assert mo.IRM not in screen.mode


def test_autowrap_stays_on():
    "The DEC manuals turn it off. xterm keeps it on, and so do we."
    screen, stream, _answers = _screen()
    stream.feed("\x1b[?7l\x1b[!p")
    assert mo.DECAWM in screen.mode


def test_the_cursor_stays_visible():
    screen, stream, _answers = _screen()
    stream.feed("\x1b[?25l\x1b[!p")
    assert screen.pt_screen.show_cursor is True


def test_the_saved_cursor_goes_home():
    screen, stream, _answers = _screen()
    stream.feed("\x1b[3;5H\x1b7\x1b[!p\x1b8")
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (0, 0)


def test_the_rendition_goes_back_to_plain():
    _screen_, stream, answers = _screen()
    stream.feed("\x1b[1;4;31m\x1b[!p")
    stream.feed("\x1bP$qm\x1b\\")
    assert answers == ["\x1bP1$r0m\x1b\\"]


def test_the_alternate_screen_stays_in_front():
    "A soft reset is not a way out of the alternate screen."
    screen, stream, _answers = _screen()
    stream.feed("\x1b[?1049h\x1b[!p")
    assert screen.in_alternate_screen is True
