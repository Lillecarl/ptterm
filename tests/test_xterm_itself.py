"""
What xterm itself draws, where the panel has nothing to say.

The six judges hold a whole cell and vote. xterm holds a character, so
it does not vote: `panel.py` says why, and `xterm_oracle.py` says how
it is asked.

It is asked three kinds of question here.

- The sequences that no judge carries. Three entries of
  `DEVIATIONS.md` say some form of "no judge carries this, and xterm
  does", and ptterm stands on the word of a suite in all three. This
  file is the measurement behind that word.
- The splits where the panel is three against three. Each of those is
  about which character lands where, which is what xterm answers, so
  xterm breaks the tie. Two of the three go against ptterm, and
  neither is changed here: the rule is that a tally with ptterm on it
  goes to the user.
- The differences the panel already settled. Nothing there changes.
  The answers fill the last column of the table in `DEVIATIONS.md`, so
  that a reader sees a measurement and not a claim.
"""
import pytest

from panel import what_ptterm_draws, what_xterm_draws, xterm_is_here

pytestmark = pytest.mark.skipif(
    not xterm_is_here(), reason="xterm has no display here"
)


def both(data, lines=3, columns=8):
    "What xterm draws and what ptterm draws, as rows of text."
    return what_xterm_draws(data, lines, columns), what_ptterm_draws(
        data, lines, columns
    )


def test_xterm_answers_at_all():
    assert what_xterm_draws("hi", lines=2, columns=4) == ["hi  ", "    "]


def test_a_cell_nobody_wrote_reads_as_a_space():
    assert what_xterm_draws("", lines=2, columns=3) == ["   ", "   "]


def test_it_holds_a_character_that_is_not_ascii():
    assert what_xterm_draws("å─", lines=1, columns=4) == ["å─  "]


def test_the_two_draw_the_same_plain_screen():
    drawn, ours = both("one\r\ntwo")
    assert drawn == ours


#: The seven programs of `test_the_judges_that_carry_margins_agree`.
#: Three judges carry DECSLRM and three drop it, so the panel reads
#: three against three. `DEVIATIONS.md` entry 10 says the three that
#: drop it are missing a feature, on the word of esctest2.
MARGINS = [
    "a\r\nb\r\nc\r\nd\x1b[?69h\x1b[2;4s\x1b[2S",
    "a\r\nb\r\nc\r\nd\x1b[?69h\x1b[2;4s\x1b[2T",
    "abcd\r\nefgh\r\nijkl\x1b[?69h\x1b[2;4s\x1b[2;3H\x1b[L",
    "abcd\r\nefgh\r\nijkl\x1b[?69h\x1b[2;4s\x1b[2;3H\x1b[M",
    "abcdefg\x1b[?69h\x1b[2;5s\x1b[1;3H\x1b[@",
    "abcdefg\x1b[?69h\x1b[2;5s\x1b[1;3H\x1b[P",
    "a\r\nb\r\nc\r\nd\x1b[?69h\x1b[2;4s\x1b[2;4r\x1b[4;3H\n",
]

#: The four programs of `test_the_columns_of_a_region_stand_apart`.
#: Two judges carry DECIC and DECDC, and no judge carries DECBI or
#: DECFI. `DEVIATIONS.md` entry 11.
COLUMNS_OF_A_REGION = [
    "abcdefg\r\nABCDEFG\x1b[1;2H\x1b['}",
    "abcdefg\r\nABCDEFG\x1b[1;2H\x1b['~",
    "x\x1b[1;1H\x1b6",
    "\x1b[1;24Hx\x1b[1;24H\x1b9",
]

#: The four programs of `test_no_judge_carries_a_rectangle_command`,
#: each on the screen that `DECCRATests` draws. `DEVIATIONS.md` entry
#: 12.
RECTANGLES = [
    "abcdefg\r\nABCDEFG\r\nhijklmn\r\nHIJKLMN\r\nopqrstu" + command
    for command in [
        "\x1b[37;2;2;4;4$x",
        "\x1b[2;2;4;4$z",
        "\x1b[2;2;4;4${",
        "\x1b[2;2;4;4;1;5;5;1$v",
    ]
]


@pytest.mark.parametrize("data", MARGINS)
def test_the_margins_draw_what_xterm_draws(data):
    """
    Left and right margins, which three of the six judges drop.

    The panel reads three against three there, and a tally of three is
    not a decision. ptterm follows xterm because esctest2 sets a margin
    in 73 of its tests. This is xterm saying it itself, on the same
    seven programs.
    """
    drawn, ours = both(data, lines=8, columns=24)
    assert drawn == ours


@pytest.mark.parametrize("data", COLUMNS_OF_A_REGION)
def test_the_columns_of_a_region_draw_what_xterm_draws(data):
    """
    DECIC, DECDC, DECBI and DECFI.

    Two judges carry the first pair and none carries the second, so the
    panel had nothing to say about "ESC 6" and "ESC 9" at all: six
    judges that do nothing read the same as six that disagree. xterm
    carries all four.
    """
    drawn, ours = both(data, lines=4, columns=24)
    assert drawn == ours


@pytest.mark.parametrize("data", RECTANGLES)
def test_a_rectangle_command_draws_what_xterm_draws(data):
    """
    DECFRA, DECERA, DECSERA and DECCRA, which no judge carries.

    Fifteen probes of the panel end in six abstentions. This is the
    same screen, put to the emulator that the suite speaks for.
    """
    drawn, ours = both(data, lines=6, columns=8)
    assert drawn == ours


# ----------------------------------------------------------------------
# The splits where the panel is three against three. A tally of three
# decides nothing. Each of these is about which character lands where,
# which is the one question xterm answers, so xterm is the seventh
# voice and it breaks the tie.
#
# Two of the three go against ptterm. Neither is changed here: ptterm
# still sits with three judges in each, and the rule for that is that
# the user decides. These tests write down what xterm says, so that the
# decision rests on a measurement.


def test_xterm_brings_the_wait_to_wrap_back_through_a_restore():
    """
    Entry 22 of `DEVIATIONS.md`, and Lillecarl/pymux#88.

    A character in the last column leaves the cursor waiting to wrap.
    Alacritty, Ghostty and WezTerm bring that wait back through a
    restore, so the "b" wraps and the "a" in the last column stays.
    kitty, libvterm and xterm.js do not, so the "b" lands over the "a".
    Three against three, and ptterm is with the second three.

    **xterm is with the first three, in all three programs.** So the
    tally is four against three, and ptterm is on the smaller side. The
    third program is the strongest: with no move between the save and
    the restore, libvterm joins the first three and it is five to two.

    `test_the_panel.py::test_whether_a_restore_brings_the_wait_to_wrap_back`
    holds the tally of the six.
    """
    fill = "a" * 6
    landed = [
        what_xterm_draws(fill + tail, lines=4, columns=6)[0][5]
        for tail in (
            "\x1b7\x1b[1;1H\x1b8b",
            "\x1b[?1049hx\x1b[?1049lb",
            "\x1b7\x1b8b",
        )
    ]
    assert landed == ["a", "a", "a"]


def test_xterm_wraps_rather_than_moving_back_over_a_tab_stop():
    """
    Entry 9 of `DEVIATIONS.md`.

    "CSI I" twice puts a "y" in the last column, which leaves the
    cursor waiting to wrap. "CSI Z" then asks for one tab stop back.

    ptterm moves the cursor to column 16 and draws the "z" there, and
    kitty, libvterm and WezTerm do the same. Alacritty, Ghostty and
    xterm.js land somewhere else. Three against three.

    **xterm draws the "z" at the start of the next row.** The wait to
    wrap outlives CBT there, and the cursor never moves back. So the
    tally is four against three, and ptterm is on the smaller side.
    """
    program = "\x1b[Ix\x1b[2Iy\x1b[Zz"

    def where(rows, glyph):
        return next(
            (y, row.index(glyph)) for y, row in enumerate(rows) if glyph in row
        )

    drawn = what_xterm_draws(program, lines=8, columns=24)
    ours = what_ptterm_draws(program, lines=8, columns=24)
    assert [where(drawn, one) for one in "xyz"] == [(0, 8), (0, 23), (1, 0)]
    assert [where(ours, one) for one in "xyz"] == [(0, 8), (0, 23), (0, 16)]


def test_xterm_reads_the_parameters_it_needs_out_of_too_many():
    """
    Entry 3 of `DEVIATIONS.md`.

    Alacritty, libvterm and xterm.js read the parameters they need out
    of a sequence that carries too many, and ptterm does too. Ghostty,
    kitty and WezTerm drop the sequence whole. Three against three.

    **xterm reads them.** The tally is four against three, and this
    time ptterm is on the larger side.
    """
    drawn, ours = both("\x1b[3;9;9GX", lines=4, columns=8)
    assert drawn == ours


# ----------------------------------------------------------------------
# The differences the panel already settled, put to xterm as well. None
# of these changes a decision. They fill the column in the table of
# `DEVIATIONS.md`, so that a reader sees a measurement where the entry
# says "xterm does" and not a claim.


@pytest.mark.parametrize(
    "number, data, lines, columns",
    [
        (1, "\x1b[8;20H12345\t", 6, 20),
        (2, "\x1b[?1047h X \x1b[?1047l \x1b[?47h", 3, 6),
        (4, "ab\x1b#8X", 4, 6),
        (5, "\n\x080", 4, 8),
        (6, "a\r\nb\x1b[0S", 4, 8),
    ],
)
def test_a_settled_difference_reads_the_way_xterm_reads_it(
    number, data, lines, columns
):
    "Entries 1, 2, 4, 5 and 6 of `DEVIATIONS.md`, in that order."
    drawn, ours = both(data, lines=lines, columns=columns)
    assert drawn == ours, number


def test_what_xterm_draws_for_the_blank_of_the_line_drawing_set():
    """
    Entry 20 of `DEVIATIONS.md`, which is open.

    Position 0x5F of the DEC special graphics set is a blank, and the
    panel gives three answers. ptterm and kitty draw U+00A0, which is
    the mapping that Markus Kuhn's table names and that xterm's own
    documentation carries. Alacritty draws U+0020. Ghostty, libvterm,
    WezTerm and xterm.js leave the underscore alone.

    **xterm gives a fourth answer: it draws nothing at all.**
    `xtermCharSetDec` in `charsets.c` maps position 0x5F of the set to
    0, and a cell of 0 never takes the `CHARDRAWN` mark. So a program
    that reads the cell back gets a space, because the checksum counts
    an undrawn cell as one. Asking again with `csDRAWN` off, which
    skips an undrawn cell rather than counting it, gives nothing at
    all, and that is how the two are told apart.

    So the panel gives three answers, xterm gives a fourth, and none of
    them is what the other three are. Nothing to follow.
    """
    assert what_xterm_draws("\x1b(0_", lines=3, columns=6)[0][0] == " "


def test_a_whole_screen_of_eighty_columns_comes_back():
    """
    A screen of 24 by 80 is 1920 queries and 1920 answers.

    Neither fits in a pty. A judge that wrote every query first would
    fill the buffer while xterm waited for room to answer, and the two
    would wait for each other. `_Xterm._talk` writes and reads at once
    for that reason, and this is the probe that would hang without it.
    """
    program = "".join("%d\r\n" % (number % 10) for number in range(24))
    drawn, ours = both(program, lines=24, columns=80)
    assert drawn == ours
