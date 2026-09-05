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


def test_decncsm_keeps_the_screen_through_a_width_change():
    "DECNCSM ('?95') is how a program says it wants to keep the page."
    screen, stream, asks = make_screen()
    stream.feed("abc" + ALLOW + "\x1b[?95h" + WIDE)
    assert asks == [(None, 132)]
    assert screen.data_buffer[0][0].char == "a"
    assert screen.pt_cursor_position.x == 3


def test_the_page_width_modes_answer_decrqm():
    "A mode this screen acts on has to be one it can report."
    answers = []
    screen = BetterScreen(
        4, 80,
        write_process_input=answers.append,
        resize_func=lambda lines, columns: None,
    )
    stream = BetterStream(screen)
    stream.feed(ALLOW + "\x1b[?40$p")
    assert answers == ["\x1b[?40;1$y"]
    answers.clear()
    stream.feed("\x1b[?95$p")
    assert answers == ["\x1b[?95;2$y"]


def test_decncsm_needs_the_level_that_brought_it():
    "The VT510 brought DECNCSM, so DECSCL 64 takes it away again."
    screen, stream, asks = make_screen()
    stream.feed('\x1b[64;1"p')
    stream.feed("abc" + ALLOW + "\x1b[?95h" + WIDE)
    assert asks == [(None, 132)]
    assert screen.data_buffer[0].get(0) is None


# ----------------------------------------------------------------------
# RIS.


RIS = "\x1bc"


def test_a_reset_gives_the_narrow_page_back():
    """
    RIS ("ESC c") puts a terminal on the 132 column page back on the
    80 column one. `RISTests.test_RIS_ResetDECCOLM` of esctest2 asks
    for it, and Lillecarl/pymux#42 is where it was found.
    """
    screen, stream, asks = make_screen()
    stream.feed(ALLOW + WIDE)
    assert asks == [(None, 132)]
    stream.feed(RIS)
    assert asks == [(None, 132), (None, 80)]


def test_a_reset_on_the_narrow_page_asks_for_nothing():
    "A reset that changes no width must not ask the embedder for room."
    screen, stream, asks = make_screen()
    stream.feed(ALLOW + RIS)
    assert asks == []


def test_a_reset_reads_the_page_before_it_drops_the_modes():
    """
    The order is the fault the test in esctest2 names.

    An older xterm dropped DECCOLM first, found the terminal on no
    wide page, and left the width at 132. So the reading has to happen
    before the modes go, and this is what says it does.
    """
    screen, stream, asks = make_screen()
    stream.feed(ALLOW + WIDE)
    asks.clear()
    stream.feed(RIS)
    assert asks == [(None, 80)]
    # And the modes really are gone afterwards.
    stream.feed(WIDE)
    assert asks == [(None, 80)]


def test_a_denied_wide_page_is_not_given_back():
    """
    A terminal that never left the 80 column page has nothing to undo.

    Mode 40 off means DECCOLM did nothing at all, so a reset must not
    ask for a width either.
    """
    screen, stream, asks = make_screen()
    stream.feed(WIDE + RIS)
    assert asks == []
