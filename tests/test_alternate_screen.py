"""
The alternate screen, checked against kitty.

A full screen program takes the alternate screen so that the shell it
came from is still there when it ends. Three private modes name it:
"?1049" is the one a program sends today, and "?47" and "?1047" are
what an older one sends.
"""
import pytest

from kitty_oracle import differences, kitty_is_available
from pyte import escape
from pyte.modes import PrivateMode
from pyte.sequences import csi, esc, reset_mode, set_mode

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)


@pytest.mark.parametrize("mode", ["47", "1047", "1049"])
def test_the_alternate_screen_starts_empty(mode):
    # The cursor goes home by hand, because the three modes do not
    # agree on where it stands after the switch and this test is about
    # the cells.
    assert not differences("abc\x1b[?%sh\x1b[H xyz" % mode, lines=4, columns=8)


@pytest.mark.parametrize("mode", ["47", "1047", "1049"])
def test_the_first_screen_comes_back(mode):
    data = "abc\x1b[?%shxyz\x1b[?%sl" % (mode, mode)
    assert not differences(data, lines=4, columns=8)


def test_a_second_switch_keeps_the_first_screen():
    assert not differences((
        "abc"
        + set_mode(PrivateMode.ALTERNATE_SCREEN)
        + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "x"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
    ), lines=4, columns=8)


def test_leaving_a_screen_that_was_never_taken():
    assert not differences((
        "abc"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
    ), lines=4, columns=8)


def test_the_lines_of_the_alternate_screen_go_away():
    "What the program drew may not come back with the first screen."
    data = (
        "a\r\nb\r\nc"
        + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "x\r\ny"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
    )
    assert not differences(data, lines=4, columns=8)


@pytest.mark.parametrize(
    "taken,given_back",
    [("1049", "47"), ("47", "1049"), ("1047", "47"), ("1049", "1047")],
)
def test_any_of_the_three_gives_the_screen_back(taken, given_back):
    "A program can take the screen under one name and give it back under another."
    data = "0\x1b[?%sh\x1b[H\x1b[?%sl0" % (taken, given_back)
    assert not differences(data, lines=3, columns=8)


def test_the_cursor_comes_back_with_the_mode_that_saved_it():
    assert not differences((
        "ab"
        + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "Z"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "X"
    ), lines=3, columns=8)


def test_a_cursor_that_was_never_saved_does_not_come_back():
    "'?47' takes the screen without a cursor, so '?1049l' has none to read."
    assert not differences((
        "0"
        + set_mode(PrivateMode.ALTERNATE_SCREEN)
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "0"
    ), lines=3, columns=8)


def test_the_scrolling_region_survives_the_switch():
    "The region belongs to the terminal, so the alternate screen keeps it."
    assert not differences((
        csi(escape.SM, 2, 3)
        + csi(escape.DECSTBM, 2, 3)
        + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "0"
        + esc(escape.RI)
    ), lines=5, columns=6)


def test_the_region_scrolls_on_the_alternate_screen():
    data = (
        csi(escape.DECSTBM, 2, 4)
        + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "A"
        + csi(escape.CUP, 4, 1)
        + "B\nC"
    )
    assert not differences(data, lines=5, columns=6)


def test_a_region_set_on_the_alternate_screen_holds_after_the_leave():
    data = (
        csi(escape.DECSTBM, 2, 3)
        + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + csi(escape.DECSTBM, 1, 3)
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + csi(escape.CUD, 9)
        + "0"
    )
    assert not differences(data, lines=5, columns=6)


def test_each_screen_has_its_own_saved_cursor():
    "A restore on the alternate screen may not read the cursor of the first."
    assert not differences((
        "0"
        + esc(escape.DECSC)
        + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + esc(escape.DECRC)
        + "0"
    ), lines=5, columns=6)


def test_the_saved_cursor_of_the_first_screen_survives():
    data = (
        "0"
        + esc(escape.DECSC)
        + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + esc(escape.DECSC)
        + csi(escape.CUP, 3, 1)
        + esc(escape.DECRC)
        + "X"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + esc(escape.DECRC)
        + "Y"
    )
    assert not differences(data, lines=5, columns=6)


def test_the_alternate_screen_starts_with_a_plain_rendition():
    assert not differences((
        csi(escape.SGR, 1)
        + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "0"
    ), lines=4, columns=6, strict=True)


def test_the_rendition_comes_back_with_the_cursor():
    "'?1049' saves the rendition the way 'ESC 7' does."
    data = (
        csi(escape.SGR, 1)
        + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "0"
    )
    assert not differences(data, lines=4, columns=6, strict=True)


def test_a_rendition_set_on_the_alternate_screen_does_not_survive():
    data = (
        set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + csi(escape.SGR, 31)
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "0"
    )
    assert not differences(data, lines=4, columns=6, strict=True)


def test_the_older_modes_bring_no_rendition_back():
    data = (
        csi(escape.SGR, 42)
        + set_mode(PrivateMode.ALTERNATE_SCREEN)
        + "0"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN)
        + "0"
    )
    assert not differences(data, lines=4, columns=6, strict=True)


def test_the_leave_of_1049_reads_the_saved_cursor_of_the_first_screen():
    "'?47' saved none, so '?1049l' finds nothing and goes home."
    assert not differences((
        set_mode(PrivateMode.ALTERNATE_SCREEN)
        + "0"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "0"
    ), lines=4, columns=6)


# ----------------------------------------------------------------------
# One screen, kept between visits.
#
# A terminal has one alternate screen for its whole life and hands it
# back with what it held. "?1049h" clears the screen it takes; the two
# older names do not.


def test_a_second_visit_finds_what_the_first_left():
    assert not differences((
        set_mode(PrivateMode.ALTERNATE_SCREEN)
        + "X"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN)
        + set_mode(PrivateMode.ALTERNATE_SCREEN)
    ), lines=3, columns=6)


def test_the_mode_that_clears_still_clears():
    assert not differences((
        set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "X"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
    ), lines=3, columns=6)


def test_a_screen_that_1049_left_is_still_there_for_an_older_name():
    assert not differences((
        set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "X"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + set_mode(PrivateMode.ALTERNATE_SCREEN)
    ), lines=3, columns=6)


def test_the_cells_come_back_on_a_second_visit():
    # The cursor goes home by hand: where it stands after the switch
    # is a deviation of its own, in `test_known_deviations.py`.
    assert not differences((
        set_mode(PrivateMode.ALTERNATE_SCREEN)
        + "abc"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN)
        + set_mode(PrivateMode.ALTERNATE_SCREEN)
        + csi(escape.CUP)
        + "Z"
    ),
                           lines=3, columns=6)


def test_the_first_screen_is_untouched_by_all_of_it():
    data = (
        "M"
        + set_mode(PrivateMode.ALTERNATE_SCREEN)
        + "X"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN)
        + set_mode(PrivateMode.ALTERNATE_SCREEN)
        + "Y"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN)
    )
    assert not differences(data, lines=3, columns=6)


def test_a_rendition_of_the_first_visit_does_not_come_back():
    "The cells keep the colour they were drawn with; the next one is plain."
    data = (
        set_mode(PrivateMode.ALTERNATE_SCREEN)
        + csi(escape.SGR, 31)
        + "red"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN)
        + set_mode(PrivateMode.ALTERNATE_SCREEN)
        + csi(escape.CUP)
        + "plain"
    )
    assert not differences(data, lines=3, columns=6, strict=True)
