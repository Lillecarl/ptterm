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
from kitty_oracle import ptterm_cells

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


def marks_kept(data, lines=3, columns=6):
    "How many code points each judge keeps in the first cell, and ptterm."
    kept = {"ptterm": len(ptterm_cells(data, lines, columns)[0][0].char)}
    for judge in judges():
        kept[judge.name] = len(judge.cells(data, lines, columns)[0][0].char)
    return kept


def columns_before_the_wrap(data, lines=4, columns=20):
    """
    How wide each judge thinks the first row is, and ptterm.

    No judge reports a line attribute, so DECDWL cannot be read
    directly. It is still visible: a double width line holds half the
    columns, so text wraps at half the width. Counting the cells that
    hold text on row 0 asks the question the panel can answer.
    """

    def wrote(rows):
        return sum(1 for cell in rows[0] if cell.char.strip())

    found = {"ptterm": wrote(ptterm_cells(data, lines, columns))}
    for judge in judges():
        found[judge.name] = wrote(judge.cells(data, lines, columns))
    return found


def test_a_plain_program_finds_no_difference():
    assert verdict("hello\r\nworld\x1b[1;31m!\x1b[0m", 8, 24) == "agree"


#: What every judge but libvterm answers to a DEC line attribute: the
#: line still holds every column it held.
WHOLE_WIDTH = {
    "ptterm": 15,
    "alacritty": 15,
    "ghostty": 15,
    "kitty": 15,
    "libvterm": 15,
    "wezterm": 15,
    "xterm": 15,
}

#: The same, with libvterm halving the line.
HALF_WIDTH = dict(WHOLE_WIDTH, libvterm=10)


def test_a_double_width_line_still_holds_every_column():
    """
    libvterm halves the columns of a DECDWL line. Nobody else does.

    `ROWWIDTH` in `src/vterm_internal.h` gives a double width line
    `cols / 2`, and `THISROWWIDTH` reaches every draw, erase and cursor
    bound in `src/state.c`. So fifteen characters wrap after ten on a
    twenty column screen.

    kitty, WezTerm, Alacritty, Ghostty and xterm.js all keep the whole
    line and let the renderer draw it twice as wide. Five to one, and
    ptterm is with the five.

    The panel cannot be asked the question directly, because no judge
    reports a line attribute. It can be asked where the text wraps,
    which is what `THISROWWIDTH` decides. Lillecarl/pymux#55.
    """
    assert columns_before_the_wrap("\x1b#6" + "a" * 15) == HALF_WIDTH


def test_a_double_height_line_is_a_double_width_line_too():
    "Both halves of a DECDHL line are double width, so libvterm halves both."
    assert columns_before_the_wrap("\x1b#3" + "a" * 15) == HALF_WIDTH
    assert columns_before_the_wrap("\x1b#4" + "a" * 15) == HALF_WIDTH


def test_single_width_gives_the_columns_back():
    "DECSWL puts libvterm back with the rest of the panel."
    assert columns_before_the_wrap("\x1b#6\x1b#5" + "a" * 15) == WHOLE_WIDTH


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
        # The four of the position family that ptterm already had. They
        # are here so that a change to HPB and VPB cannot quietly move
        # these.
        "\x1b[1;8H\x1b[3GX",
        "\x1b[1;4H\x1b[3aX",
        "\x1b[6;3H\x1b[3dX",
        "\x1b[2;3H\x1b[3eX",
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


# ----------------------------------------------------------------------
# The rectangle commands. No judge carries one.

#: The four sequences that take a rectangle, each on the screen that
#: `DECCRATests` draws in the conformance suite.
RECTANGLE_COMMANDS = [
    # DECFRA fills one with a character.
    "\x1b[37;2;2;4;4$x",
    # DECERA erases one.
    "\x1b[2;2;4;4$z",
    # DECSERA erases one and leaves a cell that DECSCA marked alone.
    "\x1b[2;2;4;4${",
    # DECCRA copies one to another place.
    "\x1b[2;2;4;4;1;5;5;1$v",
]


@pytest.mark.parametrize("command", RECTANGLE_COMMANDS)
def test_no_judge_carries_a_rectangle_command(command):
    """
    Every one of the six leaves the screen as it is.

    A judge without the feature does nothing at all, which reads the
    same way as a judge that disagrees. So the panel says nothing here,
    and it cannot: the tally is six abstentions and not six votes.

    xterm is the anchor instead. esctest2 is xterm's own suite, and its
    `DECFRATests`, `DECERATests`, `DECSERATests` and `DECCRATests` are
    what `test_rectangles.py` follows. `DEVIATIONS.md` says so.

    This test guards the claim. A judge that grows the feature makes it
    fail, and then the panel has something to say.
    """
    data = "abcdefg\r\nABCDEFG\r\nhijklmn\r\nHIJKLMN\r\nopqrstu" + command
    against, _with_us = sides(data, lines=6, columns=8)
    assert against == sorted(WANTED)


#: The judges that carry HPB and VPB, and the ones that do not.
WITH_THE_PAIR = ["ghostty", "libvterm", "wezterm"]
WITHOUT_THE_PAIR = ["alacritty", "kitty", "xterm"]


@pytest.mark.parametrize(
    "data",
    [
        # HPB: three columns to the left of column eight.
        "\x1b[1;8H\x1b[3jX",
        # VPB: two rows above row six.
        "\x1b[6;3H\x1b[2kX",
    ],
)
def test_hpb_and_vpb_follow_the_three_judges_that_carry_them(data):
    """
    Three of the six move the cursor, and three leave it where it is.

    ptterm had neither: `CSI Ps j` and `CSI Ps k` reached no handler and
    were consumed. So the panel read three against and three with us,
    and the three that were with us were abstaining and not agreeing.
    Alacritty, kitty and xterm.js do not carry the pair at all, and a
    judge without a feature does nothing, which reads the same way as a
    judge that does nothing on purpose.

    Ghostty, libvterm and WezTerm carry them, and all three land in the
    same place. ECMA-48 8.3.58 and 8.3.159 say that place too, and the
    four sequences beside these were already right. So ptterm follows
    the three, and the tally is now three that agree and three that
    still do nothing. Lillecarl/pymux#52.
    """
    against, with_us = sides(data, lines=8, columns=24, blank_style=False)
    assert against == WITHOUT_THE_PAIR
    assert with_us == WITH_THE_PAIR


def test_how_many_combining_marks_a_cell_keeps():
    """
    Four judges keep every mark, and so does ptterm. libvterm keeps six.

    libvterm's own `61screen_unicode.test` asserts the six, so
    `checks.ptterm-vterm` records two failures for it. The panel says
    that is libvterm's limit and not our fault:
    `VTERM_MAX_CHARS_PER_CELL` is a fixed array in a C struct, and
    nobody else has one.

    **Ghostty's 1 is our own instrument and not Ghostty.**
    `tests/judges-c` reports the base character of a cell and drops the
    marks, so it abstains here rather than voting.
    Lillecarl/pymux#63.

    So the tally is four to one with one abstention, and ptterm is with
    the four. A cell with no bound is still a cell a program can grow,
    which is what Lillecarl/pymux#54 asked about, and the answer is that
    every emulator people use has the same property.
    """
    assert marks_kept("e" + "́" * 20) == {
        "ptterm": 21,
        "alacritty": 21,
        "kitty": 21,
        "wezterm": 21,
        "xterm": 21,
        "libvterm": 6,
        "ghostty": 1,
    }


def test_where_the_cursor_stands_after_the_older_alternate_modes():
    """
    Five of the six leave the cursor where it stands when a program
    takes the alternate screen with "?47" or "?1047". kitty alone puts
    it home.

    esctest2 asks for the same thing, so xterm itself is on the side of
    the five.
    """
    against, with_us = sides("\x1b[2;3H\x1b[?47hX", lines=3, columns=6)
    assert against == ["kitty"]
    assert with_us == ["alacritty", "ghostty", "libvterm", "wezterm", "xterm"]


def test_where_the_cursor_stands_after_the_newest_alternate_mode():
    """
    "?1049" splits the panel the other way, and ptterm is with the two.

    ptterm sends the cursor home, because "?1049" saves it first and
    gives it back on the way out. Four judges leave it. Nothing in
    esctest2 asks, so the difference stands as a choice.
    """
    against, with_us = sides("\x1b[2;3H\x1b[?1049hX", lines=3, columns=6)
    assert against == ["alacritty", "ghostty", "libvterm", "xterm"]
    assert with_us == ["kitty", "wezterm"]
