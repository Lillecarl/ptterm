"""
What the whole panel says about the differences that stand.

ptterm is not a judge: it is the thing on trial. Six emulators vote,
each written by other people and each from a different line — kitty in
C, WezTerm and Alacritty in Rust, libvterm in C, Ghostty in Zig and
xterm.js in TypeScript.

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
WANTED = {"kitty", "wezterm", "alacritty", "libvterm", "ghostty", "xterm"}

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


def test_a_tab_on_the_last_row_keeps_the_panel():
    """
    Two scroll the screen and four do not.

    This was two against two when the panel was four. Ghostty and
    xterm.js both leave the screen alone, so the side ptterm is on has
    the numbers now.
    """
    against, with_us = sides("\x1b[8;20H12345\t")
    assert against == ["alacritty", "kitty"]
    assert with_us == ["ghostty", "libvterm", "wezterm", "xterm"]


def test_a_backspace_in_the_first_column_keeps_the_panel():
    "kitty steps back to the row above. None of the other five does."
    against, with_us = sides("\n\x080", lines=4, columns=8)
    assert against == ["kitty"]
    assert with_us == ["alacritty", "ghostty", "libvterm", "wezterm", "xterm"]


def test_a_count_of_zero_for_su_keeps_the_panel():
    "kitty and Ghostty read a zero as no scroll. The other four read one."
    against, with_us = sides("a\r\nb\x1b[0S", lines=4, columns=8)
    assert against == ["ghostty", "kitty"]
    assert with_us == ["alacritty", "libvterm", "wezterm", "xterm"]


def test_too_many_parameters_splits_the_panel():
    """
    Three drop the sequence whole and three read the ones they need.

    Two against two before, and three against three now: the two new
    judges took one side each. Nothing here decides it.
    """
    against, with_us = sides("\x1b[3;9;9GX", lines=4, columns=8)
    assert against == ["ghostty", "kitty", "wezterm"]
    assert with_us == ["alacritty", "libvterm", "xterm"]


def test_who_clears_the_alternate_screen_keeps_the_panel():
    """
    Two keep the content of the alternate screen and four clear it.

    Two against two before. Ghostty and xterm.js both clear, so the
    reading that xterm documents has the numbers now.
    """
    against, with_us = sides("\x1b[?1047h X \x1b[?1047l \x1b[?47h", lines=3, columns=6)
    assert against == ["alacritty", "kitty"]
    assert with_us == ["ghostty", "libvterm", "wezterm", "xterm"]


def test_decaln_sends_the_cursor_home_for_most_of_the_panel():
    """
    ptterm follows the DEC manuals here, and the change is not a
    guess: four of the six do the same.
    """
    against, with_us = sides("ab\x1b#8X", lines=4, columns=6)
    assert against == ["alacritty", "libvterm"]
    assert with_us == ["ghostty", "kitty", "wezterm", "xterm"]


def test_a_mark_on_an_erased_cell_splits_the_panel():
    """
    The erase takes the "0" away, and a combining mark arrives with no
    character to hang on.

    ptterm drops the mark, and kitty, WezTerm and xterm.js drop it too.
    Alacritty and Ghostty keep it on the blank, and libvterm puts the
    "0" back and hangs the mark on that.

    Three against three. ptterm sits with the three that drop it.
    """
    against, with_us = sides("0\x1b[40m\x1b[1Ḱ", lines=3, columns=6)
    assert against == ["alacritty", "ghostty", "libvterm"]
    assert with_us == ["kitty", "wezterm", "xterm"]


def test_moving_back_over_a_tab_stop_splits_the_panel():
    """
    CBT and CHT ("CSI Ps Z" and "CSI Ps I") move over the tab stops
    without drawing. Three of the six land somewhere else than ptterm.

    This looked like a quirk of Alacritty while the panel was four.
    Ghostty and xterm.js both take that side, so it is a difference
    that stands and not one emulator being odd.
    """
    against, with_us = sides(
        "\x1b[Ix\x1b[2Iy\x1b[Zz", lines=8, columns=24, blank_style=False
    )
    assert against == ["alacritty", "ghostty", "xterm"]
    assert with_us == ["kitty", "libvterm", "wezterm"]


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
    assert len(with_us) == len(WANTED) - 1


# ----------------------------------------------------------------------
# Left and right margins. Three of the six carry them, and the tally
# below says which. A judge without the feature drops DECSLRM and
# draws the whole width, so it differs from ptterm on every one of
# these. That is a missing feature and not a decision, so ptterm keeps
# what xterm does. `DEVIATIONS.md` carries the reasoning.

#: The judges that carry DECSLRM, and the ones that do not.
WITH_MARGINS = ["ghostty", "libvterm", "wezterm"]
WITHOUT_MARGINS = ["alacritty", "kitty", "xterm"]


@pytest.mark.parametrize(
    "data",
    [
        # SU and SD carry the columns of the region.
        "a\r\nb\r\nc\r\nd\x1b[?69h\x1b[2;4s\x1b[2S",
        "a\r\nb\r\nc\r\nd\x1b[?69h\x1b[2;4s\x1b[2T",
        # IL and DL do the same, from inside the region.
        "abcd\r\nefgh\r\nijkl\x1b[?69h\x1b[2;4s\x1b[2;3H\x1b[L",
        "abcd\r\nefgh\r\nijkl\x1b[?69h\x1b[2;4s\x1b[2;3H\x1b[M",
        # ICH and DCH stop at the right margin.
        "abcdefg\x1b[?69h\x1b[2;5s\x1b[1;3H\x1b[@",
        "abcdefg\x1b[?69h\x1b[2;5s\x1b[1;3H\x1b[P",
        # A line feed at the bottom margin scrolls the region only.
        "a\r\nb\r\nc\r\nd\x1b[?69h\x1b[2;4s\x1b[2;4r\x1b[4;3H\n",
    ],
)
def test_the_judges_that_carry_margins_agree(data):
    against, with_us = sides(data)
    assert against == WITHOUT_MARGINS
    assert with_us == WITH_MARGINS


def test_a_soft_reset_takes_the_margins_away_for_everybody():
    "DECSTR is the one piece of this that all six carry."
    assert verdict("\x1b[?69h\x1b[3;7s\x1b[!p\x1b[1;5Hab", 8, 24) == "agree"


@pytest.mark.parametrize(
    "data, against",
    [
        # DECIC and DECDC insert and delete columns. Only libvterm and
        # xterm.js carry them.
        ("abcdefg\r\nABCDEFG\x1b[1;2H\x1b['}", ["alacritty", "ghostty", "kitty",
                                               "wezterm"]),
        ("abcdefg\r\nABCDEFG\x1b[1;2H\x1b['~", ["alacritty", "ghostty", "kitty",
                                               "wezterm"]),
        # DECBI and DECFI move the region when the cursor stands on a
        # margin. No judge carries them, and xterm does.
        ("x\x1b[1;1H\x1b6", sorted(WANTED)),
        ("\x1b[1;24Hx\x1b[1;24H\x1b9", sorted(WANTED)),
    ],
)
def test_the_columns_of_a_region_stand_apart(data, against):
    found, _with_us = sides(data, lines=4, columns=24)
    assert found == against
