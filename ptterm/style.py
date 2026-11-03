"""
How prompt_toolkit spells what a cell carries.

A screen holds an `Appearance`: the rendition that SGR set, and the
hyperlink that "OSC 8" opened. Both are a model, and neither is a
spelling. What a renderer writes for them is the renderer's own
answer, and this file is prompt_toolkit's.

A second front end has a second answer. Textual draws through Rich, so
it builds a `rich.style.Style` from the same object and reads no word
written here (Lillecarl/pymux#82). Nothing in this file is shared with
it, which is the reason it is a file of its own.

The two halves of a cell are here: `style_of` for what it looks like,
and `visible_char` for what is drawn. `ptterm/terminal.py` calls both
once per cell of a frame. A screen makes one appearance per SGR
sequence, and a frame draws thousands of cells carrying a handful
of them.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import TYPE_CHECKING

from prompt_toolkit.layout.screen import Char
from prompt_toolkit.token import KeepWhitespace
from prompt_toolkit.utils import get_cwidth
from pyte.cells import PLAIN_APPEARANCE, appearance_of
from pyte.colors import DEFAULT_COLOR, SgrColor
from pyte.extra_cursors import ColorSpace, ExtraShape
from pyte.placeholders import PLACEHOLDER, runs_in_line, spelled

if TYPE_CHECKING:
    from collections.abc import Callable

    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from pyte.cells import Appearance
    from pyte.extra_cursors import ExtraCursors
    from pyte.osc import ProgramPalette
    from pyte.runs import Run

__all__ = (
    "DEFAULT_COLOR_NAME",
    "PALETTE_NAMES",
    "UNDERLINE_WORDS",
    "drawn_as",
    "extra_cursor_style",
    "fragments_of_runs",
    "placeholder_cells",
    "run_style",
    "style_of",
    "style_word",
    "visible_char",
    "with_extra_cursors",
)

#: The names that prompt_toolkit gives the first sixteen colours of the
#: palette, in the order that "CSI 38 ; 5 ; n m" numbers them.
PALETTE_NAMES: list[str] = [
    "ansiblack",
    "ansired",
    "ansigreen",
    "ansiyellow",
    "ansiblue",
    "ansimagenta",
    "ansicyan",
    "ansigray",
    "ansibrightblack",
    "ansibrightred",
    "ansibrightgreen",
    "ansibrightyellow",
    "ansibrightblue",
    "ansibrightmagenta",
    "ansibrightcyan",
    "ansiwhite",
]

#: What prompt_toolkit calls the colour of the terminal itself.
DEFAULT_COLOR_NAME = "ansidefault"


def style_word(color: SgrColor, palette: ProgramPalette | None = None) -> str:
    """
    The word that prompt_toolkit reads for one colour.

    Every word opens with "#", which tells prompt_toolkit to take the
    colour as it stands rather than to look it up in a style sheet.

    A number of the palette stays a number here as well: it becomes
    "#ansired" or "#ansi234", and prompt_toolkit writes the SGR code
    back out, so the terminal of the user paints it from its own theme.
    A colour that a program named itself becomes "#rrggbb", because no
    theme has an opinion about that one.

    The number has to be one the palette holds. `sgr_color` is the only
    thing that makes one and it refuses the rest, so a number that is
    not there is a fault in this repository and not a program's doing.
    prompt_toolkit reads "#ansi256" as a style class it cannot find.

    `palette` holds the entries a program set, for a pane that draws
    with them (`allow-program-palette`). Lillecarl/pymux#16.
    """
    if color.rgb is not None:
        return "#%02x%02x%02x" % color.rgb
    if color.index is None:
        return "#" + DEFAULT_COLOR_NAME
    if palette is not None and color.index in palette.words:
        return palette.words[color.index]
    if color.index < len(PALETTE_NAMES):
        return "#" + PALETTE_NAMES[color.index]
    return "#ansi%d" % color.index


#: The word that prompt_toolkit reads for each shape of underline.
UNDERLINE_WORDS: dict[str, str] = {
    "": "underline",
    "double": "underdouble",
    "curly": "undercurl",
    "dotted": "underdotted",
    "dashed": "underdashed",
}


def _encoded(text: str) -> str:
    """
    One piece of a hyperlink, as it travels in a style string.

    prompt_toolkit splits a style string on whitespace, and a target or
    an id can hold anything, so both travel as base64.
    """
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _spelled(appearance: Appearance, palette: ProgramPalette | None = None) -> str:
    """
    The prompt_toolkit style string that draws one cell.

    `style_of` is this function with the answers remembered. Nothing
    calls this one directly.
    """
    rendition = appearance.rendition
    style = ""

    # "SGR 39" and "SGR 49" ask for the terminal's own colour, which is
    # what a cell with no colour draws. Spelled, it would beat the pane's
    # background: pymux paints that with its theme, and every cell after
    # an "SGR 49" showed the terminal's colour in the middle of the theme's.
    # Lillecarl/pymux#582.
    if rendition.color and rendition.color != DEFAULT_COLOR:
        style += "%s " % style_word(rendition.color, palette)
    if rendition.bgcolor and rendition.bgcolor != DEFAULT_COLOR:
        style += "bg:%s " % style_word(rendition.bgcolor, palette)
    if rendition.bold:
        style += "bold "
    if rendition.dim:
        style += "dim "
    if rendition.italic:
        style += "italic "
    if rendition.underline:
        style += UNDERLINE_WORDS[rendition.underline_style or ""] + " "
        # The colour of a line that nobody draws would travel with
        # every cell for nothing.
        if rendition.underline_color:
            style += "ul:%s " % style_word(rendition.underline_color, palette)
    if rendition.blink:
        style += "blink "
    if rendition.reverse:
        style += "reverse "
    if rendition.hidden:
        style += "hidden "
    if rendition.strike:
        style += "strike "
    if rendition.baseline:
        style += rendition.baseline + " "

    if appearance.hyperlink:
        style += "[hyperlink:%s] " % _encoded(appearance.hyperlink)
        if appearance.hyperlink_id:
            style += "[hyperlink-id:%s] " % _encoded(appearance.hyperlink_id)

    return style


#: The prompt_toolkit style string that draws one cell.
#:
#: A frame asks this once per cell, so it is the hot path of drawing,
#: and a screen holds a handful of appearances. `lru_cache` answers a
#: hit without running any bytecode at all, which a dictionary of our
#: own cannot: that one costs a Python call for every cell, and
#: `checks.ptterm-instructions` measured the difference at seven points
#: of a frame.
#:
#: The size holds every appearance that a screen can hand out, so it is
#: read off the cache that hands them out rather than written again
#: here. A key of this cache is an `Appearance`, and `pyte.cells` keeps
#: only that many of those alive. A palette is interned per pane and
#: hashes by identity, so it adds no Python call to a hit.
style_of = lru_cache(maxsize=appearance_of.size)(_spelled)


#: The characters that must not reach the terminal of the user as they
#: stand. prompt_toolkit lists them because it draws them for a person
#: who is typing; the reason here is different, and so is the answer.
#: The non-breaking space is left out: it is a character to draw, not a
#: control to keep out.
NOT_FOR_A_SCREEN = frozenset(Char.display_mappings) - {"\xa0"}


def visible_char(char: str) -> str:
    """
    What to draw for a cell.

    A unicode placeholder stands for a cell of an image, and the
    embedder draws that image itself. The character must not reach the
    screen: a terminal that does not know it paints a box, and the
    combining characters that carry the row and the column pile up on
    top of it. A space keeps the cell, and the image covers it.

    A control character is drawn as a blank. It should never be in a
    cell at all, because the parser consumes those, and one that is
    there must not reach the terminal of the user: that terminal would
    read it as a control of its own and the screen after it is anybody's
    guess. prompt_toolkit draws "^@" in blue for the same characters,
    which is a thing to look at rather than a thing to be safe.

    A non-breaking space goes through as it stands. It is a printable
    character that a program wrote on purpose, and the content of this
    control says `apply_display_mappings=False`, which is what stops
    prompt_toolkit from marking it up.
    """
    if char.startswith(PLACEHOLDER):
        return " "
    if char in NOT_FOR_A_SCREEN:
        return " "
    return char


def _run_style(appearance: Appearance, reverse_video: bool, keep: bool, palette: ProgramPalette | None) -> str:
    style = style_of(appearance) if palette is None else style_of(appearance, palette)

    if reverse_video and appearance.rendition.reverse:
        style += " noreverse"
    if keep:
        style += " " + KeepWhitespace

    return style


#: The style string for a run of one appearance.
#:
#: `keep` says a blank this styles carries `KeepWhitespace`: the
#: renderer drops a blank at the end of a row when nothing styles
#: it, so that a person who copies the output gets no trailing
#: spaces. That guess is wrong for a pane: a space a program wrote
#: is content, and a terminal that reads its own screen back has to
#: find the column.
#:
#: Answered once per way of styling rather than once per run: a
#: frame styles the same appearances row after row, so all but the
#: first sighting of one is answered in C and runs no bytecode.
run_style = lru_cache(maxsize=1024)(_run_style)


def _drawn_as(
    char: str, appearance: Appearance, reverse_video: bool, written: bool, palette: ProgramPalette | None
) -> tuple[str, str]:
    """
    The style and the character that one cell draws with.
    """
    shown = visible_char(char)

    return run_style(appearance, reverse_video, shown == " " and written, palette), shown


#: How a cell draws, answered once per way of drawing rather than once
#: per cell.
#:
#: **A frame asks this for every cell, and a screen holds a handful of
#: answers.** The arguments are what a cell is made of, and both parts
#: are interned -- `pyte.cells` hands out one `Appearance` per way of
#: drawing, and CPython caches a string's hash -- so a hit costs one
#: lookup in C and runs no bytecode at all. Without it every cell paid
#: three Python calls and two string concatenations: `fragment`,
#: `visible_char` and `style_of`, which together were a quarter of a
#: frame of moving output at 400x150. Lillecarl/pymux#434.
#:
#: The size is a whole wide screen and then some. 400x150 is sixty
#: thousand cells, so a cache this big answers every cell of one
#: without evicting an answer it is about to be asked for again.
drawn_as = lru_cache(maxsize=64 * 1024)(_drawn_as)


def _reversed(style: str, reverse_video: bool) -> bool:
    "Whether a cell of `style` draws reversed: the last word of the two wins."
    for word in reversed(style.split()):
        if word == "reverse":
            return True
        if word == "noreverse":
            return False
    return reverse_video


def extra_cursor_style(shape: ExtraShape, extra: ExtraCursors, style: str, reverse_video: bool) -> str:
    """
    What a cell under one of kitty's extra cursors adds to its style.
    Lillecarl/pymux#891.

    A cell cannot draw a beam, so a beam draws as a block. A cursor with
    no colour of its own, or the special one, reverses the cell, which
    is how the main cursor of most terminals draws.
    """
    cursor = extra.cursor_color.color if extra.cursor_color.space in _OWN_COLORS else None
    if shape == ExtraShape.UNDERLINE:
        return " underline" + ("" if cursor is None else " ul:" + style_word(cursor))
    if cursor is None:
        return " noreverse" if _reversed(style, reverse_video) else " reverse"
    text = extra.text_color.color if extra.text_color.space in _OWN_COLORS else None
    return " noreverse bg:" + style_word(cursor) + ("" if text is None else " " + style_word(text))


_OWN_COLORS = (ColorSpace.RGB, ColorSpace.INDEXED)


def with_extra_cursors(
    fragments: StyleAndTextTuples,
    cursors: dict[int, ExtraShape],
    extra: ExtraCursors,
    reverse_video: bool,
) -> StyleAndTextTuples:
    """
    A row's fragments with the cells under extra cursors cut out and
    styled. A fragment whose characters are one column each is a plain
    run; any other is one cell, such as a wide character.
    """
    result: StyleAndTextTuples = []
    column = 0
    for fragment in fragments:
        style, text = fragment[0], fragment[1]
        width = get_cwidth(text)
        if width != len(text):
            shape = cursors.get(column) if width < 2 else cursors.get(column, cursors.get(column + 1))
            if shape is None:
                result.append(fragment)
            else:
                result.append((style + extra_cursor_style(shape, extra, style, reverse_video), text))
            column += width
            continue
        start = 0
        for offset in range(len(text)):
            shape = cursors.get(column + offset)
            if shape is None:
                continue
            if offset > start:
                result.append((style, text[start:offset]))
            result.append((style + extra_cursor_style(shape, extra, style, reverse_video), text[offset]))
            start = offset + 1
        if start == 0:
            result.append(fragment)
        elif start < len(text):
            result.append((style, text[start:]))
        column += len(text)
    return result


def placeholder_cells(row, columns: int, number: int, outer_id: Callable[[int], int]) -> dict[int, tuple[str, str]]:
    """
    The image cells of one row as an outer terminal that reads unicode
    placeholders draws them: by column, the style to add and the text.

    `outer_id` gives the id that terminal knows the image by. It has to
    fit the 24 bits of a colour. Every cell names its row and column,
    because the cell that a mark was left out after may be scrolled
    away. Lillecarl/pymux#600.
    """
    cells: dict[int, tuple[str, str]] = {}
    for run in runs_in_line(row, columns, number):
        colour = " fg:#%06x" % outer_id(run.image_id)
        for offset in range(run.columns):
            text = spelled(run.image_row, run.image_column + offset)
            if text:
                cells[run.column + offset] = (colour, text)
    return cells


def fragments_of_runs(
    runs: list[Run],
    end: int,
    reverse_video: bool,
    images: Callable[[], dict[int, tuple[str, str]]] | None = None,
    palette: ProgramPalette | None = None,
) -> StyleAndTextTuples:
    """
    One row built from runs: one fragment per run.

    A run of one appearance is one piece of text in one style, and a
    gap between two runs holds cells nobody wrote, so it draws blanks.
    A blank a program wrote keeps only its trailing column, anywhere
    else the mark changes no attribute.

    `images` gives `placeholder_cells` for the row. With it, a cell of
    an image keeps its placeholder; without, it draws a space. It is
    asked only when the row holds one, which most rows do not.
    """
    # What an unwritten column draws: the blank nobody wrote.
    gap = run_style(PLAIN_APPEARANCE, reverse_video, False, palette)

    cells = None
    fragments: StyleAndTextTuples = []
    at = 0
    last = len(runs) - 1
    for index, run in enumerate(runs):
        if run.start > at:
            fragments.append((gap, " " * (run.start - at)))
        if run.plain:
            fragments.append(
                (
                    run_style(
                        run.appearance,
                        reverse_video,
                        run.blank and run.written and index == last,
                        palette,
                    ),
                    run.text,
                )
            )
        else:
            # A cell that draws as something else stands on its own
            # run, and is mapped the way one cell at a time always
            # was: a wide character, a control, a cell of an image.
            fragment = drawn_as(run.text, run.appearance, reverse_video, run.written, palette)
            if images is not None and run.text.startswith(PLACEHOLDER):
                if cells is None:
                    cells = images()
                cell = cells.get(run.start)
                if cell is not None:
                    fragment = (fragment[0] + cell[0], cell[1])
            fragments.append(fragment)
        at = run.end
    if at < end:
        fragments.append((gap, " " * (end - at)))

    return fragments
