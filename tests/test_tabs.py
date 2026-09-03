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
