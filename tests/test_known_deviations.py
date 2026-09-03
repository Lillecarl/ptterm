"""
Places where ptterm and kitty draw a different screen on purpose.

Each of these is written down so that the comparison against kitty can
stay green, and so that nobody has to work out again whether it is a
bug. An `xfail` here that starts to pass means the deviation is gone.
"""
import pytest

from kitty_oracle import differences, kitty_is_available

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)


@pytest.mark.xfail(
    reason="kitty moves to the next line on a tab at the right margin, which "
    "xterm and the DEC manuals do not. ptterm follows xterm.",
    strict=True,
)
def test_a_tab_at_the_right_margin_of_the_last_row():
    # kitty scrolls the screen up here, because it treats the tab as a
    # move to the next line. ptterm keeps the cursor where it is.
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
