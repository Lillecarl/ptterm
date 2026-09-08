"""
What xterm itself draws, where the panel has nothing to say.

The six judges hold a whole cell and vote. xterm holds a character, so
it does not vote: `panel.py` says why, and `xterm_oracle.py` says how
it is asked.

It is asked four kinds of question here.

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
- The questions that are still open on their own. xterm answers three
  of those the same way, and Lillecarl/pymux#107 says why they are one
  question: ptterm drops the wait to wrap where xterm keeps it.
"""

import pytest

from panel import what_ptterm_draws, what_xterm_draws, xterm_is_here
from pyte.sequences import Csi, csi
from pyte import escape
from pyte.sequences import Escape, Sharp, esc, sharp
from pyte.modes import PrivateMode
from pyte.sequences import reset_mode, set_mode

pytestmark = pytest.mark.skipif(not xterm_is_here(), reason="xterm has no display here")


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
    (
        "a\r\nb\r\nc\r\nd"
        + set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(Csi.SU, 2)
    ),
    (
        "a\r\nb\r\nc\r\nd"
        + set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(Csi.SD, 2)
    ),
    (
        "abcd\r\nefgh\r\nijkl"
        + set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.CUP, 2, 3)
        + csi(escape.IL)
    ),
    (
        "abcd\r\nefgh\r\nijkl"
        + set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.CUP, 2, 3)
        + csi(escape.DL)
    ),
    (
        "abcdefg"
        + set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 5)
        + csi(escape.CUP, 1, 3)
        + csi(escape.ICH)
    ),
    (
        "abcdefg"
        + set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 5)
        + csi(escape.CUP, 1, 3)
        + csi(escape.DCH)
    ),
    (
        "a\r\nb\r\nc\r\nd"
        + set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.DECSTBM, 2, 4)
        + csi(escape.CUP, 4, 3)
        + "\n"
    ),
]

#: The four programs of `test_the_columns_of_a_region_stand_apart`.
#: Two judges carry DECIC and DECDC, and no judge carries DECBI or
#: DECFI. `DEVIATIONS.md` entry 11.
COLUMNS_OF_A_REGION = [
    "abcdefg\r\nABCDEFG" + csi(escape.CUP, 1, 2) + csi(Csi.DECIC),
    "abcdefg\r\nABCDEFG" + csi(escape.CUP, 1, 2) + csi(Csi.DECDC),
    "x" + csi(escape.CUP, 1, 1) + esc(Escape.DECBI),
    csi(escape.CUP, 1, 24) + "x" + csi(escape.CUP, 1, 24) + esc(Escape.DECFI),
]

#: The four programs of `test_no_judge_carries_a_rectangle_command`,
#: each on the screen that `DECCRATests` draws. `DEVIATIONS.md` entry
#: 12.
RECTANGLES = [
    "abcdefg\r\nABCDEFG\r\nhijklmn\r\nHIJKLMN\r\nopqrstu" + command
    for command in [
        csi(Csi.DECFRA, 37, 2, 2, 4, 4),
        csi(Csi.DECERA, 2, 2, 4, 4),
        csi(Csi.DECSERA, 2, 2, 4, 4),
        csi(Csi.DECCRA, 2, 2, 4, 4, 1, 5, 5, 1),
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
            esc(escape.DECSC) + csi(escape.CUP, 1, 1) + esc(escape.DECRC) + "b",
            (
                set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
                + "x"
                + reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
                + "b"
            ),
            esc(escape.DECSC) + esc(escape.DECRC) + "b",
        )
    ]
    assert landed == ["a", "a", "a"]

    # The restore puts the column back as well as the wait. "CSI D"
    # clears the wait and moves one column left, so the "b" lands one
    # left of the last column and the "a" there stays.
    with_a_move = what_xterm_draws(
        fill
        + (
            esc(escape.DECSC)
            + csi(escape.CUP, 1, 1)
            + esc(escape.DECRC)
            + csi(escape.CUB)
            + "b"
        ),
        4,
        6,
    )
    assert with_a_move[0] == "aaaaba"


def test_xterm_wraps_rather_than_moving_back_over_a_tab_stop():
    """
    Entry 9 of `DEVIATIONS.md`.

    "CSI I" twice puts a "y" in the last column, which leaves the
    cursor waiting to wrap. "CSI Z" then asks for one tab stop back.

    ptterm moves the cursor to column 16 and draws the "z" there, and
    kitty, libvterm and WezTerm do the same. Alacritty, Ghostty and
    xterm.js draw it at the start of the next row, all three of them.
    Three against three.

    **xterm draws it at the start of the next row too**, so the tally
    is four against three and ptterm is on the smaller side.

    **The cursor does move.** A checksum says where a character landed
    and not where the cursor stood, so the second probe asks. "CSI D"
    moves the cursor one column left, and it clears the wait to wrap in
    every terminal. The "z" then lands at column 15, which is one left
    of 16, so CBT had moved the cursor back a tab stop after all. What
    outlives CBT is the wait, not the column: the cursor stands at 16
    and the next character wraps anyway.
    """
    program = csi(Csi.CHT) + "x" + csi(Csi.CHT, 2) + "y" + csi(Csi.CBT) + "z"

    def where(rows, glyph):
        return next((y, row.index(glyph)) for y, row in enumerate(rows) if glyph in row)

    drawn = what_xterm_draws(program, lines=8, columns=24)
    ours = what_ptterm_draws(program, lines=8, columns=24)
    assert [where(drawn, one) for one in "xyz"] == [(0, 8), (0, 23), (1, 0)]
    assert [where(ours, one) for one in "xyz"] == [(0, 8), (0, 23), (0, 16)]

    with_a_move = what_xterm_draws(
        (
            csi(Csi.CHT)
            + "x"
            + csi(Csi.CHT, 2)
            + "y"
            + csi(Csi.CBT)
            + csi(escape.CUB)
            + "z"
        ),
        8,
        24,
    )
    assert where(with_a_move, "z") == (0, 15)


def test_xterm_keeps_the_wait_to_wrap_through_a_tab():
    """
    The same wait, through HT, where ptterm already follows the panel.

    `test_the_panel.py::test_a_tab_at_the_right_margin_follows_the_panel`
    holds this one. ptterm used to clear the wait on a tab, so the
    character after the tab landed over the one that was there. Every
    judge put it on the next row instead, and the only thing on the
    other side was a reading of a document: xterm says a cursor move
    clears the wait, and a tab is a cursor move. The panel won and
    `tab()` changed.

    **xterm puts the "X" on the next row as well.** So the document was
    read wrong and the panel had xterm with it all along. That matters
    for Lillecarl/pymux#107: ptterm already made this exact change once,
    in one place, and three more places still drop the wait.
    """
    drawn = what_xterm_draws(csi(escape.CUP, 1, 20) + "12345\tX", lines=8, columns=24)
    assert [(y, row.index("X")) for y, row in enumerate(drawn) if "X" in row] == [
        (1, 0)
    ]


def test_xterm_reads_the_parameters_it_needs_out_of_too_many():
    """
    Entry 3 of `DEVIATIONS.md`.

    Alacritty, libvterm and xterm.js read the parameters they need out
    of a sequence that carries too many, and ptterm does too. Ghostty,
    kitty and WezTerm drop the sequence whole. Three against three.

    **xterm reads them.** The tally is four against three, and this
    time ptterm is on the larger side.
    """
    drawn, ours = both(csi(escape.CHA, 3, 9, 9) + "X", lines=4, columns=8)
    assert drawn == ours


# ----------------------------------------------------------------------
# The differences the panel already settled, put to xterm as well. None
# of these changes a decision. They fill the last column in the table of
# `DEVIATIONS.md`, so that a reader sees a measurement where the entry
# says "xterm does" and not a claim.


@pytest.mark.parametrize(
    "number, data, lines, columns",
    [
        (1, csi(escape.CUP, 8, 20) + "12345\t", 6, 20),
        (
            2,
            (
                set_mode(PrivateMode.ALTERNATE_SCREEN_AGAIN)
                + " X "
                + reset_mode(PrivateMode.ALTERNATE_SCREEN_AGAIN)
                + " "
                + set_mode(PrivateMode.ALTERNATE_SCREEN)
            ),
            3,
            6,
        ),
        (4, "ab" + sharp(Sharp.DECALN) + "X", 4, 6),
        (5, "\n\x080", 4, 8),
        (6, "a\r\nb" + csi(Csi.SU, 0), 4, 8),
    ],
)
def test_a_settled_difference_reads_the_way_xterm_reads_it(
    number, data, lines, columns
):
    "Entries 1, 2, 4, 5 and 6 of `DEVIATIONS.md`, in that order."
    drawn, ours = both(data, lines=lines, columns=columns)
    assert drawn == ours, number


# ----------------------------------------------------------------------
# The questions that are still open. Each is about where a character
# lands, so xterm answers each, and none is settled here.


def test_where_xterm_leaves_the_cursor_on_the_newest_alternate_mode():
    """
    Lillecarl/pymux#34, and entry 17 of `DEVIATIONS.md`.

    ptterm sends the cursor home when a program takes the alternate
    screen with "?1049", so the "X" lands at row 0, column 0. Alacritty,
    Ghostty, libvterm and xterm.js leave the cursor where it stood, so
    the "X" lands at row 1, column 2. kitty and WezTerm are with ptterm.
    Four against two.

    **xterm leaves the cursor.** Its own description of the mode says
    what it does and does not mention a move: "Save cursor as in DECSC.
    After saving the cursor, switch to the Alternate Screen Buffer,
    clearing it first." So the tally is five against two, and the
    document the issue quotes is the terminal that wrote it.
    """
    drawn = what_xterm_draws(
        (
            csi(escape.CUP, 2, 3)
            + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
            + "X"
        ),
        lines=3,
        columns=6,
    )
    assert [(y, row.index("X")) for y, row in enumerate(drawn) if "X" in row] == [
        (1, 2)
    ]


def test_where_xterm_draws_after_the_screen_goes_back_under_another_name():
    """
    Lillecarl/pymux#35.

    A program takes the alternate screen with "?1049", draws to the end
    of the row, and gives the screen back with "?47". The hunt found
    this and hypothesis cut it down; the panel calls it a split, so it
    is a choice and not a fault.

    ptterm draws the last "0" where the cursor stood, at row 0 column
    23. kitty, WezTerm, Ghostty and xterm.js draw it somewhere else.
    The size is the one the hunt uses.

    **xterm draws it at row 1, column 0.** The three wide characters
    fill the row to the last column, which leaves the cursor waiting to
    wrap, and giving the screen back does not clear that wait. So the
    "0" wraps.

    This is the same flag as entry 9 and entry 22: ptterm drops the
    wait where xterm keeps it. Lillecarl/pymux#107 holds the three
    together.
    """
    program = (
        set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + csi(escape.CHA, 14)
        + "00000你你你"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN)
        + "0"
    )

    def marks(rows):
        return [
            (y, x)
            for y, row in enumerate(rows)
            for x, one in enumerate(row)
            if one != " "
        ]

    assert marks(what_xterm_draws(program, lines=8, columns=24)) == [(1, 0)]
    assert marks(what_ptterm_draws(program, lines=8, columns=24)) == [(0, 23)]

    # The cursor is in the last column, as it is for ptterm. "CSI D"
    # clears the wait and moves one column left, and the "0" lands
    # there.
    with_a_move = (
        set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + csi(escape.CHA, 14)
        + "00000你你你"
        + reset_mode(PrivateMode.ALTERNATE_SCREEN)
        + csi(escape.CUB)
        + "0"
    )
    assert marks(what_xterm_draws(with_a_move, lines=8, columns=24)) == [(0, 22)]


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


# ----------------------------------------------------------------------
# The instrument itself.


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
