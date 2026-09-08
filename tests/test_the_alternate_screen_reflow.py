"""
What a resize does to the alternate screen. Lillecarl/pymux#192.

pyte used to reflow the alternate screen the way it reflows any other,
and a reflow can leave it holding more rows than it can show. The pane
drew the last screenful; copy mode read the whole buffer and offered
the rows above the top as well, so the two disagreed about what was on
screen.

The issue asked a question before it asked for a fix: **should the
alternate screen reflow at all?** It is the screen a full-screen
program owns and redraws, and a resize there is a signal to the
program.

That is a vote and not a rule, so the panel answered it. The issue
guessed the second of its three ways out -- reflow, and drop what goes
above the top. The panel said the first instead: do not reflow it.
These tests are that vote, written down.

**The vote was then read rather than counted.** kitty is the judge
that matters here, because kitty used to do what pyte did. Its
`resize_screen_buffer_without_rewrap` (`kitty/resize.c`) runs for the
alternate buffer alone; commit 6db24b66f added it on 2025-11-26, and
its own changelog says why: "Do not rewrap the text in the alternate
screen buffer. Avoids flicker during live resize." The report behind
it, discussion 9142, is a person holding foot, kitty and Ghostty side
by side and saying kitty is the odd one out.

libvterm still reflows, and that is a setting and not an opinion:
`screen->reflow` is one flag for the whole screen, `resize_buffer`
takes it for both buffers, and `vterm_oracle.py` turns it on.
"""

from kitty_oracle import ptterm_cells
from panel import judges
from pyte.modes import PrivateMode
from pyte.sequences import set_mode

LINES = 8
WIDE = 32
NARROW = 20

#: Seven rows that each fill a 32 column screen exactly. Narrowed to 20
#: every one of them wraps, so a screen that reflows holds about
#: fifteen rows and can show eight.
FILLED = [chr(ord("A") + number) * (WIDE - 1) for number in range(7)]

ALTERNATE = set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR) + "\r\n".join(FILLED)
PRIMARY = "\r\n".join(FILLED)

#: The judges that cut the screen down rather than laying it out again.
#: libvterm is not among them, and that is a setting of ours rather
#: than its opinion: reflow is off in libvterm until an embedder calls
#: `vterm_screen_enable_reflow`, and `vterm_oracle.py` calls it for
#: every screen. So the panel here is five emulators, not six.
THE_ONES_THAT_CLIP = ("alacritty", "ghostty", "kitty", "wezterm", "xtermjs")


def text(rows):
    return ["".join(cell.char or " " for cell in row).rstrip() for row in rows]


def rows_of(data, lines, columns, resize):
    "What each judge holds after the resize, as one string a row."
    found = {"ptterm": text(ptterm_cells(data, lines, columns, resize))}
    for judge in judges():
        found[judge.name] = text(judge.cells(data, lines, columns, resize))
    return found


def a_dump(found):
    return "\n".join("%-10s %s" % (name, found[name]) for name in sorted(found))


def test_a_narrowing_cuts_the_alternate_screen_down():
    """
    Five judges to two, and ptterm is one of the five now.

    Each of the seven rows fills the screen exactly, so a reflow wraps
    every one of them and the screen keeps the bottom of what it made.
    A clip keeps the rows as they are and takes the cells that no
    longer fit.
    """
    found = rows_of(ALTERNATE, LINES, WIDE, (LINES, NARROW))
    cut_down = [letter * NARROW for letter in "ABCDEFG"] + [""]

    for name in THE_ONES_THAT_CLIP + ("ptterm",):
        assert found[name] == cut_down, "%s\n%s" % (name, a_dump(found))


def test_libvterm_is_the_one_that_reflows_and_we_asked_it_to():
    """
    Recorded so that the five above are not read as unanimous.

    libvterm reflows here because `vterm_oracle.py` turns reflow on for
    every screen it builds. Nothing in libvterm asks about the
    alternate screen: `screen->reflow` is one flag, `resize_buffer` is
    called for both buffers with it, and the library's two switches --
    `vterm_screen_enable_reflow` and `vterm_screen_enable_altscreen` --
    do not know about each other. So this is a setting of ours showing
    through, and not a judge's opinion to weigh.
    """
    found = rows_of(ALTERNATE, LINES, WIDE, (LINES, NARROW))

    assert found["libvterm"][0] == "D" * NARROW, a_dump(found)


def test_the_primary_screen_still_reflows():
    """
    The control, and the thing that must not change. Every judge
    reflows here, ptterm included, so the difference above is the
    alternate screen and not a difference in reflowing at all.
    """
    found = rows_of(PRIMARY, LINES, WIDE, (LINES, NARROW))

    # A row of 31 characters laid out at 20 leaves a tail of 11. Only a
    # reflow makes one: a clip keeps whole rows and cuts them to 20.
    # Where the tails land differs -- alacritty and xterm.js start the
    # screen one row off the others -- so the test asks that a tail is
    # there and not where it is.
    tail = (WIDE - 1) - NARROW
    for name in found:
        assert any(len(row) == tail for row in found[name]), "%s\n%s" % (
            name,
            a_dump(found),
        )


def test_a_shorter_alternate_screen_keeps_its_bottom():
    """
    Six judges to one: a screen that loses rows loses them off the top.

    ptterm needed nothing for this. `line_offset` is the last `lines`
    rows up to `max_y`, so a shorter screen already keeps its bottom.

    kitty keeps the top instead, and this test does not ask it to keep
    either end. That behaviour looks incidental rather than argued:
    `resize_screen_buffer_without_rewrap` copies rows from zero upward,
    and the commit that added it (6db24b66f) is about rewrapping and
    says nothing about which end a shorter screen keeps. Asserting it
    would make this suite fail on a kitty that fixed it.
    """
    found = rows_of(ALTERNATE, LINES, WIDE, (4, WIDE))
    the_bottom = [letter * (WIDE - 1) for letter in "DEFG"]

    for name in ("ptterm", "alacritty", "ghostty", "libvterm", "wezterm", "xtermjs"):
        assert found[name] == the_bottom, "%s\n%s" % (name, a_dump(found))

    # kitty keeps whole rows either way, which is the thing this file
    # is about. Which four of them is its own business.
    assert len(found["kitty"]) == 4, a_dump(found)
    for row in found["kitty"]:
        assert len(row) == WIDE - 1, a_dump(found)


def test_a_resize_that_changes_both_cuts_and_keeps_the_bottom():
    "What a real resize usually is: fewer rows and fewer columns."
    found = rows_of(ALTERNATE, LINES, WIDE, (4, NARROW))
    the_bottom = [letter * NARROW for letter in "DEFG"]

    for name in ("ptterm", "alacritty", "ghostty", "wezterm", "xtermjs"):
        assert found[name] == the_bottom, "%s\n%s" % (name, a_dump(found))
