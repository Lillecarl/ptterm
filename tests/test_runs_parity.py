"""
The runs build draws what the cell build drew.

`pyte.runs` coalesces a row once, and `build` maps runs instead of
cells. This holds the two against each other, cell by cell, over
styled text, blanks, gaps, the cursor row, reverse video, wide and
combining characters, and erases.

The keep mark is the one licensed difference: a blank a program
wrote keeps its column, and the mark changes no attribute, so the
runs build keeps only trailing blanks while the cell build marks
every blank. The wire is the same either way.
"""

from __future__ import annotations

import pytest

from pyte.runs import runs_of
from pyte.screen import Screen
from pyte.streams import Stream

from ptterm.style import drawn_as, fragments_of_runs

KEEP = " [KeepWhitespace]"

SEQUENCES = [
    # Styled words with interior and trailing blanks.
    "\x1b[1;31mhello \x1b[0mworld   \x1b[7mrev\x1b[27m   tail   ",
    # A second row, so a move lands on one.
    "\x1b[2;10H\x1b[32mgreen here\x1b[0m  ",
    # Wide, combining, and an erase past the cursor.
    "\x1b[3;1H\u2851 wide \u00e9\u0301tail\x1b[3;20H\x1b[K",
    # Sparse writes with gaps between them.
    "\x1b[5;5Hone\x1b[5;40Htwo\x1b[5;70H   ",
    # Trailing blanks a program wrote, spelled so no editor eats them.
    "\x1b[6;1Hleft\x20\x20\x20",
    # Reverse video over the whole screen.
    "\x1b[?5h",
]


def _screen() -> Screen:
    screen = Screen(100, 24, lambda part: None)
    stream = Stream(screen)
    stream.attach(screen)
    for sequence in SEQUENCES:
        stream.feed(sequence)
    return screen


def _old(number: int, screen: Screen, cursor_x: int, cursor_y: int, reverse: bool):
    "One row the way one cell at a time always built it."
    row = screen.page.data_buffer[number]
    most = max(row) if row else 0
    if number == cursor_y:
        most = max(most, cursor_x)
    if not row and number != cursor_y:
        return []
    return [
        drawn_as(cell.char, cell.appearance, reverse, cell.written)
        for cell in [row[column] for column in range(most + 1)]
    ]


def _new(number: int, screen: Screen, cursor_x: int, cursor_y: int, reverse: bool):
    "The same row built from runs, through the production assembly."
    row = screen.page.data_buffer[number]
    if not row and number != cursor_y:
        return []
    runs = runs_of(row)
    end = runs[-1].end if runs else 0
    if number == cursor_y:
        end = max(end, cursor_x + 1)
    return fragments_of_runs(runs, end, reverse)


def _expanded(fragments):
    "Per code point: the style of each, and all the text."
    styles = []
    for style, text in fragments:
        styles.extend([style] * len(text))
    return styles, "".join(text for _, text in fragments)


@pytest.mark.parametrize("number", [0, 1, 2, 4, 5, 10, 23])
def test_a_row_built_from_runs_draws_what_cells_drew(number: int) -> None:
    screen = _screen()
    cursor_x = screen.pt_cursor_position.x
    cursor_y = screen.pt_cursor_position.y - screen.line_offset
    reverse = screen.has_reverse_video

    old_styles, old_text = _expanded(_old(number, screen, cursor_x, cursor_y, reverse))
    new_styles, new_text = _expanded(_new(number, screen, cursor_x, cursor_y, reverse))

    assert new_text == old_text
    assert [style.replace(KEEP, "") for style in new_styles] == [
        style.replace(KEEP, "") for style in old_styles
    ]
    # The new build marks a subset of what the old one marked --
    # interior blanks lose a mark that changes no attribute -- and
    # the trailing marks, which the trim reads, agree exactly.
    assert all(not new or old for new, old in zip(new_styles, old_styles))

    def trailing_marks(styles: list[str]) -> int:
        marked = 0
        for style in reversed(styles):
            if KEEP not in style:
                break
            marked += 1
        return marked

    assert trailing_marks(new_styles) == trailing_marks(old_styles)
