"""
The screen of ptterm against libvterm, and the vote of the three.

libvterm is the emulator that Vim and Neovim carry. It is the second
opinion beside kitty, and it leans towards xterm.

A vote is worth more than a comparison. Where kitty and libvterm agree
and ptterm differs, ptterm is wrong and nobody has to decide anything.
Where the two disagree, the difference is a choice, and
`test_known_deviations.py` holds it.
"""
import pytest

from kitty_oracle import kitty_is_available
from vterm_oracle import libvterm_is_available, three_way, vterm_differences

pytestmark = pytest.mark.skipif(
    not (libvterm_is_available() and kitty_is_available()),
    reason="the two emulators to compare against are not both there",
)


#: Programs that every emulator draws the same way. These are the ones
#: that the comparison against kitty already covers; running them past
#: a second emulator says the agreement is not a coincidence.
SAME = [
    "hello",
    "\x1b[1;31mred\x1b[0m plain",
    "\x1b[38;5;200mcube\x1b[0m",
    "\x1b[38;2;10;20;30mtruecolor\x1b[0m",
    "a\r\nb\r\nc",
    "abc\x1b[1;2H\x1b[1K",
    "abc\x1b[2K",
    "abc\r\ndef\x1b[1;1H\x1b[1J",
    "\x1b[2;3r\x1b[2;1Habc\r\ndef\r\nghi",
    "abc\x1b[1;2H\x1b[2@",
    "abcdef\x1b[1;2H\x1b[2P",
    "abc\x1b[1;1H\x1b[2L",
    "abc\r\ndef\x1b[1;1H\x1b[1M",
    "\x1b[1;3r\x1b[3;1H\x1b[2S",
    "\x1b[1;3r\x1b[1;1H\x1b[2T",
    "abc\x1b[3X",
    "\x1b(0lqk\x1b(B",
    "你好世界",
    "é",
    "abcde\x1b[?7l fgh",
    "\x1b7abc\x1b8X",
    "\x1b[3;1H\x1bM",
    "\x1b[1;1H\x1bD",
]


@pytest.mark.parametrize("data", SAME, ids=range(len(SAME)))
def test_libvterm_draws_the_same_screen(data):
    assert not vterm_differences(data, lines=6, columns=12, blank_style=False)


@pytest.mark.parametrize("data", SAME, ids=range(len(SAME)))
def test_the_three_agree(data):
    assert three_way(data, lines=6, columns=12, blank_style=False) == "agree"


# ----------------------------------------------------------------------
# The vote on the differences that stand.
#
# Each of these is a strict `xfail` in `test_known_deviations.py`,
# recorded as "ptterm follows xterm and kitty does something else".
# libvterm is the check on that reading: it draws what ptterm draws, so
# the choice is not one implementation against the world.

FOLLOWS_PTTERM = [
    ("a tab in the last column", "\x1b[8;20H12345\t", 8, 24),
    ("a backspace in the first column", "\n\x080", 4, 8),
    ("a count of zero for SU", "a\r\nb\x1b[0S", 4, 8),
    ("the line that a scroll brings in", "\x1b[42m\x1b[1S", 4, 6),
    ("a sequence with too many parameters", "\x1b[3;9;9GX", 4, 8),
]


@pytest.mark.parametrize(
    "name,data,lines,columns", FOLLOWS_PTTERM, ids=[c[0] for c in FOLLOWS_PTTERM]
)
def test_libvterm_takes_the_side_of_ptterm(name, data, lines, columns):
    "kitty draws something else here; libvterm draws what ptterm draws."
    assert not vterm_differences(data, lines=lines, columns=columns)
    assert three_way(data, lines=lines, columns=columns) == "split"


def test_the_two_emulators_disagree_about_a_mark_on_an_erased_cell():
    """
    Three emulators, three answers.

    ptterm hangs the mark on the space that the erase left, kitty drops
    it, and libvterm hangs it on the character that the erase was meant
    to take away. Nothing to follow here.
    """
    assert three_way("0\x1b[40m\x1b[1K\u0301", lines=3, columns=6) == "split"


def test_the_alternate_screen_that_ptterm_does_not_keep_is_a_real_bug():
    """
    Both of the others hand the alternate screen back with what it
    held. This is the one open gap, and the vote says it is a bug and
    not a choice.
    """
    data = "\x1b[?1049h0\x1b[?1049l\x1b[?47h"
    assert three_way(data, lines=4, columns=6) == "ptterm-wrong"
