"""
The payloads of the OSC sequences that a pane reads and answers.

A pane is not the outer terminal: it has no window, no clipboard of its
own and no palette that the user picked. What it does have is a set of
answers that keep a program from waiting forever for a reply. This
module holds the shape of each payload: which code names which colour,
how a hyperlink is written, how a pointer shape is named.

Colour queries come in two shapes. The xterm one names the colour in
the code itself ("OSC 10" is the foreground, "OSC 11" the background,
"OSC 4 ; index" a palette entry), and the kitty one names it with a key
("OSC 21 ; foreground=?"). Both are answered here.

What a colour *is* lives in `colors.py`, and the arithmetic behind it
in `xcms.py`. Nothing about a colour space belongs here.
"""
from typing import Dict, List, Tuple

from .colors import PALETTE

__all__ = [
    "DYNAMIC_COLOR_CODES",
    "DYNAMIC_COLOR_RESET_OFFSET",
    "FIRST_SPECIAL_COLOR",
    "MAX_HYPERLINK_ID_LENGTH",
    "MAX_HYPERLINK_LENGTH",
    "MAX_POINTER_SHAPES",
    "POINTER_SHAPES",
    "POINTER_SHAPE_ALIASES",
    "SPECIAL_COLOR_NAMES",
    "parse_hyperlink",
    "parse_kitty_color_query",
    "pointer_shape_name",
]

#: The codes of the dynamic colours, and the colour that each one
#: names. "OSC 10" is the first of them, and a payload with several
#: values walks up the codes from the one it was sent with.
#:
#: xterm numbers ten of these. The five that are here are the five
#: that a pane holds; the rest name a pointer or a Tektronix window,
#: which a pane does not have.
DYNAMIC_COLOR_CODES: Dict[str, str] = {
    "10": "foreground",
    "11": "background",
    "12": "cursor",
    "17": "selection_background",
    "19": "selection_foreground",
}

#: The colours that a rendition asks for by name, in the order that
#: xterm numbers them. "OSC 5 ; 0" is the first.
SPECIAL_COLOR_NAMES = ["bold", "underline", "blink", "reverse", "italic"]

#: The index that the first special colour takes in an "OSC 4"
#: payload. The special colours sit after the palette, so a program
#: reads the size of the palette first and adds it.
FIRST_SPECIAL_COLOR = len(PALETTE)

#: What separates the code that puts a dynamic colour back from the
#: code that sets it. "OSC 10" sets the foreground and "OSC 110" puts
#: it back.
DYNAMIC_COLOR_RESET_OFFSET = 100


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

#: The longest id that a hyperlink may carry. The specification of the
#: sequence gives this number.
MAX_HYPERLINK_ID_LENGTH = 250

#: The characters that an id may not hold. Three of them separate the
#: parts of the sequence, and a control character ends it early. The id
#: goes back out on the wire, so an id with one of these in it would
#: change what the sequence means there.
_UNSAFE_IN_HYPERLINK_ID = frozenset(";:=\x1b\x07")


def _hyperlink_id(params: str) -> str:
    """
    The id that the parameter field of an "OSC 8" names, or "".

    The field is "key=value : key=value", and the specification gives
    one key: "id". A pane keeps the id, because it joins the pieces of
    one link, so a link that a line break cuts in two stays one link.
    """
    for part in params.split(":"):
        key, _, value = part.partition("=")
        if key != "id":
            continue
        if not value or len(value) > MAX_HYPERLINK_ID_LENGTH:
            return ""
        if any(
            character < " "
            or character == "\x7f"
            or character in _UNSAFE_IN_HYPERLINK_ID
            for character in value
        ):
            return ""
        return value
    return ""


def parse_hyperlink(param: str) -> tuple[str, str] | None:
    """
    The id and the target of an "OSC 8", or `None` when there is none.

    The payload is "params ; target". An empty target closes the link
    that is open, and it comes back as a pair of empty strings.

    A control character would end the sequence early on the terminal of
    the user, and what follows would run as a command of its own, so a
    target that holds one is no target at all.
    """
    if ";" not in param:
        return None
    params, target = param.split(";", 1)
    if not target:
        return "", ""  # Close the link that is open.
    if len(target) > MAX_HYPERLINK_LENGTH:
        return None
    if any(character < " " or character == "\x7f" for character in target):
        return None
    return _hyperlink_id(params), target


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
