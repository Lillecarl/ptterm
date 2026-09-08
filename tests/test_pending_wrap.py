"""
The place a cursor waits in after a character in the last column.

A character written in the last column leaves the cursor one column
past the line. The next character wraps from there. A move of the
cursor ends that wait: the cursor lands on the last column, and what
comes next goes there.
"""
import pytest

from kitty_oracle import differences, kitty_is_available
from pyte import escape
from pyte.sequences import csi
from pyte.sequences import esc

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)


def test_the_next_character_wraps():
    assert not differences(csi(escape.CHA, 6) + "00", lines=4, columns=6)


@pytest.mark.parametrize(
    "move",
    [
        "\n",  # A linefeed.
        esc(escape.IND),  # An index.
        csi(escape.CUD),  # A move down.
        csi(escape.CUU),  # A move up.
        esc(escape.NEL),  # The next line.
        "\r",  # A carriage return.
        csi(escape.CUF),  # A move right.
        csi(escape.CUB),  # A move left.
    ],
)
def test_a_move_ends_the_wait(move):
    assert not differences(csi(escape.CHA, 6) + "0%s0" % move, lines=4, columns=6)


def test_a_reverse_index_ends_the_wait():
    assert not differences((
        csi(escape.CUP, 2, 6)
        + "0"
        + esc(escape.RI)
        + "0"
    ), lines=4, columns=6)


def test_an_erase_does_not_move_the_cursor():
    assert not differences((
        csi(escape.CHA, 6)
        + "0"
        + csi(escape.EL)
        + "0"
    ), lines=4, columns=6)
