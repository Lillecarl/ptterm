"""
OSC sequences that a pane may send.

A pane is not the outer terminal: it has no window, no clipboard of its
own and no palette that the user picked. What it does have is a set of
answers that keep a program from waiting forever for a reply. This
module holds the colour answers and the small parser that reads a
colour query.

Colour queries come in two shapes. The xterm one names the colour in
the code itself ("OSC 10" is the foreground, "OSC 11" the background,
"OSC 4 ; index" a palette entry), and the kitty one names it with a key
("OSC 21 ; foreground=?"). Both are answered here.
"""
from typing import Dict, List, Optional, Tuple

__all__ = [
    "DEFAULT_COLORS",
    "PALETTE",
    "format_color",
    "parse_kitty_color_query",
]

# The colours that a pane reports. pymux renders a dark background, so
# these are the honest answer for what a program will draw on.
DEFAULT_COLORS: Dict[str, Tuple[int, int, int]] = {
    "foreground": (0xFF, 0xFF, 0xFF),
    "background": (0x00, 0x00, 0x00),
    "cursor": (0xFF, 0xFF, 0xFF),
    "cursor_text": (0x00, 0x00, 0x00),
    "selection_foreground": (0x00, 0x00, 0x00),
    "selection_background": (0xFF, 0xFF, 0xFF),
}

# The first sixteen entries of the palette, then the usual 6x6x6 cube
# and the grey ramp of a 256 colour terminal.
_ANSI = [
    (0x00, 0x00, 0x00),
    (0xCD, 0x00, 0x00),
    (0x00, 0xCD, 0x00),
    (0xCD, 0xCD, 0x00),
    (0x00, 0x00, 0xEE),
    (0xCD, 0x00, 0xCD),
    (0x00, 0xCD, 0xCD),
    (0xE5, 0xE5, 0xE5),
    (0x7F, 0x7F, 0x7F),
    (0xFF, 0x00, 0x00),
    (0x00, 0xFF, 0x00),
    (0xFF, 0xFF, 0x00),
    (0x5C, 0x5C, 0xFF),
    (0xFF, 0x00, 0xFF),
    (0x00, 0xFF, 0xFF),
    (0xFF, 0xFF, 0xFF),
]

_CUBE = [0x00, 0x5F, 0x87, 0xAF, 0xD7, 0xFF]


def _build_palette() -> List[Tuple[int, int, int]]:
    palette = list(_ANSI)
    for red in _CUBE:
        for green in _CUBE:
            for blue in _CUBE:
                palette.append((red, green, blue))
    for step in range(24):
        level = 8 + step * 10
        palette.append((level, level, level))
    return palette


PALETTE = _build_palette()


def format_color(color: Tuple[int, int, int]) -> str:
    """
    A colour in the "rgb:rrrr/gggg/bbbb" form that xterm answers with.
    Every component is doubled, which is what terminals send.
    """
    return "rgb:%02x%02x/%02x%02x/%02x%02x" % (
        color[0],
        color[0],
        color[1],
        color[1],
        color[2],
        color[2],
    )


def parse_kitty_color_query(param: str) -> Optional[List[Tuple[str, bool]]]:
    """
    Split the payload of an "OSC 21" sequence into its keys.

    Returns one (key, is_query) pair per part, or None when the payload
    holds nothing to answer. A part with a "?" value is a query; every
    other part sets a colour, which a pane cannot do.
    """
    parts = [part for part in param.split(";") if part != ""]
    if not parts:
        return None

    result = []
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            result.append((key, value == "?"))
        else:
            result.append((part, False))
    return result
