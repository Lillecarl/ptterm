"""
Marks that have no width of their own, checked against kitty.

A combining mark belongs to the character before it and shares its
cell. The cell before can be the empty second half of a double width
character, and the character then sits one cell further back.
"""
import pytest

from kitty_oracle import differences, kitty_is_available, ptterm_cells

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)


def test_a_mark_on_the_character_before_it():
    assert not differences("é", lines=3, columns=8)


def test_two_marks_on_one_character():
    assert not differences("ǟ", lines=3, columns=8)


def test_a_mark_on_a_wide_character():
    "The cell before the cursor is the empty half. The character is before it."
    assert not differences("你́", lines=3, columns=8)
    rows = ptterm_cells("你́", lines=3, columns=8)
    assert rows[0][0].char == "你́"


def test_a_mark_with_nothing_before_it():
    "Nothing carries the mark, so it goes away."
    assert not differences("́X", lines=3, columns=8)


def test_a_mark_after_a_cursor_move():
    assert not differences("\x1b[3Gá", lines=3, columns=8)


def test_a_mark_on_a_character_that_is_already_drawn():
    assert not differences("abc\x1b[1Gá", lines=3, columns=8)
