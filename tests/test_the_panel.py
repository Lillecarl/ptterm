"""
What the whole panel says about the differences that stand.

ptterm is not a judge: it is the thing on trial. Four emulators vote,
each written by other people and each from a different line — kitty in
C, WezTerm and Alacritty in Rust, libvterm in C.

A tally is worth more than a verdict when the answer is a choice. Each
test here writes down who is on which side, so that a decision rests on
what the emulators do and not on a memory of what they do.

`DEVIATIONS.md` carries the same list in prose: what each deviation
is, why ptterm takes the side it takes, and whether it could become a
setting. Change a tally here and change it there.
"""
import pytest

from panel import judges, report, verdict

#: Every judge that this file wants. With fewer, a tally means nothing.
WANTED = {"kitty", "wezterm", "alacritty", "libvterm"}

pytestmark = pytest.mark.skipif(
    not WANTED.issubset({judge.name for judge in judges()}),
    reason="the whole panel is not here",
)


def sides(data, lines=8, columns=24, blank_style=True):
    "The judges that differ from ptterm, and the ones that do not."
    answers = report(data, lines=lines, columns=columns, blank_style=blank_style)
    against = sorted(name for name, found in answers.items() if found)
    with_us = sorted(name for name, found in answers.items() if not found)
    return against, with_us


def test_the_panel_is_whole():
    assert {judge.name for judge in judges()} >= WANTED


def test_a_plain_program_finds_no_difference():
    assert verdict("hello\r\nworld\x1b[1;31m!\x1b[0m", 8, 24) == "agree"


def test_a_tab_at_the_right_margin_follows_the_panel():
    """
    A tab does not end the wait to wrap.

    A character in the last column leaves the cursor waiting to wrap.
    ptterm cleared that wait on a tab, so the character after the tab
    landed over the one that is there. Every judge put it on the next
    line instead, four to nothing, and only a document stood behind
    ptterm: xterm says a cursor move clears the wait, and a tab is a
    cursor move.

    The panel won. `tab()` now leaves a cursor that sits past the last
    column alone.
    """
    assert verdict("\x1b[1;20H12345\tX", 8, 24) == "agree"


# ----------------------------------------------------------------------
# The differences that stand. The user has decided every one of them,
# and ptterm keeps what it does in each. This records the tally that
# the decision rested on, so that nobody has to build it again.


def test_a_tab_on_the_last_row_splits_the_panel():
    "Two scroll the screen and two do not."
    against, with_us = sides("\x1b[8;20H12345\t")
    assert against == ["alacritty", "kitty"]
    assert with_us == ["libvterm", "wezterm"]


def test_a_backspace_in_the_first_column_keeps_the_panel():
    "kitty steps back to the row above. Nobody else does."
    against, with_us = sides("\n\x080", lines=4, columns=8)
    assert against == ["kitty"]
    assert with_us == ["alacritty", "libvterm", "wezterm"]


def test_a_count_of_zero_for_su_keeps_the_panel():
    "kitty reads a zero as no scroll. Everybody else reads it as one."
    against, with_us = sides("a\r\nb\x1b[0S", lines=4, columns=8)
    assert against == ["kitty"]
    assert with_us == ["alacritty", "libvterm", "wezterm"]


def test_too_many_parameters_splits_the_panel():
    "Two drop the sequence whole and two read the ones they need."
    against, with_us = sides("\x1b[3;9;9GX", lines=4, columns=8)
    assert against == ["kitty", "wezterm"]
    assert with_us == ["alacritty", "libvterm"]


def test_who_clears_the_alternate_screen_splits_the_panel():
    against, with_us = sides("\x1b[?1047h X \x1b[?1047l \x1b[?47h", lines=3, columns=6)
    assert against == ["alacritty", "kitty"]
    assert with_us == ["libvterm", "wezterm"]


def test_decaln_sends_the_cursor_home_for_half_the_panel():
    """
    ptterm follows the DEC manuals here, and the change is not a
    guess: kitty and WezTerm do the same.
    """
    against, with_us = sides("ab\x1b#8X", lines=4, columns=6)
    assert against == ["alacritty", "libvterm"]
    assert with_us == ["kitty", "wezterm"]


def test_a_mark_on_an_erased_cell_leaves_ptterm_alone():
    """
    ptterm is on its own, and the panel still does not settle it.

    The erase takes the "0" away, and a combining mark arrives with no
    character to hang on. ptterm hangs it on the space that the erase
    left. kitty, WezTerm and Alacritty all drop the mark. libvterm
    puts the "0" back and hangs the mark on that.

    Three judges of the four agree, so the majority says "drop it".
    The verdict is still "split": it calls ptterm wrong only when
    every judge agrees, and libvterm gives a fourth answer.
    """
    against, with_us = sides("0\x1b[40m\x1b[1Ḱ", lines=3, columns=6)
    assert against == ["alacritty", "kitty", "libvterm", "wezterm"]
    assert with_us == []
    assert verdict("0\x1b[40m\x1b[1Ḱ", lines=3, columns=6) == "split"


# ----------------------------------------------------------------------
# What the panel agrees on. These are the ones that a change may not
# break.


@pytest.mark.parametrize(
    "data",
    [
        "\x1b[4:2mdouble\x1b[4:3mcurly\x1b[4:4mdotted\x1b[4:5mdashed",
        "\x1b[4;58:2::255:0:0mred line\x1b[59m plain",
        "\x1b#8",
        "你好世界",
        "hello\r\nworld\x1b[2;2H\x1b[1K",
        "\x1b[2;4rabc\r\ndef\r\nghi\r\njkl",
    ],
)
def test_the_panel_agrees(data):
    assert verdict(data, lines=8, columns=24, blank_style=False) == "agree"


# ----------------------------------------------------------------------
# Where one judge stands apart. ptterm is with the other three, so
# there is nothing to fix; each of these is a quirk of one emulator and
# the panel is what makes that visible.


@pytest.mark.parametrize(
    "name, data",
    [
        # libvterm reads a colour of its own as "38:2:r:g:b" only, and
        # takes the empty colour space of the ISO form for the red.
        ("libvterm", "\x1b[38:2::10:20:30mcolon colour"),
        # Alacritty moves back over a tab stop differently.
        ("alacritty", "\x1b[Ix\x1b[2Iy\x1b[Zz"),
        # Alacritty sets a tab stop differently.
        ("alacritty", "\x1b[1;3H\x1bH\x1b[1;1H\tX"),
        # WezTerm scrolls inside a region under origin mode
        # differently.
        ("wezterm", "\x1b[2;4r\x1b[?6habc\r\ndef"),
    ],
)
def test_one_judge_stands_apart(name, data):
    against, with_us = sides(data, lines=8, columns=24, blank_style=False)
    assert against == [name]
    assert len(with_us) == 3
