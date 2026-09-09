"""
What a scroll does to the wrap mark of the row it moves to the top.

Lillecarl/pymux#188. A scroll drops the rows that leave the region, so
the row that lands at the top continues a row that is gone. What is
above it is either a line the program wrote separately, outside the
region, or the history.

**The mark cannot be seen from outside a terminal except through a
resize**, which is why this asks the panel rather than reading cells.
Feed the bytes, widen the screen, and read whether the surviving rows
joined the line above them.

## The vote, and how it was read

    alacritty  ['ZZZZ', 'aaaaaaaaaaaaaaaa', '', '']
    kitty      ['ZZZZ', 'aaaaaaaaaaaaaaaa', '', '']
    wezterm    ['ZZZZ', 'aaaaaaaaaaaaaaaa', '', '']
    ghostty    ['ZZZZ', 'aaaaaaaa', 'aaaaaaaa', '']
    libvterm   ['ZZZZ    aaaaaaaa', 'aaaaaaaa', '', '']
    xtermjs    ['ZZZZ    aaaaaaaa', 'aaaaaaaa', '', '']

Three to two, with one abstention, and the reason weighs more than the
count. **The two that join make a line the program never wrote.**
"ZZZZ" and the "a"s were written as two lines, and the only thing that
says otherwise is a mark whose antecedent the scroll threw away.

ptterm used to be with libvterm, and worse: our reflow takes the
blanks off the end of a line first, so the two lines came out glued as
`ZZZZaaaaaaaaaaaa` rather than merely run together.

xterm is not in this panel and answers it the other way: `ScrnDeleteLine`
moves the `LineData` pointers and clears no mark. That costs xterm
nothing, because xterm never lays a screen out again. It is a reading
that only holds for a terminal without reflow.

Ghostty draws neither answer here, because it does not lay these rows
out again at all. It says nothing about the mark, so it does not vote.
"""

from kitty_oracle import ptterm_cells
from panel import judges

LINES = 4
NARROW = 8
WIDE = 16

#: A line of its own on the first row, then one wrapped line filling
#: the three rows under it, then a scroll of those three alone.
#:
#: **The scrolling region is what makes this decisive.** Without one
#: the row that lands on top has nothing above it, and a reader cannot
#: tell a kept mark from a cleared one. With it, the row above is a
#: line the program wrote separately, so a kept mark joins "ZZZZ" to
#: the "a"s and a cleared one leaves them apart.
A_SCROLL = (
    "\x1b[2;4r"  # the region is the last three rows
    + "\x1b[1;1HZZZZ"  # a line of its own, outside the region
    + "\x1b[2;1H"
    + "a" * 24  # three full rows, the last two wrapped
    + "\x1b[S"  # scroll the region up: the top row's line is dropped
)

#: The judges that keep the two lines apart, which is what ptterm does
#: now. Ghostty is not among them because it lays nothing out again
#: here, so it is not a vote either way.
THE_ONES_THAT_KEEP_THEM_APART = ("alacritty", "kitty", "wezterm")

#: And the two that join them, recorded so that the three above are not
#: read as unanimous.
THE_ONES_THAT_JOIN_THEM = ("libvterm", "xtermjs")


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


def test_the_row_that_lands_on_top_starts_a_line_of_its_own():
    """
    ptterm with the three, and this is the behaviour under test.

    The scroll left two rows of "a" and threw away the row they
    continued. Laid out at sixteen columns they make one row, and
    "ZZZZ" above them is untouched.
    """
    found = rows_of(A_SCROLL, LINES, NARROW, (LINES, WIDE))
    apart = ["ZZZZ", "a" * 16, "", ""]

    for name in THE_ONES_THAT_KEEP_THEM_APART + ("ptterm",):
        assert found[name] == apart, "%s\n%s" % (name, a_dump(found))


def test_libvterm_and_xtermjs_join_the_two_lines():
    """
    Recorded so that the three above are not read as unanimous.

    Both keep the mark the scroll left, so the row above becomes the
    start of the line that the "a"s continue, and the two lay out as
    one. The blanks that pad "ZZZZ" out to eight columns come with it,
    which is what "ZZZZ    aaaaaaaa" is.
    """
    found = rows_of(A_SCROLL, LINES, NARROW, (LINES, WIDE))

    for name in THE_ONES_THAT_JOIN_THEM:
        assert found[name][0] == "ZZZZ    " + "a" * 8, "%s\n%s" % (
            name,
            a_dump(found),
        )


def test_a_wrapped_line_that_survives_whole_is_still_one_line():
    """
    The control, and the thing that must not change.

    Clearing the mark of the row at the top of the region must not
    clear the marks of the rows under it: they continue rows that are
    still there. Here nothing scrolls, so all three rows are one line
    and every judge that lays them out again says so.
    """
    written = "\x1b[1;1HZZZZ" + "\x1b[2;1H" + "a" * 24
    found = rows_of(written, LINES, NARROW, (LINES, WIDE))

    for name in THE_ONES_THAT_KEEP_THEM_APART + ("ptterm",):
        assert found[name][:2] == ["ZZZZ", "a" * 16], "%s\n%s" % (
            name,
            a_dump(found),
        )
