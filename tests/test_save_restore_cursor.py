"""
The three ways a program saves the cursor, and brings it back.

DECSC ("ESC 7") and DECRC ("ESC 8") are the pair of the DEC terminals.
SCOSC ("CSI s") and SCORC ("CSI u") are the pair of the SCO console.
Private mode 1048 is the same pair written as a mode: a set saves and a
reset restores.

All three save the same thing, and all three read the same savepoint.
A save through one and a restore through another works, which is what
xterm does.

"CSI s" carries two meanings. While private mode 69 is set it is
DECSLRM and names the columns of the scrolling region. `left_right`
covers that side; this file covers the other one.
"""
import pytest

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

#: The three ways to save, and to bring back what was saved.
PAIRS = [
    ("\x1b7", "\x1b8"),
    ("\x1b[s", "\x1b[u"),
    ("\x1b[?1048h", "\x1b[?1048l"),
]


def _screen(lines=6, columns=20):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    return screen, stream


def _position(screen):
    return screen.pt_cursor_position.x, screen.pt_cursor_position.y


@pytest.mark.parametrize("save, restore", PAIRS)
def test_a_restore_brings_the_place_back(save, restore):
    screen, stream = _screen()
    stream.feed("\x1b[3;5H" + save + "\x1b[1;1H" + restore)
    assert _position(screen) == (4, 2)


@pytest.mark.parametrize("save, restore", PAIRS)
def test_a_restore_brings_the_rendition_back(save, restore):
    screen, stream = _screen()
    stream.feed("\x1b[31m" + save + "\x1b[0m" + restore + "x")
    assert "ansired" in screen.pt_screen.data_buffer[0][0].style


@pytest.mark.parametrize("save, restore", PAIRS)
def test_a_restore_brings_the_mark_of_decsca_back(save, restore):
    screen, stream = _screen()
    stream.feed('\x1b[1"q' + save + '\x1b[0"q' + restore)
    stream.feed("a\x1b[1;1;1;1${")
    assert screen.pt_screen.data_buffer[0][0].char == "a"


def test_one_pair_saves_and_another_pair_restores():
    "A terminal holds one savepoint, not three."
    screen, stream = _screen()
    stream.feed("\x1b[4;7H\x1b7\x1b[1;1H\x1b[u")
    assert _position(screen) == (6, 3)


def test_a_second_restore_gives_the_same_answer():
    screen, stream = _screen()
    stream.feed("\x1b[3;5H\x1b[s\x1b[1;1H\x1b[u\x1b[1;1H\x1b[u")
    assert _position(screen) == (4, 2)


def test_the_columns_of_a_region_win_while_the_mode_is_set():
    """
    "CSI s" is DECSLRM while private mode 69 is set, and SCOSC without
    it. The mode decides, and nothing else can.
    """
    screen, stream = _screen()
    stream.feed("\x1b[3;5H\x1b[?69h\x1b[2;9s")
    assert screen.horizontal_margins == (1, 8)
    # DECSLRM homes the cursor, and saved nothing on the way.
    assert _position(screen) == (0, 0)


def test_a_plain_csi_u_is_not_the_keyboard_protocol():
    """
    The kitty keyboard protocol writes "CSI > u", "CSI < u", "CSI = u"
    and "CSI ? u". A plain "CSI u" carries no marker, so it is SCORC.
    """
    screen, stream = _screen()
    stream.feed("\x1b[2;3H\x1b[s\x1b[5;5H\x1b[u")
    assert _position(screen) == (2, 1)
    assert screen.kitty_keyboard_flags == 0


@pytest.mark.parametrize("save, restore", PAIRS)
def test_a_restore_takes_origin_mode_off_again(save, restore):
    """
    Origin mode comes back the way it was saved, both ways.

    A save with the mode off has to take the mode off again. Only
    setting it back leaves a mode on that the program turned off.
    """
    screen, stream = _screen()
    stream.feed(save + "\x1b[2;5r\x1b[?6h" + restore)
    stream.feed("\x1b[1;1HX")
    assert screen.data_buffer[0][0].char == "X"


@pytest.mark.parametrize("save, restore", PAIRS)
def test_a_restore_leaves_the_wrap_alone(save, restore):
    """
    DECAWM is not part of the saved cursor.

    xterm does not bring the wrap back on a restore, and its own suite
    asks for that. A save with the wrap on, a reset and a restore
    leaves the wrap off.
    """
    screen, stream = _screen(lines=4, columns=8)
    stream.feed("\x1b[?7h" + save + "\x1b[?7l" + restore)
    stream.feed("\x1b[1;7Habcd")
    assert screen.pt_cursor_position.y == 0
