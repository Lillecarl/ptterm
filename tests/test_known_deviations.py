"""
Places where ptterm and kitty draw a different screen on purpose.

Each of these is written down so that the comparison against kitty can
stay green, and so that nobody has to work out again whether it is a
bug. An `xfail` here that starts to pass means the deviation is gone.

This file compares against kitty alone. `test_the_panel.py` holds the
tally of all four judges for each one, and `DEVIATIONS.md` holds the
reason and whether it could become a setting.
"""
import pytest

from kitty_oracle import differences, kitty_is_available

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)


@pytest.mark.xfail(
    reason="kitty scrolls the screen on a tab in the last column of the last "
    "row. libvterm and WezTerm do not, and neither does ptterm.",
    strict=True,
)
def test_a_tab_at_the_right_margin_of_the_last_row():
    # A tab leaves a cursor that waits to wrap alone, which is what the
    # whole panel does. kitty goes further on the last row and scrolls
    # the screen up. Two judges scroll and two do not, so the panel
    # decides nothing here.
    assert not differences("\x1b[8;20H12345\t", lines=8, columns=24)


@pytest.mark.xfail(
    reason="kitty steps back to the end of the row above on a backspace in "
    "the first column. xterm does that only with mode 45 set, which is off "
    "by default. ptterm follows xterm.",
    strict=True,
)
def test_a_backspace_in_the_first_column():
    # kitty puts the "0" at the end of the row above. ptterm keeps the
    # cursor in the first column of the row it is on.
    assert not differences("\n\x080", lines=4, columns=8)


def test_a_backspace_that_is_not_in_the_first_column_agrees():
    # The common case has to keep working, and it does.
    assert not differences("ab\x08X", lines=4, columns=8)


@pytest.mark.xfail(
    reason="kitty reads a count of zero for SU and SD as no scroll. xterm "
    "reads a count of zero as one, for these and for every other sequence "
    "that counts. ptterm follows xterm.",
    strict=True,
)
def test_a_scroll_of_zero_lines():
    assert not differences("a\r\nb\x1b[0S", lines=4, columns=8)


@pytest.mark.parametrize("letter", "ABCDEFGLM@PX")
def test_a_count_of_zero_agrees_everywhere_else(letter):
    # Every other sequence that counts reads a zero as one on both
    # sides, so the deviation above really is only SU and SD.
    data = "abc\r\ndef\r\nghi\x1b[2;2H\x1b[0" + letter
    assert not differences(data, lines=5, columns=8)


@pytest.mark.xfail(
    reason="kitty leaves the line that a scroll brings in with the default "
    "style. xterm paints it with the background that is set, the same way it "
    "paints an erased cell. ptterm follows xterm.",
    strict=True,
)
def test_the_line_that_a_scroll_brings_in():
    assert not differences("\x1b[42m\x1b[1S", lines=4, columns=6)


@pytest.mark.xfail(
    reason="kitty drops a CSI sequence that carries more parameters than the "
    "command takes. xterm reads the ones it needs and ignores the rest. "
    "ptterm follows xterm.",
    strict=True,
)
def test_a_sequence_with_too_many_parameters():
    # "CSI 3;9;9 G" is CHA, which takes one parameter. ptterm moves to
    # column three; kitty leaves the cursor where it was.
    assert not differences("\x1b[3;9;9GX", lines=4, columns=8)


def test_a_sequence_with_too_many_parameters_does_not_raise():
    # Whatever the two do with it, one stray sequence may not stop the
    # stream of a pane. Everything after it still reaches the screen.
    from kitty_oracle import ptterm_cells

    rows = ptterm_cells("\x1b[3;9;9GX\r\nok", lines=4, columns=8)
    assert rows[1][0].char == "o"


def test_a_mark_on_an_erased_cell_agrees():
    # This was a deviation, and it is fixed. "CSI 1 K" erases the cell
    # before the cursor and paints it with the background. The cell
    # that the erase leaves holds no character, so the mark that lands
    # on it goes away, the same way it does in kitty.
    assert not differences("0\x1b[40m\x1b[1K\u0301", lines=3, columns=6)


def test_a_mark_on_an_erased_cell_agrees_without_a_background():
    # The same program without a background. ptterm gave two answers
    # for these two before: with no background the erase drops the
    # cell, and with one it wrote a space that the mark hung on.
    assert not differences("0\x1b[1K\u0301", lines=3, columns=6)


def test_a_mark_on_a_space_that_a_program_wrote():
    # A space that a program prints is a character, and the mark belongs
    # to it. Both sides agree there.
    assert not differences("a ́", lines=3, columns=6)


def test_a_character_after_a_wrap_below_the_region():
    """
    kitty puts two characters in one cell here, and ptterm draws two
    cells.

    The character has to be one that is not ASCII, and the cursor has
    to sit below the scrolling region, two columns after a wrap. Every
    case around it draws two cells on both sides, so this looks like a
    fault of kitty. The oracle takes the second character out of the
    cell, because a reader sees two cells either way.
    """
    data = "\x1b[1;2r\x1b[8;23H000ä"
    assert not differences(data, lines=8, columns=24)


@pytest.mark.parametrize("tail", ["0a", "ä0", "äa", "00ä"])
def test_the_cases_around_it_agree(tail):
    data = "\x1b[1;2r\x1b[8;23H00" + tail
    assert not differences(data, lines=8, columns=24)


def test_the_line_after_the_cell_that_kitty_holds_wrong():
    "What follows the second character moves along with it."
    data = "\x1b[1;2r\x1b[8;23H000ä0"
    assert not differences(data, lines=8, columns=24)
