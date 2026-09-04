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
from typing import Dict, List, Tuple

__all__ = [
    "DEFAULT_COLORS",
    "MAX_HYPERLINK_LENGTH",
    "MAX_POINTER_SHAPES",
    "PALETTE",
    "POINTER_SHAPES",
    "POINTER_SHAPE_ALIASES",
    "format_color",
    "parse_hyperlink",
    "parse_kitty_color_query",
    "pointer_shape_name",
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


def parse_kitty_color_query(param: str) -> List[Tuple[str, bool]] | None:
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


#: The longest hyperlink target that a pane may open. A URL longer than
#: this is not a link that anybody follows; it is a way to fill memory.
MAX_HYPERLINK_LENGTH = 2083


def parse_hyperlink(param: str) -> str | None:
    """
    The target that an "OSC 8" names, or `None` when there is none.

    The payload is "params ; target". The parameters carry an "id" that
    joins the pieces of one link across lines; nothing here needs it, so
    they are read and dropped. An empty target closes the link that is
    open.

    A control character would end the sequence early on the terminal of
    the user, and what follows would run as a command of its own, so a
    target that holds one is no target at all.
    """
    if ";" not in param:
        return None
    _params, target = param.split(";", 1)
    if not target:
        return ""  # Close the link that is open.
    if len(target) > MAX_HYPERLINK_LENGTH:
        return None
    if any(character < " " or character == "\x7f" for character in target):
        return None
    return target


#: The stack of pointer shapes that a terminal keeps. kitty asks for a
#: minimum of sixteen, and uses sixteen itself.
MAX_POINTER_SHAPES = 16

#: The shapes that a terminal must know, named after the cursor
#: property of CSS.
POINTER_SHAPES = frozenset([
    "alias", "cell", "copy", "crosshair", "default", "e-resize",
    "ew-resize", "grab", "grabbing", "help", "move", "n-resize",
    "ne-resize", "nesw-resize", "no-drop", "not-allowed", "ns-resize",
    "nw-resize", "nwse-resize", "pointer", "progress", "s-resize",
    "se-resize", "sw-resize", "text", "vertical-text", "w-resize", "wait",
    "zoom-in", "zoom-out",
])

#: The names that xterm used, which kitty takes as well. A set takes
#: them; kitty leaves "arrow" and "beam" out of the set that its own
#: "OSC 22" reads, so those are not here either.
POINTER_SHAPE_ALIASES = {
    "bottom_left_corner": "sw-resize",
    "bottom_right_corner": "se-resize",
    "bottom_side": "s-resize",
    "clock": "wait",
    "closedhand": "grabbing",
    "cross": "cell",
    "crossed_circle": "not-allowed",
    "dnd-copy": "copy",
    "dnd-link": "alias",
    "dnd-no-drop": "no-drop",
    "dnd-none": "grabbing",
    "fleur": "move",
    "forbidden": "not-allowed",
    "half-busy": "progress",
    "hand": "pointer",
    "hand1": "grab",
    "hand2": "pointer",
    "ibeam": "text",
    "left_ptr": "default",
    "left_ptr_watch": "progress",
    "left_side": "w-resize",
    "openhand": "grab",
    "plus": "cell",
    "pointer-move": "move",
    "pointing_hand": "pointer",
    "question_arrow": "help",
    "right_side": "e-resize",
    "sb_h_double_arrow": "ew-resize",
    "sb_v_double_arrow": "ns-resize",
    "size-bdiag": "nesw-resize",
    "size-fdiag": "nwse-resize",
    "size_bdiag": "nesw-resize",
    "size_fdiag": "nwse-resize",
    "split_h": "ew-resize",
    "split_v": "ns-resize",
    "tcross": "crosshair",
    "top_left_corner": "nw-resize",
    "top_right_corner": "ne-resize",
    "top_side": "n-resize",
    "watch": "wait",
    "whats_this": "help",
    "xterm": "text",
    "zoom_in": "zoom-in",
    "zoom_out": "zoom-out",
}


def pointer_shape_name(name: str) -> str | None:
    """
    The shape that a name stands for, or `None` for a name that no
    terminal knows.

    An empty name is the shape of nobody: it takes the shape away.
    """
    if not name:
        return ""
    if name in POINTER_SHAPES:
        return name
    return POINTER_SHAPE_ALIASES.get(name)
