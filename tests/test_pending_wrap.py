"""
The place a cursor waits in after a character in the last column.

A character written in the last column leaves the cursor one column
past the line. The next character wraps from there. A move of the
cursor ends that wait: the cursor lands on the last column, and what
comes next goes there.
"""
import pytest

from kitty_oracle import differences, kitty_is_available

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)


def test_the_next_character_wraps():
    assert not differences("\x1b[6G00", lines=4, columns=6)


@pytest.mark.parametrize(
    "move",
    [
        "\n",  # A linefeed.
        "\x1bD",  # An index.
        "\x1b[B",  # A move down.
        "\x1b[A",  # A move up.
        "\x1bE",  # The next line.
        "\r",  # A carriage return.
        "\x1b[C",  # A move right.
        "\x1b[D",  # A move left.
    ],
)
def test_a_move_ends_the_wait(move):
    assert not differences("\x1b[6G0%s0" % move, lines=4, columns=6)


def test_a_reverse_index_ends_the_wait():
    assert not differences("\x1b[2;6H0\x1bM0", lines=4, columns=6)


def test_an_erase_does_not_move_the_cursor():
    assert not differences("\x1b[6G0\x1b[K0", lines=4, columns=6)
