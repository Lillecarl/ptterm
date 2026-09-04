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
    "\x1b[4:2mdouble\x1b[24m plain",
    "\x1b[4:3mcurly\x1b[0m plain",
    "\x1b[21mdouble\x1b[24m plain",
    "\x1b[4:3m\x1b[4msingle",
    "\x1b[38:5:9mindex\x1b[0m",
    "\x1b[38:2:10:20:30mtruecolor\x1b[0m",
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


def test_a_character_after_the_tab_turns_the_vote_around():
    """
    The tab is not the split that it looks like.

    A tab that fills the last column and ends the program looks like
    agreement: all three leave the same screen. Write one character
    after the tab and the three come apart. kitty and libvterm put it
    on the next line; ptterm keeps the cursor in the last column, so
    the character lands over the one that is already there.

    The vote therefore calls the tab at the right margin
    "ptterm-wrong". xterm stands behind ptterm: a cursor move clears
    the flag that a character in the last column sets, and a tab is a
    cursor move. It is still a choice, and it is the user who makes
    it.
    """
    assert three_way("\x1b[1;20H12345\t", lines=4, columns=24) == "agree"
    assert three_way("\x1b[1;20H12345\tX", lines=4, columns=24) == "ptterm-wrong"


def test_the_two_emulators_disagree_about_a_mark_on_an_erased_cell():
    """
    Three emulators, three answers.

    ptterm hangs the mark on the space that the erase left, kitty drops
    it, and libvterm hangs it on the character that the erase was meant
    to take away. Nothing to follow here.
    """
    assert three_way("0\x1b[40m\x1b[1K\u0301", lines=3, columns=6) == "split"


def test_the_alternate_screen_keeps_what_it_held():
    """
    The vote called this a bug, and the bug is fixed.

    A terminal has one alternate screen and hands it back with what it
    held. Both of the others do; ptterm made a new one every time.
    """
    data = "\x1b[?47h X \x1b[?47l \x1b[?47h"
    assert three_way(data, lines=3, columns=6) == "agree"


def test_libvterm_does_not_take_the_alternate_screen_on_the_oldest_name():
    """
    libvterm reads "?1047" and "?1049" and not "?47", so it draws on
    one screen there. It is no reference for that mode, and the
    comparison against kitty covers it instead.
    """
    # The "X" of the alternate screen shows up on the first screen.
    assert vterm_differences("M\x1b[?47hX\x1b[?47l", lines=3, columns=6)


def test_libvterm_reads_no_colour_space_in_a_colour():
    """
    ISO 8613-6 writes a colour as "38:2:<space>:r:g:b", where the
    colour space is empty. libvterm reads the five parts of
    "38:2:r:g:b" only, so it takes the empty part for the red.

    kitty reads both, and ptterm follows kitty. The comparison against
    kitty covers the form with the colour space.
    """
    assert not vterm_differences("\x1b[38:2:1:2:3mA", lines=3, columns=6)
    assert vterm_differences("\x1b[38:2::1:2:3mA", lines=3, columns=6)


def test_libvterm_draws_three_shapes_of_underline():
    """
    libvterm knows a single, a double and a curly line and draws a
    single one for the two that are left. The comparison drops what it
    cannot hold, so a dotted line reads as a single one on both sides.
    """
    for shape in ("4:2", "4:3"):
        assert three_way("\x1b[%smA" % shape, lines=3, columns=6) == "agree"
    for shape in ("4:4", "4:5"):
        assert not vterm_differences("\x1b[%smA" % shape, lines=3, columns=6)


def test_who_clears_the_alternate_screen_is_a_choice():
    """
    The three do not agree about when the screen is cleared, and each
    pair takes a different side.

    ptterm clears on "?1049h" and on "?1047l", which is what xterm
    documents. kitty clears only on "?1049h". libvterm clears when it
    leaves, whichever mode leaves.
    """
    # Leaving with "?1049l" keeps the content here and in kitty.
    assert three_way("\x1b[?1049h0\x1b[?1049l\x1b[?47h", 4, 6) == "split"
    # Leaving with "?1047l" clears it here and in libvterm.
    assert three_way("\x1b[?1047h X \x1b[?1047l \x1b[?47h", 3, 6) == "split"
