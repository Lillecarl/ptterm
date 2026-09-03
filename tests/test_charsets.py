"""
The character sets that "ESC ( 0" and "ESC ) 0" name.

The line drawing set of the DEC terminals is how ncurses draws a box
when the font has no Unicode. A program then sends "ESC ( 0" and the
letters "lqk" for the top of a box. Without the translation the reader
sees the letters.
"""
import pytest

from kitty_oracle import differences, kitty_is_available

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)


def test_the_line_drawing_set_as_g0():
    assert not differences("\x1b(0lqk", lines=4, columns=8)


def test_a_box_of_line_drawing_characters():
    assert not differences("\x1b(0lqk\r\nx u\r\nmqj", lines=4, columns=8)


def test_the_ascii_set_comes_back():
    assert not differences("\x1b(0abc\x1b(Babc", lines=4, columns=8)


def test_the_line_drawing_set_as_g1():
    "Shift out picks G1, and shift in gives G0 back."
    assert not differences("\x1b)0\x0eabc\x0fabc", lines=4, columns=8)


def test_a_cursor_move_does_not_change_the_set():
    assert not differences("\x1b(0\x1b[1;3Hqqq", lines=4, columns=8)


def test_a_set_that_nobody_defines_is_ignored():
    assert not differences("\x1b(Zabc", lines=4, columns=8)
