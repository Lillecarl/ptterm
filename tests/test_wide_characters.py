"""
Double width characters, checked against kitty.

A double width character takes two cells. ptterm keeps the character in
the first and an empty string in the second. Every edit that touches
one of the two has to take the other one away, or the screen shows half
a character that nobody asked for.
"""
import pytest

from kitty_oracle import differences, kitty_is_available, ptterm_cells

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)

#: Two Chinese characters, a full width "A" and a half width "ka". The
#: first three take two cells, the last one takes one.
WIDE = "你好Ａ"
NARROW = "ｶ"


def test_a_wide_character_takes_two_cells():
    assert not differences("你好", lines=3, columns=8)


def test_a_half_width_character_takes_one_cell():
    assert not differences("ｶﾅ", lines=3, columns=8)


def test_a_wide_character_that_does_not_fit_wraps():
    "One free column is not enough, so the character goes to the next line."
    assert not differences("abcde你", lines=3, columns=6)


def test_the_line_goes_on_after_the_wrap():
    assert not differences("abcde你f", lines=3, columns=6)


def test_a_wide_character_at_the_right_edge_without_auto_wrap():
    "Auto wrap off: the character takes the last two columns."
    assert not differences("\x1b[?7labcde你", lines=3, columns=6)


def test_a_narrow_character_over_the_left_half():
    assert not differences("你好\x1b[1;1Hx", lines=3, columns=6)


def test_a_narrow_character_over_the_right_half():
    assert not differences("你好\x1b[1;2Hx", lines=3, columns=6)


def test_a_wide_character_over_a_pair():
    assert not differences("你好\x1b[1;2H漢", lines=3, columns=6)


def test_a_delete_that_splits_a_pair():
    assert not differences("你好\x1b[1;2H\x1b[1P", lines=3, columns=6)


def test_an_insert_that_splits_a_pair():
    assert not differences("你好\x1b[1;2H\x1b[1@", lines=3, columns=6)


def test_an_insert_that_pushes_half_a_pair_off_the_edge():
    assert not differences("abcd你\x1b[1;1H\x1b[1@", lines=3, columns=6)


def test_an_erase_of_the_left_half():
    assert not differences("你好\x1b[1;1H\x1b[1X", lines=3, columns=6)


def test_an_erase_of_the_right_half():
    assert not differences("你好\x1b[1;2H\x1b[1X", lines=3, columns=6)


def test_an_erase_to_the_end_of_the_line_that_splits_a_pair():
    assert not differences("你好\x1b[1;2H\x1b[0K", lines=3, columns=6)


def test_an_erase_to_the_start_of_the_line_that_splits_a_pair():
    assert not differences("你好\x1b[1;1H\x1b[1K", lines=3, columns=6)


def test_a_wide_character_never_writes_outside_the_screen():
    "The cell after the last column belongs to nobody."
    screen_rows = ptterm_cells("abcde你", lines=3, columns=6)
    assert len(screen_rows[0]) == 6
    assert screen_rows[1][0].char == "你"
