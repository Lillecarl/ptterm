"""
XTSAVE and XTRESTORE: putting private modes away and bringing them back.

A program that wants to change a mode and give it back the way it
found it saves it first. The two commands share their final byte with
DECSLRM and DECSTBM, and the private marker says which is meant.
"""
import pytest

from ptterm.screen import BetterScreen, flag_of
from ptterm.stream import BetterStream


@pytest.fixture
def pane():
    responses = []
    screen = BetterScreen(24, 80, write_process_input=responses.append)
    return screen, BetterStream(screen), responses


def is_set(screen, number):
    "True while the private mode `number` is set."
    return flag_of(number) in screen.mode


def test_a_saved_mode_comes_back_as_it_was(pane):
    screen, stream, _responses = pane
    stream.feed("\x1b[?7h")     # Autowrap on.
    stream.feed("\x1b[?7s")     # Save it.
    stream.feed("\x1b[?7l")     # Off.
    assert not is_set(screen, 7)
    stream.feed("\x1b[?7r")     # Back.
    assert is_set(screen, 7)


def test_a_mode_saved_while_off_comes_back_off(pane):
    screen, stream, _responses = pane
    stream.feed("\x1b[?7l")
    stream.feed("\x1b[?7s")
    stream.feed("\x1b[?7h")
    assert is_set(screen, 7)
    stream.feed("\x1b[?7r")
    assert not is_set(screen, 7)


def test_one_sequence_saves_several_modes(pane):
    screen, stream, _responses = pane
    stream.feed("\x1b[?7h\x1b[?25l")
    stream.feed("\x1b[?7;25s")
    stream.feed("\x1b[?7l\x1b[?25h")
    stream.feed("\x1b[?7;25r")
    assert is_set(screen, 7)
    assert not is_set(screen, 25)


def test_a_mode_that_no_terminal_carries_is_saved_as_off(pane):
    # A program may save and read back anything, so the number does
    # not have to name a mode that this pane knows.
    screen, stream, _responses = pane
    stream.feed("\x1b[?12345s")
    assert screen.saved_modes == {12345: False}


def test_restoring_a_mode_that_was_never_saved_changes_nothing(pane):
    screen, stream, _responses = pane
    stream.feed("\x1b[?7h")
    stream.feed("\x1b[?7r")
    assert is_set(screen, 7)


def test_the_private_marker_tells_a_save_from_a_region(pane):
    # "CSI Pl ; Pr s" names a region and "CSI ? Pm s" puts modes away.
    # One final byte, two commands.
    screen, stream, _responses = pane
    stream.feed("\x1b[?69h\x1b[3;20s")
    assert screen.horizontal_margins == (2, 19)
    stream.feed("\x1b[?7s")
    assert screen.horizontal_margins == (2, 19)
    assert 7 in screen.saved_modes


def test_the_private_marker_tells_a_restore_from_a_region(pane):
    # "CSI Pt ; Pb r" names a region and "CSI ? Pm r" brings modes back.
    screen, stream, _responses = pane
    stream.feed("\x1b[3;20r")
    assert screen.margins == (2, 19)
    stream.feed("\x1b[?7r")
    assert screen.margins == (2, 19)


def test_a_region_without_the_marker_still_reaches_decstbm(pane):
    # The private branch must not swallow the plain form.
    screen, stream, _responses = pane
    stream.feed("\x1b[5;20r")
    assert screen.margins == (4, 19)
