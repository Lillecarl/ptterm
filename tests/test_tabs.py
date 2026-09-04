"""
Where a tab puts the cursor.

The tab stops sit every eight columns and do not know how wide the
screen is. A stop past the last column may not carry the cursor off
the line.
"""
import pytest

from kitty_oracle import differences, kitty_is_available

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)


def test_a_tab_reaches_the_next_stop():
    assert not differences("\tx", lines=3, columns=12)


def test_a_tab_past_the_last_stop_stops_at_the_last_column():
    "Twelve columns hold one stop, at column nine. The next one is past it."
    assert not differences("\t\tx", lines=3, columns=12)


def test_a_tab_on_a_screen_that_is_narrower_than_a_stop():
    assert not differences("\tx", lines=3, columns=6)


def test_a_tab_after_text():
    assert not differences("abc\tx", lines=3, columns=12)


def test_a_stop_that_a_program_sets():
    assert not differences("\x1b[3G\x1bH\x1b[1G\tx", lines=3, columns=12)


def test_a_stop_that_a_program_clears():
    assert not differences("\x1b[3g\x1b[1G\tx", lines=3, columns=12)


# ----------------------------------------------------------------------
# CHT and CBT ("CSI Ps I" and "CSI Ps Z") move over the stops without
# drawing anything. pyte has neither, so ptterm dropped them both: the
# vote called that a bug, because kitty and libvterm agree.


def test_forward_over_one_stop():
    assert not differences("\x1b[Ix", lines=3, columns=24)


def test_forward_over_several_stops():
    assert not differences("\x1b[2Ix", lines=3, columns=24)


def test_forward_past_the_last_stop():
    assert not differences("\x1b[9Ix", lines=3, columns=24)


def test_back_over_one_stop():
    assert not differences("\x1b[1;12Hab\x1b[Zx", lines=3, columns=24)


def test_back_over_several_stops():
    assert not differences("\x1b[1;20H\x1b[2Zx", lines=3, columns=24)


def test_back_from_the_first_column():
    "There is no stop before the first column, so the cursor stays."
    assert not differences("\x1b[Zx", lines=3, columns=24)


def test_a_count_of_zero_moves_over_one_stop():
    assert not differences("\x1b[0Ix", lines=3, columns=24)
    assert not differences("\x1b[1;20H\x1b[0Zx", lines=3, columns=24)


def test_they_follow_the_stops_that_a_program_sets():
    assert not differences("\x1b[3g\x1b[1;3H\x1bH\x1b[1;1H\x1b[Ix", lines=3, columns=24)
    assert not differences("\x1b[3g\x1b[1;3H\x1bH\x1b[1;20H\x1b[Zx", lines=3, columns=24)
