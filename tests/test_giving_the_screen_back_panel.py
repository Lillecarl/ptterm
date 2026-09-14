"""
What `?47l` leaves on the screen, and what xterm says about it.

A program can take the alternate screen under one name and give it
back under another:

    \x1b[?1049h ... \x1b[?47l

`?1049h` saves the cursor, switches to the alternate screen and clears
it. `?47l` is the older, smaller mode: it switches back and says
nothing about saving or clearing. So the two are not a pair, and what
the original screen holds afterwards is not written down anywhere the
judges agree on.

The panel splits five to two. `test_wait_to_wrap_panel.py` met it while
measuring something else, and it is the reason `verdict()` read a
unanimous cursor reading as a split: a judge that differs for two
reasons in one program cannot agree cell for cell with one that differs
for one. Lillecarl/pymux#328.

**xterm is what this file adds.** It holds a character rather than a
whole cell, so it does not vote in the panel, and `what_xterm_draws`
asks it on its own. It is the terminal the mode comes from, so its
answer is worth more than one vote.

Nothing here changes ptterm. This is the record of what the others do,
the way `test_wait_to_wrap_panel.py` is.
"""

import pytest

from panel import (
    abstained,
    report,
    what_ptterm_draws,
    what_xterm_draws,
    xterm_is_here,
)

#: The alternate screen taken with `?1049h`, filled to the last column,
#: and given back with the older `?47l`. The same program as
#: `test_wait_to_wrap_panel.GIVING_BACK_THE_SCREEN`, which asks about
#: the cursor; this file asks what row 0 holds.
GIVING_BACK_THE_SCREEN = "\x1b[?1049h\x1b[14G00000你你你\x1b[?47l0"

LINES = 6
COLUMNS = 24

#: What the alternate screen had in row 0, from column 14. A judge that
#: keeps the alternate content leaves this behind.
WRITTEN_ON_THE_ALTERNATE = "00000你你你"


def _row_zero(drawn):
    "Row 0 with the trailing blanks taken off."
    return drawn[0].rstrip()


def test_ptterm_gives_back_the_original_row():
    """
    ptterm answers with the original screen's row 0, which is empty
    here: nothing was written to it before `?1049h`.
    """
    assert WRITTEN_ON_THE_ALTERNATE not in _row_zero(
        what_ptterm_draws(GIVING_BACK_THE_SCREEN, LINES, COLUMNS)
    )


@pytest.mark.skipif(not xterm_is_here(), reason="xterm has no display here")
def test_xterm_gives_back_the_original_row():
    """
    The measurement Lillecarl/pymux#328 named as missing.

    xterm is where `?47` and `?1049` both come from, so what it does
    with the two mixed is the closest thing to a rule there is.
    """
    row = _row_zero(what_xterm_draws(GIVING_BACK_THE_SCREEN, LINES, COLUMNS))
    assert WRITTEN_ON_THE_ALTERNATE not in row, (
        "xterm keeps the alternate content: row 0 is %r" % (row,)
    )


def test_the_split_is_who_the_issue_says():
    """
    Who keeps the alternate content, held so that a reading which moves
    is a test that fails and has to be read again.
    """
    said = report(GIVING_BACK_THE_SCREEN, lines=LINES, columns=COLUMNS)
    blind = set(abstained(GIVING_BACK_THE_SCREEN, lines=LINES, columns=COLUMNS))

    kept = {
        name
        for name, found in said.items()
        if name not in blind
        and any(WRITTEN_ON_THE_ALTERNATE[0] in line for line in found)
    }
    assert kept == {"alacritty", "libvterm"}
