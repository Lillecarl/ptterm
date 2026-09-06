"""
How prompt_toolkit spells a colour.

A screen holds a colour as a number: a place in the palette, or three
components a program named itself. `colors.py` says why. What a
renderer writes for that number is the renderer's own answer, and this
file is prompt_toolkit's.

A second front end has a second answer. Textual draws through Rich, so
its cell carries a `rich.style.Style` and not a word at all
(Lillecarl/pymux#82). Nothing here is shared with it, which is the
reason this is a file of its own.
"""
from typing import List

from .colors import SgrColor

__all__ = ("PALETTE_NAMES", "DEFAULT_COLOR_NAME", "style_word")

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
