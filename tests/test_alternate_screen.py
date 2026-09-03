"""
The alternate screen, checked against kitty.

A full screen program takes the alternate screen so that the shell it
came from is still there when it ends. Three private modes name it:
"?1049" is the one a program sends today, and "?47" and "?1047" are
what an older one sends.
"""
import pytest

from kitty_oracle import differences, kitty_is_available

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)


@pytest.mark.parametrize("mode", ["47", "1047", "1049"])
def test_the_alternate_screen_starts_empty(mode):
    assert not differences("abc\x1b[?%sh xyz" % mode, lines=4, columns=8)


@pytest.mark.parametrize("mode", ["47", "1047", "1049"])
def test_the_first_screen_comes_back(mode):
    data = "abc\x1b[?%shxyz\x1b[?%sl" % (mode, mode)
    assert not differences(data, lines=4, columns=8)


def test_a_second_switch_keeps_the_first_screen():
    assert not differences("abc\x1b[?47h\x1b[?1049hx\x1b[?1049l", lines=4, columns=8)


def test_leaving_a_screen_that_was_never_taken():
    assert not differences("abc\x1b[?1049l", lines=4, columns=8)


def test_the_lines_of_the_alternate_screen_go_away():
    "What the program drew may not come back with the first screen."
    data = "a\r\nb\r\nc\x1b[?1049hx\r\ny\x1b[?1049l"
    assert not differences(data, lines=4, columns=8)


@pytest.mark.parametrize(
    "taken,given_back",
    [("1049", "47"), ("47", "1049"), ("1047", "47"), ("1049", "1047")],
)
def test_any_of_the_three_gives_the_screen_back(taken, given_back):
    "A program can take the screen under one name and give it back under another."
    data = "0\x1b[?%sh\x1b[?%sl0" % (taken, given_back)
    assert not differences(data, lines=3, columns=8)


@pytest.mark.parametrize("mode", ["47", "1047"])
def test_the_older_modes_leave_the_cursor_where_it_is(mode):
    "Only '?1049' saves a cursor, so only it brings one back."
    assert not differences("ab\x1b[?%shZ\x1b[?%slX" % (mode, mode),
                           lines=3, columns=8)


def test_the_cursor_comes_back_with_the_mode_that_saved_it():
    assert not differences("ab\x1b[?1049hZ\x1b[?1049lX", lines=3, columns=8)


def test_a_cursor_that_was_never_saved_does_not_come_back():
    "'?47' takes the screen without a cursor, so '?1049l' has none to read."
    assert not differences("0\x1b[?47h\x1b[?1049l0", lines=3, columns=8)


def test_the_scrolling_region_survives_the_switch():
    "The region belongs to the terminal, so the alternate screen keeps it."
    assert not differences("\x1b[2;3h\x1b[2;3r\x1b[?1049h0\x1bM", lines=5, columns=6)


def test_the_region_scrolls_on_the_alternate_screen():
    data = "\x1b[2;4r\x1b[?1049hA\x1b[4;1HB\nC"
    assert not differences(data, lines=5, columns=6)


def test_a_region_set_on_the_alternate_screen_holds_after_the_leave():
    data = "\x1b[2;3r\x1b[?1049h\x1b[1;3r\x1b[?1049l\x1b[9B0"
    assert not differences(data, lines=5, columns=6)
