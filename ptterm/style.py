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
once per cell of a frame, and `ptterm/preview.py` calls them for a
drawing of a pane that a person is not working in, so the style answer
is remembered. A screen makes one appearance per SGR sequence, and a
frame draws thousands of cells carrying a handful of them.
"""

import base64
from functools import lru_cache
from typing import TYPE_CHECKING, Dict, List

from prompt_toolkit.layout.screen import Char

from pyte.cells import appearance_of
from pyte.colors import SgrColor
from pyte.placeholders import PLACEHOLDER

if TYPE_CHECKING:
    from pyte.cells import Appearance

__all__ = (
    "PALETTE_NAMES",
    "DEFAULT_COLOR_NAME",
    "UNDERLINE_WORDS",
    "style_of",
    "style_word",
    "visible_char",
)

#: The names that prompt_toolkit gives the first sixteen colours of the
#: palette, in the order that "CSI 38 ; 5 ; n m" numbers them.
PALETTE_NAMES: List[str] = [
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


def style_word(color: SgrColor) -> str:
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
    """
    if color.rgb is not None:
        return "#%02x%02x%02x" % color.rgb
    if color.index is None:
        return "#" + DEFAULT_COLOR_NAME
    if color.index < len(PALETTE_NAMES):
        return "#" + PALETTE_NAMES[color.index]
    return "#ansi%d" % color.index


#: The word that prompt_toolkit reads for each shape of underline.
UNDERLINE_WORDS: Dict[str, str] = {
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


def _spelled(appearance: "Appearance") -> str:
    """
    The prompt_toolkit style string that draws one cell.

    `style_of` is this function with the answers remembered. Nothing
    calls this one directly.
    """
    rendition = appearance.rendition
    style = ""

    if rendition.color:
        style += "%s " % style_word(rendition.color)
    if rendition.bgcolor:
        style += "bg:%s " % style_word(rendition.bgcolor)
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
            style += "ul:%s " % style_word(rendition.underline_color)
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
#: only that many of those alive.
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
