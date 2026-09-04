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
from string import hexdigits
from typing import Dict, List, NamedTuple

__all__ = [
    "Color",
    "DEFAULT_COLORS",
    "DYNAMIC_COLOR_CODES",
    "DYNAMIC_COLOR_RESET_OFFSET",
    "FIRST_SPECIAL_COLOR",
    "MAX_HYPERLINK_LENGTH",
    "MAX_POINTER_SHAPES",
    "PALETTE",
    "POINTER_SHAPES",
    "POINTER_SHAPE_ALIASES",
    "SPECIAL_COLOR_NAMES",
    "parse_color",
    "parse_hyperlink",
    "parse_kitty_color_query",
    "pointer_shape_name",
]

#: The width of one colour component that a pane keeps, in bits.
_KEPT_BITS = 8


class Color(NamedTuple):
    """
    One colour, as the eight bits per component that a pane keeps.

    It is a tuple, so it indexes and unpacks the way a plain triple
    does. The names say which component is which, and the two
    properties write the two forms that a terminal sends.
    """

    red: int
    green: int
    blue: int

    @property
    def spec(self) -> str:
        """
        This colour in the "rgb:rrrr/gggg/bbbb" form that answers a
        colour query.

        The form carries sixteen bits per component and a pane holds
        eight, so each component is doubled. That is what a terminal
        sends, and what a program reading the answer expects.
        """
        return "rgb:%02x%02x/%02x%02x/%02x%02x" % (
            self.red, self.red,
            self.green, self.green,
            self.blue, self.blue,
        )

    @property
    def hex(self) -> str:
        "This colour as '#rrggbb', which is what a renderer reads."
        return "#%02x%02x%02x" % self


# The colours that a pane reports. pymux renders a dark background, so
# these are the honest answer for what a program will draw on.
DEFAULT_COLORS: Dict[str, Color] = {
    "foreground": Color(0xFF, 0xFF, 0xFF),
    "background": Color(0x00, 0x00, 0x00),
    "cursor": Color(0xFF, 0xFF, 0xFF),
    "cursor_text": Color(0x00, 0x00, 0x00),
    "selection_foreground": Color(0x00, 0x00, 0x00),
    "selection_background": Color(0xFF, 0xFF, 0xFF),
}

# The first sixteen entries of the palette, then the usual 6x6x6 cube
# and the grey ramp of a 256 colour terminal.
_ANSI = [
    Color(0x00, 0x00, 0x00),
    Color(0xCD, 0x00, 0x00),
    Color(0x00, 0xCD, 0x00),
    Color(0xCD, 0xCD, 0x00),
    Color(0x00, 0x00, 0xEE),
    Color(0xCD, 0x00, 0xCD),
    Color(0x00, 0xCD, 0xCD),
    Color(0xE5, 0xE5, 0xE5),
    Color(0x7F, 0x7F, 0x7F),
    Color(0xFF, 0x00, 0x00),
    Color(0x00, 0xFF, 0x00),
    Color(0xFF, 0xFF, 0x00),
    Color(0x5C, 0x5C, 0xFF),
    Color(0xFF, 0x00, 0xFF),
    Color(0x00, 0xFF, 0xFF),
    Color(0xFF, 0xFF, 0xFF),
]

#: The six levels that each component of the colour cube takes.
_CUBE = [0x00, 0x5F, 0x87, 0xAF, 0xD7, 0xFF]

#: How many steps the grey ramp has, and where it starts and steps.
#: The ramp runs from near black to near white and misses both ends,
#: because the cube already holds them.
_GREYS = 24
_GREY_FIRST = 8
_GREY_STEP = 10


def _build_palette() -> List[Color]:
    palette = list(_ANSI)
    for red in _CUBE:
        for green in _CUBE:
            for blue in _CUBE:
                palette.append(Color(red, green, blue))
    for step in range(_GREYS):
        level = _GREY_FIRST + step * _GREY_STEP
        palette.append(Color(level, level, level))
    return palette


PALETTE = _build_palette()

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


#: How many bits one hexadecimal digit carries.
_BITS_PER_DIGIT = 4

#: The width of one colour component in a spec, in bits. X11 reads a
#: spec into sixteen bits per component.
_SPEC_BITS = 16

#: The most hexadecimal digits that one component of a spec may have.
_MAX_DIGITS = _SPEC_BITS // _BITS_PER_DIGIT

#: How many components a colour has.
_COMPONENTS = len(Color._fields)


def _component(digits: str, scale: bool) -> int:
    """
    One colour component of a spec, as the bits that a pane keeps.

    X11 reads the two spec forms differently. A "#" spec pads the
    digits with zeros on the right, so "#fff" is 0xf000 and not
    0xffff. An "rgb:" spec scales the digits, so "rgb:f/f/f" is the
    full 0xffff. `scale` picks between the two.
    """
    value = int(digits, 16)
    written_bits = _BITS_PER_DIGIT * len(digits)
    if scale:
        value = value * ((1 << _SPEC_BITS) - 1) // ((1 << written_bits) - 1)
    else:
        value <<= _SPEC_BITS - written_bits
    return value >> (_SPEC_BITS - _KEPT_BITS)


def _parse_hash(spec: str) -> Color | None:
    "A colour in the '#rgb' form, with one to four digits per component."
    if len(spec) % _COMPONENTS != 0:
        return None
    width = len(spec) // _COMPONENTS
    parts = [
        spec[index * width : (index + 1) * width]
        for index in range(_COMPONENTS)
    ]
    return _parse_parts(parts, scale=False)


def _parse_parts(parts: List[str], scale: bool) -> Color | None:
    "Three components of a spec, or None when one of them is not hex."
    if len(parts) != _COMPONENTS:
        return None
    values = []
    for digits in parts:
        if not digits or len(digits) > _MAX_DIGITS:
            return None
        if any(digit not in hexdigits for digit in digits):
            return None
        values.append(_component(digits, scale))
    return Color(*values)


def parse_color(spec: str) -> Color | None:
    """
    The colour that a spec names, or `None` for one that X11 does not
    read.

    This is the syntax of `XParseColor`, which is what a program writing
    "OSC 4" uses. Two forms are read here:

    - "#rgb", "#rrggbb", "#rrrgggbbb" and "#rrrrggggbbbb".
    - "rgb:r/g/b", with one to four hexadecimal digits per component.

    A pane keeps eight bits per component, which is what it reports.
    """
    if not spec:
        return None
    if spec.startswith("#"):
        return _parse_hash(spec[1:])
    if spec.startswith("rgb:"):
        return _parse_parts(spec[4:].split("/"), scale=True)
    return None


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
