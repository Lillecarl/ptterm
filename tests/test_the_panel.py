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

from panel import abstained, judges, report, verdict
from kitty_oracle import ptterm_cells

#: Every judge that this file wants. With fewer, a tally means nothing.
WANTED = {"kitty", "wezterm", "alacritty", "libvterm", "ghostty", "xterm"}

pytestmark = pytest.mark.skipif(
    not WANTED.issubset({judge.name for judge in judges()}),
    reason="the whole panel is not here",
)


def sides(data, lines=8, columns=24, blank_style=True, resize=None):
    """
    The judges that differ from ptterm, and the ones that draw what it
    draws.

    A judge that holds nothing the difference is about is in neither.
    It has no opinion, and counting it as one that agrees would say the
    panel answered a question that it never asked. `cannot_see` names
    those.

    `resize` is a size to take after the data, as (lines, columns). The
    screens are then read at that size, and what they hold is what each
    reflow made of the rows before.
    """
    answers = report(
        data, lines=lines, columns=columns, blank_style=blank_style, resize=resize
    )
    blind = set(
        cannot_see(
            data,
            lines=lines,
            columns=columns,
            blank_style=blank_style,
            resize=resize,
        )
    )
    against = sorted(name for name, found in answers.items() if found)
    with_us = sorted(
        name for name, found in answers.items() if not found and name not in blind
    )
    return against, with_us


def cannot_see(data, lines=8, columns=24, blank_style=True, resize=None):
    "The judges that hold nothing that the difference is about."
    return abstained(
        data,
        lines=lines,
        columns=columns,
        blank_style=blank_style,
        resize=resize,
    )


def test_the_panel_is_whole():
    assert {judge.name for judge in judges()} >= WANTED


def marks_kept(data, lines=3, columns=6):
    "How many code points each judge keeps in the first cell, and ptterm."
    kept = {"ptterm": len(ptterm_cells(data, lines, columns)[0][0].char)}
    for judge in judges():
        kept[judge.name] = len(judge.cells(data, lines, columns)[0][0].char)
    return kept


def characters_in_row(data, row=0, lines=3, columns=20):
    "What each judge holds in one row, as a string, and ptterm."

    def text(rows):
        return "".join(cell.char or " " for cell in rows[row])

    found = {"ptterm": text(ptterm_cells(data, lines, columns))}
    for judge in judges():
        found[judge.name] = text(judge.cells(data, lines, columns))
    return found


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


def test_an_erase_does_not_keep_the_underline():
    """
    Five judges take the underline off an erased cell. kitty keeps it.

    ptterm kept it, and it was wrong: `erase_style` carried the
    underline and its colour, so a shell that left the underline on and
    then cleared the screen underlined every blank cell of it. That is
    Alacritty's `clear_underline` reference test, two thousand cells of
    it, and four more of their tests found the same thing through
    `checks.pymux-alacritty`.

    The background is the other way round, and both are the same
    question: what can a reader see on a blank. A colour can be seen,
    and the panel says a line under nothing cannot.
    """
    for erase in ("\x1b[2J", "\x1b[K"):
        against, with_us = sides("\x1b[4mAB" + erase, lines=3, columns=6)
        assert against == ["kitty"]
        assert with_us == ["alacritty", "ghostty", "libvterm", "wezterm", "xterm"]


def test_an_erase_keeps_the_background():
    """
    Five judges paint an erased cell with the background. Ghostty does
    not.

    Programs count on it: htop draws the header of its table with
    "CSI K" and expects the colour to reach the end of the line.
    """
    against, with_us = sides("\x1b[41mAB\x1b[2J", lines=3, columns=6)
    assert against == ["ghostty"]
    assert with_us == ["alacritty", "kitty", "libvterm", "wezterm", "xterm"]


def test_whether_an_erase_keeps_reverse_video_is_a_choice():
    """
    Four judges drop reverse video on an erased cell and two keep it.

    A split is a choice and not a rule, so ptterm keeps it: a program
    that turns reverse on and then erases means the block to be seen,
    and that is the reading kitty and WezTerm take.
    """
    against, with_us = sides("\x1b[7mAB\x1b[2J", lines=3, columns=6)
    assert against == ["alacritty", "ghostty", "libvterm", "xterm"]
    assert with_us == ["kitty", "wezterm"]


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
        "\x1b[4;58:2::255:0:0mred line",
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
    Five judges keep every mark, and so does ptterm. libvterm keeps six.

    libvterm's own `61screen_unicode.test` asserts the six, so
    `checks.ptterm-vterm` records two failures for it. The panel says
    that is libvterm's limit and not our fault:
    `VTERM_MAX_CHARS_PER_CELL` is a fixed array in a C struct, and
    nobody else has one.

    Ghostty read as 1 until Lillecarl/pymux#63. That was our own
    instrument: `tests/judges-c` asked for the cluster with a buffer of
    sixteen and did not ask again when the library said the cluster was
    longer. It now asks twice and reports what Ghostty holds.

    So the tally is five to one, and ptterm is with the five. A cell
    with no bound is still a cell a program can grow, which is what
    Lillecarl/pymux#54 asked about, and the answer is that every
    emulator people use has the same property.
    """
    assert marks_kept("e" + "́" * 20) == {
        "ptterm": 21,
        "alacritty": 21,
        "kitty": 21,
        "wezterm": 21,
        "xterm": 21,
        "libvterm": 6,
        "ghostty": 21,
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


def test_a_linefeed_at_the_bottom_paints_the_line_it_brings_in():
    """
    Four judges paint the new line with the background that is set, and
    kitty and Ghostty give it the default. The same four and the same
    two split over a scroll region, which is deviation 7.

    ptterm is with the four everywhere now. It painted for a region and
    not for a screen with no region, so the same linefeed painted or
    did not paint by whether a program had set a region.
    """
    against, with_us = sides("\x1b[4;1H\x1b[42m\n", lines=4, columns=6)
    assert against == ["ghostty", "kitty"]
    assert with_us == ["alacritty", "libvterm", "wezterm", "xterm"]


def test_what_sgr_21_means():
    """
    Five judges read "SGR 21" as a double underline. Alacritty alone
    reads it as the end of bold.

    ECMA-48 numbers 21 "doubly underlined". Alacritty follows the other
    reading, where 21 undoes "SGR 1". Its own reference test
    `underline` writes "CSI 4:3 ; 21 m" and records a curl, so the ten
    cells that `checks.pymux-alacritty` reports there are this
    difference and not a lost underline shape.

    xterm.js said only whether a line was there and could not vote. It
    now reports the shape, and it draws the double line.
    """
    program = "\x1b[1;4:3;21mX"
    against, with_us = sides(program, lines=3, columns=6)
    assert against == ["alacritty"]
    assert with_us == ["ghostty", "kitty", "libvterm", "wezterm", "xterm"]
    assert cannot_see(program, lines=3, columns=6) == []


def test_xterm_js_never_gets_back_to_the_default_colour_of_a_line():
    """
    "SGR 59" asks for the colour a line has when nothing set one.
    xterm.js paints white instead, and it is alone.

    It stores the default as -1 in a field of twenty six bits, so the
    sentinel reads back as the colour with every bit set. Nothing later
    can tell that from "SGR 58:2::255:255:255", and the emulator draws
    what it holds.

    libvterm keeps no colour for a line at all, so it does not vote.
    Four judges and ptterm go back to the default.
    """
    program = "\x1b[4;58:2::255:0:0mred line\x1b[59m plain"
    against, with_us = sides(program, lines=8, columns=24, blank_style=False)
    assert against == ["xterm"]
    assert with_us == ["alacritty", "ghostty", "kitty", "wezterm"]
    assert cannot_see(program, lines=8, columns=24, blank_style=False) == [
        "libvterm"
    ]


def test_every_judge_holds_a_number_of_the_palette_as_a_number():
    """
    All six keep the number that "CSI 38 ; 5 ; n m" names, above
    fifteen as well as below it. Each one paints the palette from its
    own theme, so the number is what the cell holds.

    The panel could not see this before. ptterm turned a number above
    fifteen into the colour that xterm paints for it, and the oracles
    did the same to each judge's answer, so every side matched. Now
    ptterm keeps the number and the oracles hand it on.
    """
    against, with_us = sides("\x1b[38;5;200m\x1b[48;5;234mX", lines=3, columns=6)
    assert against == []
    assert with_us == ["alacritty", "ghostty", "kitty", "libvterm", "wezterm", "xterm"]


def test_what_a_tab_leaves_in_the_cell_it_moves_from():
    """
    Alacritty writes a tab character into the cell the cursor moves
    from. Nobody else does, and neither does ptterm.

    A tab moves the cursor and draws nothing, so the cells it steps
    over hold what was already there. Alacritty keeps the character so
    that a copy of the line gives the tab back, instead of the spaces
    that the line looks like. A pane does not select, and it hands
    cells to a renderer, so it has nowhere to put the character.

    This is the whole of `tab_rendering` and `vttest_tab_clear_set` in
    `checks.pymux-alacritty`: 24 cells, and every one of them is a tab
    where ptterm holds a space, with every other field equal.
    """
    held = characters_in_row("a\tb", lines=3, columns=20)
    assert held["alacritty"][:9] == "a\t      b"
    for name in ("ptterm", "ghostty", "kitty", "libvterm", "wezterm", "xterm"):
        assert held[name][:9] == "a       b", name


def test_whether_a_reset_forgets_the_saved_cursor():
    """
    RIS is the power-up state, so a terminal that has just been through
    one remembers no cursor. Alacritty, Ghostty, kitty and xterm.js
    forget it; libvterm and WezTerm keep it.

    ptterm kept it, and emptied the list on DECSTR, which is the wrong
    way round: the soft reset is the weaker of the two. Neither judge on
    the other side draws the line there. It forgets it on both now.
    """

    def home(data):
        held = _cells(data, lines=4, columns=8)
        return {name: rows[0][0].char == "z" for name, rows in held.items()}

    after_ris = home("\x1b[3;5H\x1b7\x1bc\x1b8z")
    for name in ("ptterm", "alacritty", "ghostty", "kitty", "xterm"):
        assert after_ris[name], name
    for name in ("libvterm", "wezterm"):
        assert not after_ris[name], name

    after_decstr = home("\x1b[3;5H\x1b7\x1b[!p\x1b8z")
    for name in ("ptterm", "kitty", "wezterm", "xterm"):
        assert after_decstr[name], name
    for name in ("alacritty", "ghostty", "libvterm"):
        assert not after_decstr[name], name


def test_whether_a_restore_brings_the_wait_to_wrap_back():
    """
    A character in the last column leaves the cursor waiting to wrap.
    `save_cursor` stores the column the cursor stands on, so the wait is
    not in the savepoint, and a restore cannot bring it back.

    Three judges bring it back and three do not, so ptterm keeps what it
    does. The third case is the one to read: with no move between the
    save and the restore, four judges leave the screen alone.

    Entry 22 of `DEVIATIONS.md` and Lillecarl/pymux#88 hold it. It is
    the whole of `wrapline_alt_toggle` in `checks.pymux-alacritty`.
    """
    fill = "a" * 6

    def where_b_landed(data):
        held = _cells(data, lines=4, columns=6)
        return {name: rows[0][5].char for name, rows in held.items()}

    through_decsc = where_b_landed(fill + "\x1b7\x1b[1;1H\x1b8b")
    for name in ("alacritty", "ghostty", "wezterm"):
        assert through_decsc[name] == "a", name
    for name in ("ptterm", "kitty", "libvterm", "xterm"):
        assert through_decsc[name] == "b", name

    through_alt = where_b_landed(fill + "\x1b[?1049hx\x1b[?1049lb")
    for name in ("alacritty", "ghostty", "wezterm"):
        assert through_alt[name] == "a", name
    for name in ("ptterm", "kitty", "libvterm", "xterm"):
        assert through_alt[name] == "b", name

    #: A save and a restore with nothing in between. Four judges leave
    #: the screen alone, and libvterm is one of them here.
    no_move = where_b_landed(fill + "\x1b7\x1b8b")
    for name in ("alacritty", "ghostty", "libvterm", "wezterm"):
        assert no_move[name] == "a", name
    for name in ("ptterm", "kitty", "xterm"):
        assert no_move[name] == "b", name


def test_what_a_delete_leaves_at_the_right_edge():
    """
    DCH shifts a line left and blanks the right edge. Those blanks take
    the background that is set now, and the panel splits over what else
    they take.

    With a background alone, five keep it: Alacritty, kitty, libvterm,
    xterm and ptterm. Ghostty and WezTerm blank the cell outright, so
    they do no colour on a delete at all.

    With reverse video set and no background, kitty and ptterm paint the
    cell with the foreground, libvterm keeps the foreground and not the
    reverse, and Alacritty and xterm keep nothing. Two, one and two
    among the judges that colour a delete at all. `erase_style` in
    `ptterm/screen.py` holds the reason ptterm paints it.

    This is the whole of `delete_chars_reset` in
    `checks.pymux-alacritty`: twelve cells at the end of one row.
    """
    keeps_background = _cells("\x1b[41mabcdef\x1b[1;1H\x1b[1P")
    for name in ("ptterm", "alacritty", "kitty", "libvterm", "xterm"):
        assert keeps_background[name][0][7].bg == ("index", 1), name
    for name in ("ghostty", "wezterm"):
        assert keeps_background[name][0][7].bg is None, name

    reversed_cells = _cells("\x1b[31;1;7;4;9mabcdef\x1b[1;1H\x1b[1P")
    for name in ("ptterm", "kitty"):
        assert reversed_cells[name][0][7].reverse, name
    for name in ("alacritty", "ghostty", "libvterm", "wezterm", "xterm"):
        assert not reversed_cells[name][0][7].reverse, name


def _cells(data, lines=3, columns=8, resize=None):
    "Every judge's whole screen, and ptterm's."
    found = {"ptterm": ptterm_cells(data, lines, columns, resize)}
    for judge in judges():
        found[judge.name] = judge.cells(data, lines, columns, resize)
    return found


def rows_of(data, lines, columns, resize):
    "What each judge holds after a resize, as one string a row."

    def text(rows):
        return ["".join(cell.char or " " for cell in row).rstrip() for row in rows]

    return {
        name: text(rows)
        for name, rows in _cells(data, lines, columns, resize).items()
    }


def test_what_the_line_drawing_set_draws_for_h():
    """
    Position 0x68 of the DEC special graphics set is the newline
    symbol, U+2424. kitty draws U+2591 LIGHT SHADE there, and it is
    alone: five judges draw the symbol.

    pyte took its table from the linux kernel, which draws the shade,
    so ptterm drew it too. Alacritty's `saved_cursor` reference test
    found it, in the "h" of a shell prompt.
    """
    held = characters_in_row("\x1b(0h", lines=3, columns=6)
    assert held["kitty"][0] == "░"
    for name in ("ptterm", "alacritty", "ghostty", "libvterm", "wezterm", "xterm"):
        assert held[name][0] == "␤", name


def test_what_the_line_drawing_set_draws_for_the_blank():
    """
    Position 0x5F of the same set is a blank, and the panel gives
    three answers for it.

    ptterm and kitty draw U+00A0, which is the mapping the table
    names. Alacritty draws a space. The other four leave the
    underscore alone: their tables start at 0x60.

    Nothing a reader sees changes, because all three are blank. This
    is the whole of `saved_cursor` in `checks.pymux-alacritty`: one
    cell. Entry 20 of `DEVIATIONS.md` holds it.
    """
    held = characters_in_row("\x1b(0_", lines=3, columns=6)
    assert held["ptterm"][0] == " "
    assert held["kitty"][0] == " "
    assert held["alacritty"][0] == " "
    for name in ("ghostty", "libvterm", "wezterm", "xterm"):
        assert held[name][0] == "_", name


def test_the_alternate_screen_gives_back_what_it_saved():
    """
    A save made on the alternate screen is still there the next time a
    program takes that screen. The whole panel agrees, six to nothing.

    "?1049h" clears the content and leaves the saved cursor alone.
    xterm holds one saved cursor per screen for the life of the
    terminal. ptterm emptied the list on the way in, so the restore
    sent the cursor home and dropped the character sets with it.
    """
    data = "\x1b[?1049h\x1b[3;5H\x1b7\x1b[?1049l\x1b[?1049h\x1b8z"
    held = characters_in_row(data, row=2, lines=6, columns=10)
    for name in ("ptterm", "alacritty", "ghostty", "kitty", "libvterm", "wezterm", "xterm"):
        assert held[name][:5] == "    z", name


# ----------------------------------------------------------------------
# Hyperlinks, which "OSC 8" carries.
#
# A link asks two questions, and the judges do not split the same way on
# both. Where does it go, and which cells are one link?
#
# libvterm answers neither. `vterm.h` names no hyperlink at all.
#
# Ghostty answers the first alone. `ghostty_grid_ref_hyperlink_uri`
# hands over the target, and nothing hands over the name that Ghostty
# gives the one link. Lillecarl/pymux#92.
#
# xterm.js answers both, through paths that `IBufferCell` does not name.
# So the panel for a target is five, and the panel for a shape is four.

#: Two shapes of a line, as every judge numbers them. xterm.js draws a
#: link with the dashed one.
CURLY = 3
DASHED = 5

#: A link opens with its parameters and its target, and closes with
#: neither.
OPEN_LINK = "\x1b]8;%s;%s\x1b\\"
CLOSE_LINK = "\x1b]8;;\x1b\\"

A_TARGET = "https://a"
ANOTHER_TARGET = "https://b"

#: Every judge that can say where a link goes, and ptterm.
TARGET_HOLDERS = ("alacritty", "ghostty", "kitty", "ptterm", "wezterm", "xterm")

#: Every judge that can say which cells are one link, and ptterm.
LINK_HOLDERS = ("alacritty", "kitty", "ptterm", "wezterm", "xterm")

#: Every judge that holds no link at all.
LINK_BLIND = ["libvterm"]

#: Every judge that the projection silences where a link is drawn, in
#: name order. It is libvterm, which holds no link, and Ghostty, whose
#: name for a link `_as_ghostty_sees` drops. Ghostty still votes on the
#: target: a difference there survives the projection and `abstained()`
#: would not name it.
LINK_ABSTAINS = ["ghostty", "libvterm"]


def link_shape(data, lines=2, columns=4):
    """
    Which cells each judge groups into one link, and ptterm.

    A link number is a number of this screen and not a name of the
    emulator: the first link that a reader meets is 1, the next is 2.
    kitty numbers a link out of its own pool, Alacritty mints a name
    from a counter of the process, and ptterm carries the target and
    the id. None of those compare, and the shape does.
    """

    def shape(rows):
        return [tuple(cell.hyperlink_id for cell in row) for row in rows]

    found = {"ptterm": shape(ptterm_cells(data, lines, columns))}
    for judge in judges():
        found[judge.name] = shape(judge.cells(data, lines, columns))
    return found


def link_targets(data, lines=2, columns=4):
    "The target that each judge puts on the first cell, and ptterm."
    found = {"ptterm": ptterm_cells(data, lines, columns)[0][0].hyperlink}
    for judge in judges():
        found[judge.name] = judge.cells(data, lines, columns)[0][0].hyperlink
    return found


def test_one_judge_holds_no_link_at_all():
    """
    The panel for a link is five judges, not six.

    libvterm keeps no link at all: `vterm.h` names none.

    Ghostty holds no name for a link, so the projection silences it
    here too. It is not blind: a wrong target would still reach the
    comparison, and the test below reads the target it gives.
    """
    data = OPEN_LINK % ("id=1", A_TARGET) + "ab" + CLOSE_LINK
    assert cannot_see(data, lines=2, columns=4) == LINK_ABSTAINS
    assert verdict(data, lines=2, columns=4) == "agree"


def test_a_link_overwrites_the_shape_of_a_line():
    """
    xterm.js draws a link as a dashed underline. It writes that into the
    cell, over whatever shape the program asked for.

    A link on its own reads as no line at all. The mark lives in the
    extended attributes, and `getUnderlineStyle` reaches them only when
    a program asked for a line too. So on that cell every judge reports
    nothing, and so does ptterm.

    A link over a curly line reads as dashed, both ways round. The curl
    is gone, and no reader can bring it back. So the shape that xterm.js
    reports on a linked cell says nothing about the program, and
    `_as_xterm_sees` drops the underline of such a cell from both sides.

    This test reads the raw answer, because the projection hides what it
    records.
    """
    data = OPEN_LINK % ("id=1", A_TARGET) + "ab" + CLOSE_LINK
    held = _cells(data, lines=2, columns=4)
    for name in ("ptterm", "alacritty", "ghostty", "kitty", "libvterm",
                 "wezterm", "xterm"):
        assert held[name][0][0].underline == 0, name

    over_a_curly = OPEN_LINK % ("id=1", A_TARGET) + "\x1b[4:3mab\x1b[m" + CLOSE_LINK
    under_a_curly = "\x1b[4:3m" + OPEN_LINK % ("id=1", A_TARGET) + "ab\x1b[m"
    for data in (over_a_curly, under_a_curly):
        held = _cells(data, lines=2, columns=4)
        assert held["xterm"][0][0].underline == DASHED
        assert held["ptterm"][0][0].underline == CURLY


def test_every_judge_that_holds_a_link_holds_its_target():
    "The target is the text a program wrote, so it compares as it is."
    data = OPEN_LINK % ("id=1", A_TARGET) + "ab" + CLOSE_LINK
    held = link_targets(data)
    for name in TARGET_HOLDERS:
        assert held[name] == A_TARGET, name
    for name in LINK_BLIND:
        assert held[name] is None, name


def test_a_link_that_a_wrap_cuts_in_two_is_one_link():
    """
    Three judges agree with ptterm: the pieces on both rows carry one
    link and not two.

    This is what the id is for. A program that draws a long link does
    not know where the terminal will break it.
    """
    data = OPEN_LINK % ("id=1", A_TARGET) + "abcdef" + CLOSE_LINK
    held = link_shape(data)
    for name in LINK_HOLDERS:
        assert held[name] == [(1, 1, 1, 1), (1, 1, None, None)], name


def test_two_ids_on_one_target_are_two_links():
    "The id says which link, and the target says where it goes."
    data = (
        OPEN_LINK % ("id=1", A_TARGET)
        + "ab"
        + OPEN_LINK % ("id=2", A_TARGET)
        + "cd"
        + CLOSE_LINK
    )
    held = link_shape(data)
    for name in LINK_HOLDERS:
        assert held[name] == [(1, 1, 2, 2), (None, None, None, None)], name


def test_two_targets_under_one_id_are_two_links():
    "One id and two targets is two links, the same way round."
    data = (
        OPEN_LINK % ("id=1", A_TARGET)
        + "ab"
        + OPEN_LINK % ("id=1", ANOTHER_TARGET)
        + "cd"
        + CLOSE_LINK
    )
    held = link_shape(data)
    for name in LINK_HOLDERS:
        assert held[name] == [(1, 1, 2, 2), (None, None, None, None)], name


def test_the_same_id_opened_again_is_the_same_link():
    """
    A link closes, plain text follows, and the same id and target open
    again. Three judges call the two runs one link, and so does ptterm.
    """
    data = (
        OPEN_LINK % ("id=1", A_TARGET)
        + "ab"
        + CLOSE_LINK
        + "xy"
        + OPEN_LINK % ("id=1", A_TARGET)
        + "cd"
    )
    held = link_shape(data)
    for name in LINK_HOLDERS:
        assert held[name] == [(1, 1, None, None), (1, 1, None, None)], name


def test_two_judges_split_a_link_that_carries_no_id():
    """
    The same target opens twice with no id, and the two runs do not
    touch. Alacritty and xterm.js call that two links. kitty and WezTerm
    call it one, and so does ptterm.

    Alacritty mints a name for every link that arrives without an id,
    out of a counter of the process, so two opens are never the same
    link. xterm.js does the same, out of a pool it keeps for the screen.
    kitty keys its pool on the id and the target together, and an empty
    id is still an id, so both opens land on one entry.

    xterm.js is not simply on Alacritty's side. It keys on the id and
    the target the way kitty does whenever there is an id: two openings
    of one target under one id are one link for it, and a wrap does not
    cut a link in two. Only the empty id sends it the other way.

    The specification of "OSC 8" is on that side: without an id, only
    cells that touch are one link. ptterm cannot take it as it stands,
    because a cell carries the target and the id and nothing that says
    which opening drew it. It sits with the larger side by accident and
    not by choice. Lillecarl/pymux#91 holds that.

    Two against two is a split, so nothing changes here.
    """
    data = (
        OPEN_LINK % ("", A_TARGET)
        + "ab"
        + CLOSE_LINK
        + "xy"
        + OPEN_LINK % ("", A_TARGET)
        + "cd"
    )
    held = link_shape(data)
    for name in ("alacritty", "xterm"):
        assert held[name] == [(1, 1, None, None), (2, 2, None, None)], name
    for name in ("kitty", "ptterm", "wezterm"):
        assert held[name] == [(1, 1, None, None), (1, 1, None, None)], name

    against, with_us = sides(data, lines=2, columns=4)
    assert against == ["alacritty", "xterm"]
    assert with_us == ["kitty", "wezterm"]
    assert cannot_see(data, lines=2, columns=4) == LINK_ABSTAINS
    assert verdict(data, lines=2, columns=4) == "split"


# ----------------------------------------------------------------------
# A reflow: what a screen holds after it changes width.
#
# The panel could not ask this until Lillecarl/pymux#64. It gave every
# judge bytes and one size, so a reflow had no vote and two findings hit
# that wall. `resize` is the size to take after the data, and every
# judge acts on it.
#
# **libvterm needs two things turned on, and it used to have neither.**
# Reflow is off until `vterm_screen_enable_reflow`, and a scrollback
# lives in whoever embeds libvterm, behind `sb_pushline` and
# `sb_popline`. `vterm_oracle.py` sets all three now
# (Lillecarl/pymux#104), so libvterm votes here like everybody else. Its
# own suite asks for the same pair with `WANTSCREEN rb`.


def test_widening_joins_a_row_that_was_wrapped():
    """
    Every judge joins a wrapped row back together, and so does ptterm.

    Ten characters on a screen four wide take three rows. At ten wide
    they take one, and the two rows below it are blank. Six to nothing,
    which is the answer a panel gives when a thing is not a choice.
    """
    found = rows_of("abcdefghij\r\n", 4, 4, (4, 10))
    for name in found:
        assert found[name] == ["abcdefghij", "", "", ""], name


def test_narrowing_splits_a_row_that_no_longer_fits():
    """
    Five judges split the row and keep every character in view, and so
    does ptterm.

    **Alacritty keeps the text and moves the viewport.** The rows it
    made go into the scrollback and the screen shows the last of them,
    so the cells that a reader sees are not the cells the others show.
    That is where the cursor is, and Alacritty puts the cursor row
    first. It is one judge against five, so ptterm follows the five.
    """
    found = rows_of("abcdefghij\r\n", 4, 10, (4, 4))
    for name in ("ptterm", "ghostty", "kitty", "libvterm", "wezterm", "xterm"):
        assert found[name] == ["abcd", "efgh", "ij", ""], name
    assert found["alacritty"] == ["ij", "", "", ""]


def test_xterm_js_leaves_the_row_the_cursor_sits_on():
    """
    xterm.js reflows every row but the one the cursor is on.

    `reflowCursorLine` is an option of xterm.js and it is off by
    default, so this is what a reader of VS Code sees. The two tests
    above move the cursor off the row with a "\\r\\n" first, and there
    xterm.js reflows like everybody else.

    **Narrowing on that row loses the text.** Ten characters on a
    screen that becomes four wide come back as four: the rest is not in
    the scrollback, it is gone. The other five judges keep it.

    The panel is not being asked to settle anything here. ptterm
    reflows the cursor row, and so do five of the six.
    """
    on_the_cursor = rows_of("abcdefghij", 4, 10, (4, 4))
    assert on_the_cursor["xterm"] == ["abcd", "", "", ""]
    for name in ("ptterm", "ghostty", "kitty", "libvterm", "wezterm"):
        assert on_the_cursor[name] == ["abcd", "efgh", "ij", ""], name

    widened = rows_of("abcdefghij", 4, 4, (4, 10))
    assert widened["xterm"] == ["abcd", "efgh", "ij", ""]
    for name in ("ptterm", "alacritty", "ghostty", "kitty", "libvterm", "wezterm"):
        assert widened[name] == ["abcdefghij", "", "", ""], name


def test_where_a_shell_prompt_lands_when_a_window_gets_wider():
    """
    **This is the case Lillecarl/pymux#57 asked about, and the panel
    answers it: ptterm is right.**

    It is libvterm's own `69screen_reflow.test`, "Shell wrapped prompt
    behaviour". Five rows ten wide hold two prompts, and the second
    "PROMPT GOES HERE" needs a continuation row. At sixteen columns it
    stops needing one, so the content is a row shorter than the screen
    that held it, and the freed row has to come from somewhere.

    ptterm anchors the top and pulls a row down from the history.
    Alacritty, Ghostty, WezTerm and xterm.js all land in the same place.
    Four judges and ptterm.

    **libvterm pulls a row down as well.** It differs on one thing only:
    it copies the popped row cell for cell and does not wrap it again,
    so row 0 holds `S HERE` and not the whole prompt (`src/screen.c`
    line 684). Where the freed row comes from is the question this case
    asks, and libvterm answers it the way ptterm does.

    The expectation written in `69screen_reflow.test` is neither. It is
    what the suite harness does with the scrollback turned off, where
    `sb_popline` gives nothing back and the text moves up instead. So
    the seven assertions in `vterm-failures.txt` are the harness and not
    libvterm.

    kitty leaves the freed row blank at the bottom, so the first prompt
    never comes back. It is alone: five judges and ptterm fill the row
    from the top.
    """
    prompt = "PROMPT GOES HERE\r\n> \r\n\r\nPROMPT GOES HERE\r\n> "
    found = rows_of(prompt, 5, 10, (5, 16))
    for name in ("ptterm", "alacritty", "ghostty", "wezterm", "xterm"):
        assert found[name] == [
            "PROMPT GOES HERE",
            ">",
            "",
            "PROMPT GOES HERE",
            ">",
        ], name
    assert found["kitty"] == [">", "", "PROMPT GOES HERE", ">", ""]
    assert found["libvterm"] == ["S HERE", ">", "", "PROMPT GOES HERE", ">"]


def test_a_narrower_width_that_needs_no_reflow_moves_nothing():
    "Every judge agrees when the text already fits, libvterm included."
    found = rows_of("one\r\ntwo\r\nthree\r\nfour\r\nfive", 3, 8, (3, 16))
    for name in found:
        assert found[name] == ["three", "four", "five"], name


def test_an_erase_at_the_end_of_a_line_ends_the_wrap_out_of_it():
    """
    Every judge agrees, and so does ptterm: an erase that clears the end
    of a line ends the join, and a later widening does not put the two
    rows back together.

    Fifteen characters on ten columns wrap onto row 1. Go back up a row,
    to column 9, and erase to the end. Nothing wraps out of row 0 any
    more. Widening to twenty columns leaves two rows.

    libvterm asks for this in `32state_flow.test`, and until
    Lillecarl/pymux#64 it was the only thing that could: the mark that
    decides a join is not a cell, so no judge reports it, and it shows
    from outside only through a resize. The panel can ask now, and the
    answer is six to nothing.

    Lillecarl/pymux#58 worried that the mark would put the rows back
    together. `_end_the_wrap_out_of_this_line` in `ptterm/screen.py`
    takes it off, and this is that fix seen from outside.
    """
    erased = rows_of("D" * 15 + "\x1bM\x1b[9G\x1b[K", 3, 10, (3, 20))
    for name in erased:
        assert erased[name] == ["DDDDDDDD", "DDDDD", ""], name

    # Without the erase the same widening joins them, so the test above
    # is not passing because nothing ever joins.
    kept = rows_of("D" * 15, 3, 10, (3, 20))
    for name in ("ptterm", "alacritty", "ghostty", "kitty", "libvterm", "wezterm"):
        assert kept[name] == ["D" * 15, "", ""], name
    # xterm.js leaves the row the cursor sits on, as the test above says.
    assert kept["xterm"] == ["DDDDDDDDDD", "DDDDD", ""]


# ----------------------------------------------------------------------
# The baseline: "SGR 73" raises a glyph, "SGR 74" lowers it and
# "SGR 75" puts it back.
#
# Two judges hold it. libvterm keeps a `baseline` of two bits beside a
# `small` bit (`vterm.h` lines 514 and 515), and WezTerm keeps a
# `VerticalAlign` of the same three values. The other four hold nothing:
# `ghostty/vt/sgr.h` names no superscript, xterm.js has no such
# attribute, and neither kitty nor Alacritty reads the codes at all.
#
# So the panel here is two, and the projection of the other four drops
# the field. Lillecarl/pymux#59.

RAISED = 1
LOWERED = 2

#: Every judge that can say where a glyph sits, and ptterm.
BASELINE_HOLDERS = ("libvterm", "ptterm", "wezterm")

#: Every judge that holds no baseline at all.
BASELINE_BLIND = ("alacritty", "ghostty", "kitty", "xterm")


def baseline_of(data, lines=1, columns=4):
    "Where each judge puts the glyph of the first cell, and ptterm."
    return {
        name: rows[0][0].baseline
        for name, rows in _cells(data, lines, columns).items()
    }


def test_two_judges_raise_a_glyph_for_sgr_73():
    found = baseline_of("\x1b[73mx")
    assert found["libvterm"] == RAISED
    assert found["wezterm"] == RAISED
    for name in BASELINE_BLIND:
        assert found[name] == 0, name


def test_the_same_two_judges_lower_a_glyph_for_sgr_74():
    found = baseline_of("\x1b[74mx")
    assert found["libvterm"] == LOWERED
    assert found["wezterm"] == LOWERED
    for name in BASELINE_BLIND:
        assert found[name] == 0, name


def test_sgr_75_puts_the_glyph_back_on_the_line():
    found = baseline_of("\x1b[73m\x1b[75mx")
    for name in found:
        assert found[name] == 0, name


def test_sgr_0_puts_the_glyph_back_on_the_line():
    found = baseline_of("\x1b[74m\x1b[0mx")
    for name in found:
        assert found[name] == 0, name


def test_a_raised_glyph_leaves_ptterm_alone():
    """
    ptterm raises the glyph and the two judges that can see it agree.

    The other four abstain. They answer 0, ptterm answers 1, and their
    projection drops the field, so the difference is exactly what they
    do not hold.
    """
    assert verdict("\x1b[73mx", lines=1, columns=4) == "agree"
    assert cannot_see("\x1b[73mx", lines=1, columns=4) == list(BASELINE_BLIND)
