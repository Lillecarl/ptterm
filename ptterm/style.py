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

`ptterm/terminal.py` is the only thing that calls `style_of`, once per
cell of a frame, so the answer is remembered. A screen makes one
appearance per SGR sequence, and a frame draws thousands of cells
carrying a handful of them.
"""
import base64
from functools import lru_cache
from typing import TYPE_CHECKING, Dict, List

from .colors import SgrColor

if TYPE_CHECKING:
    from .screen import Appearance

__all__ = (
    "PALETTE_NAMES",
    "DEFAULT_COLOR_NAME",
    "UNDERLINE_WORDS",
    "style_of",
    "style_word",
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
#: The size holds every appearance that a screen can hand out, because
#: `appearance_of` keeps ten thousand.
style_of = lru_cache(maxsize=10 * 1000)(_spelled)
