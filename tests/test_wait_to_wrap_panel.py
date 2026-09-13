"""
Where every judge leaves a cursor that waits to wrap.

A character in the last column leaves the cursor **waiting to wrap**:
the next character starts a new row. Lillecarl/pymux#107 says three
open questions are one, because ptterm drops that wait in three places
where xterm keeps it -- a tab stop move (Lillecarl/pymux#106), a save
and a restore (Lillecarl/pymux#88), and giving the alternate screen
back (Lillecarl/pymux#35).

Lillecarl/pymux#106 named what nobody had measured: whether the judges
that differ from ptterm agree with xterm, or only that they differ.
This file measures it, for all three. They agree, every time, and one
of the three was not a split at all:

| case | the wait survives | it does not |
| --- | --- | --- |
| over a tab stop | xterm, alacritty, ghostty, xtermjs, **ptterm** | kitty, libvterm, wezterm |
| a save and a restore | xterm, alacritty, ghostty, wezterm, **ptterm** | kitty, libvterm, xtermjs |
| giving the screen back | every judge, xterm and **ptterm** | nobody |

**The third row is why this file exists.** `verdict()` called it a
split, and it was not one: alacritty and libvterm disagree with ptterm
about something else in the same program -- what `?47l` leaves on the
screen -- and a judge that differs for two reasons makes the vote read
as a split. On the cursor the seven were unanimous, and ptterm was the
one that was wrong.

ptterm carries the wait through all three now (Lillecarl/pymux#107),
so the judges that differ here are the ones that drop it.
`pyte/tests/test_the_wait_to_wrap_is_cursor_state.py` is the gate on
what ptterm does; this file is the record of what the others do.
"""

import pytest

from panel import abstained, report

#: `CSI I` twice, then one tab stop back, then a character. The "y"
#: lands in the last column, which leaves the cursor waiting to wrap.
OVER_A_TAB_STOP = "\x1b[Ix\x1b[2Iy\x1b[Zz"

#: Six columns filled, a save, a move home, a restore, one character.
#: `b` on the next row means the wait came back.
SAVE_AND_RESTORE = "aaaaaa\x1b7\x1b[1;1H\x1b8b"

#: The alternate screen taken, filled to the last column with a wide
#: character, and given back under the older name.
GIVING_BACK_THE_SCREEN = "\x1b[?1049h\x1b[14G00000你你你\x1b[?47l0"

CASES = [
    ("over a tab stop", OVER_A_TAB_STOP, 8, 24),
    ("a save and a restore", SAVE_AND_RESTORE, 6, 6),
    ("giving the screen back", GIVING_BACK_THE_SCREEN, 6, 24),
]


def _readings(data: str, lines: int, columns: int) -> dict:
    """
    What each judge that differs from ptterm drew, by judge.

    A judge's own name comes out of the words, so that two judges that
    drew the same screen compare equal.
    """
    said = report(data, lines=lines, columns=columns)
    blind = set(abstained(data, lines=lines, columns=columns))
    return {
        name: tuple(line.replace(name, "<judge>") for line in found)
        for name, found in said.items()
        if found and name not in blind
    }


def _where_the_cursor_went(drawn) -> tuple:
    """
    The part of one judge's answer that is about the cursor.

    A judge can differ from ptterm for more than one reason in one
    program, and one of the three does. The cell ptterm wrote the last
    character into is the cell this question is about: the judge draws
    a blank there and ptterm does not.
    """
    return tuple(line for line in drawn if "<judge> Cell(char=' '" in line)


@pytest.mark.parametrize("name,data,lines,columns", CASES)
def test_every_judge_that_differs_draws_the_same_cursor(name, data, lines, columns):
    """
    The measurement Lillecarl/pymux#106 asked for.

    Each judge that differs from ptterm draws something; whether they
    draw the **same** thing is what says how strong the reading is.
    They did, which is what made the three one decision.
    """
    answers = _readings(data, lines, columns)
    cursors = {judge: _where_the_cursor_went(drawn) for judge, drawn in answers.items()}
    assert len(set(cursors.values())) <= 1, "%s: they do not agree: %r" % (name, cursors)


@pytest.mark.parametrize(
    "name,data,lines,columns,drop_the_wait",
    [
        ("over a tab stop", OVER_A_TAB_STOP, 8, 24, {"kitty", "libvterm", "wezterm"}),
        (
            "a save and a restore",
            SAVE_AND_RESTORE,
            6,
            6,
            {"kitty", "libvterm", "xtermjs"},
        ),
        # Nobody drops it here. alacritty and libvterm still differ
        # from ptterm in this program, over what `?47l` leaves on the
        # screen, which is a question of its own and not this one.
        (
            "giving the screen back",
            GIVING_BACK_THE_SCREEN,
            6,
            24,
            {"alacritty", "libvterm"},
        ),
    ],
)
def test_the_tally_is_what_the_issues_say(name, data, lines, columns, drop_the_wait):
    """
    Who differs from ptterm, held so that a reading which moves is a
    test that fails and has to be read again.

    ptterm carries the wait now, so a judge that differs is one that
    drops it -- except on the third, where the two that differ do so
    for another reason entirely.
    """
    assert set(_readings(data, lines, columns)) == drop_the_wait
