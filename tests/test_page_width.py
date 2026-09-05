"""
DECCOLM: the 80 and 132 column page, and the mode that allows it.

A DEC terminal has two page widths, and DECCOLM ("?3") picks one. It
clears the screen and puts the cursor home either way.

xterm keeps the width behind private mode 40, because a program that
sets DECCOLM by accident would otherwise throw the screen away. ptterm
does the same, and asks the embedder for the room rather than taking
it: a pane sits in a layout and cannot decide its own size.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

ALLOW = "\x1b[?40h"
DENY = "\x1b[?40l"
WIDE = "\x1b[?3h"
NARROW = "\x1b[?3l"


def make_screen(lines=4, columns=80):
    "Return (screen, stream, the resize asks it made)."
    asks = []
    screen = BetterScreen(
        lines,
        columns,
        write_process_input=lambda data: None,
        resize_func=lambda lines, columns: asks.append((lines, columns)),
    )
    return screen, BetterStream(screen), asks


def test_the_mode_is_off_until_a_program_asks():
    screen, stream, asks = make_screen()
    stream.feed(WIDE)
    assert asks == []


def test_an_allowed_deccolm_asks_for_the_wide_page():
    screen, stream, asks = make_screen()
    stream.feed(ALLOW + WIDE)
    assert asks == [(None, 132)]


def test_an_allowed_reset_asks_for_the_narrow_page():
    screen, stream, asks = make_screen()
    stream.feed(ALLOW + NARROW)
    assert asks == [(None, 80)]


def test_the_mode_can_be_taken_away_again():
    screen, stream, asks = make_screen()
    stream.feed(ALLOW + DENY + WIDE + NARROW)
    assert asks == []


def test_the_width_is_the_only_thing_it_asks_for():
    "The height belongs to the layout, so DECCOLM leaves it alone."
    screen, stream, asks = make_screen()
    stream.feed(ALLOW + WIDE)
    assert asks[0][0] is None


def test_deccolm_clears_the_screen_and_homes_the_cursor():
    screen, stream, asks = make_screen()
    stream.feed("abc\r\ndef" + ALLOW + WIDE)
    assert screen.pt_cursor_position.y == 0
    assert screen.pt_cursor_position.x == 0
    assert not any(row for row in screen.data_buffer.values())


def test_a_denied_deccolm_leaves_the_screen_alone():
    screen, stream, asks = make_screen()
    stream.feed("abc" + WIDE)
    assert screen.data_buffer[0][0].char == "a"
    assert screen.pt_cursor_position.x == 3
