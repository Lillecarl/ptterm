"""
DECSCL: which DEC terminal this one answers as.

Each level is one DEC terminal, and a higher level carries everything
the levels below it carry and more. A program that asks for an earlier
terminal loses the sequences that came later.

ptterm does not drop every later sequence. It drops the three that
esctest2 asks about, because a program that asks for a VT220 and then
finds a VT520 has learned nothing from asking.
"""
import pytest

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

#: DECSCL for each terminal, with seven bit controls.
VT200 = '\x1b[62;1"p'
VT300 = '\x1b[63;1"p'
VT400 = '\x1b[64;1"p'
VT500 = '\x1b[65;1"p'


def make_screen(lines=4, columns=10):
    "Return (screen, stream, what the screen answered)."
    answers = []
    screen = BetterScreen(lines, columns, write_process_input=answers.append)
    return screen, BetterStream(screen), answers


# ----------------------------------------------------------------------
# DECRQM arrived with the VT320.


@pytest.mark.parametrize("level", [VT300, VT400, VT500])
def test_decrqm_answers_from_the_terminal_that_brought_it(level):
    screen, stream, answers = make_screen()
    stream.feed(level + "\x1b[4$p")
    assert answers == ["\x1b[4;2$y"]


def test_decrqm_says_nothing_on_an_earlier_terminal():
    screen, stream, answers = make_screen()
    stream.feed(VT200 + "\x1b[4$p")
    assert answers == []


def test_decrqm_comes_back_with_the_level():
    screen, stream, answers = make_screen()
    stream.feed(VT200 + "\x1b[4$p" + VT500 + "\x1b[4$p")
    assert answers == ["\x1b[4;2$y"]


# ----------------------------------------------------------------------
# The columns of the scrolling region arrived with the VT420.


def test_the_column_margins_hold_from_the_terminal_that_brought_them():
    screen, stream, answers = make_screen()
    stream.feed(VT400 + "\x1b[?69h\x1b[3;6s")
    assert screen.horizontal_margins == (2, 5)


@pytest.mark.parametrize("level", [VT200, VT300])
def test_the_mode_does_not_set_on_an_earlier_terminal(level):
    screen, stream, answers = make_screen()
    stream.feed(level + "\x1b[?69h\x1b[3;6s")
    assert screen.horizontal_margins is None


def test_the_same_byte_saves_the_cursor_on_an_earlier_terminal():
    "Without the mode, 'CSI s' is SCOSC, so it saves and does not name a region."
    screen, stream, answers = make_screen()
    stream.feed(VT300 + "\x1b[2;4H\x1b[?69h\x1b[3;6s")
    stream.feed("\x1b[1;1H\x1b[u")
    assert (screen.pt_cursor_position.y, screen.pt_cursor_position.x) == (1, 3)
