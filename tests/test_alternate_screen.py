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
def test_only_the_mode_that_took_the_screen_gives_it_back(taken, given_back):
    data = "0\x1b[?%sh\x1b[?%sl0" % (taken, given_back)
    assert not differences(data, lines=3, columns=8)
