"""
A drawing of a screen, for something else to show.

A preview is read-only and belongs to no process. It takes a `pyte`
screen and gives back rows that a prompt_toolkit control can draw, so
that a chooser can show what is in a pane without putting that pane's
widget in the layout twice. Lillecarl/pymux#325.

**It is not the widget with the process taken out.** `Terminal` draws
the pane a person works in: it sizes the pty from the room it is given,
it keeps a built row per version so that a frame after one write builds
one line, and it answers the mouse. None of that belongs to a picture
of somebody else's pane, and two of the three would be wrong -- a
preview must never resize the program it is a picture of.
"""

from typing import List

from prompt_toolkit.formatted_text import StyleAndTextTuples

from .style import style_of, visible_char

__all__ = ["preview_lines", "preview_text"]


def preview_lines(screen, rows: int, columns: int) -> List[StyleAndTextTuples]:
    """
    A window of the screen, `rows` high and `columns` wide.

    **Around the cursor, and not the top left.** A program writes where
    the cursor is, so a preview that starts at the top of an eighty
    column screen shows the beginning of a build log while the build is
    at the end of it. tmux picks the same region -- a third of the way
    in from the cursor, clamped to the screen -- in
    `screen_write_preview`, `screen-write.c`.

    A screen that shows no cursor has nothing to aim at, so it starts
    at the top left.

    Fewer rows come back than asked for when the screen has fewer.
    """
    if rows <= 0 or columns <= 0:
        return []

    page = screen.page
    data_buffer = page.data_buffer

    # A row number is a row of the buffer, and the buffer holds the
    # history above the screen. The screen is `lines` rows from here.
    top = screen.line_offset
    left = 0

    if page.show_cursor:
        cursor = screen.pt_cursor_position
        left = max(0, cursor.x - columns // 3)
        left = min(left, max(0, screen.columns - columns))
        top = max(screen.line_offset, cursor.y - rows // 3)
        top = min(top, max(screen.line_offset, screen.line_offset + screen.lines - rows))

    last = min(screen.line_offset + screen.lines - 1, screen.highest_row())

    lines: List[StyleAndTextTuples] = []
    for number in range(top, min(top + rows, last + 1)):
        row = data_buffer.get(number)
        if not row:
            lines.append([])
            continue

        end = min(max(row), left + columns - 1)
        lines.append(
            [
                (style_of(row[x].appearance), visible_char(row[x].char))
                for x in range(left, end + 1)
            ]
        )

    return lines


def preview_text(screen, rows: int, columns: int) -> StyleAndTextTuples:
    "The same rows, as one run of formatted text with newlines between."
    fragments: StyleAndTextTuples = []
    for number, line in enumerate(preview_lines(screen, rows, columns)):
        if number:
            fragments.append(("", "\n"))
        fragments += line
    return fragments
