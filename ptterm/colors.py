"""
What a colour is, and how a spec of X11 becomes one.

A pane answers colour queries, so it has to read the colour that a
program names and write the colour that it holds. Neither job is about
a terminal: the syntax is `XParseColor`'s, the arithmetic is Xcms's,
and the palette is a table. `xcms.py` holds the arithmetic that this
one calls, and `osc.py` holds the sequences that carry the answers.

Nothing here reads or writes a sequence.
"""
from string import hexdigits
from typing import Dict, List, NamedTuple

from .xcms import SPACES, intensity_to_value, screen_rgb

__all__ = [
    "Color",
    "DEFAULT_COLORS",
    "PALETTE",
    "parse_color",
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


def _parse_intensities(spec: str) -> Color | None:
    """
    A colour in the "rgbi:" form, which names light and not values.

    Each component is how much light that channel gives, from none to
    all of it. A display does not answer a request for light in a
    straight line, so the value that gives it comes out of the tables
    of Xcms. `xcms.py` says why they are there.
    """
    parts = spec.split("/")
    if len(parts) != _COMPONENTS:
        return None
    values = []
    for channel, text in enumerate(parts):
        try:
            intensity = float(text)
        except ValueError:
            return None
        # A component names a part of the whole, so it cannot leave
        # the range. `float` also reads "nan" and "inf", and both fail
        # this test.
        if not 0.0 <= intensity <= 1.0:
            return None
        value = intensity_to_value(channel, intensity)
        values.append(value >> (_SPEC_BITS - _KEPT_BITS))
    return Color(*values)


def _parse_space(name: str, spec: str) -> Color | None:
    """
    A colour in one of the six spaces of CIE, such as "CIELab:1/1/1".

    A space describes what the eye sees and not what a display emits,
    so the three numbers go through the screen description of Xcms.
    `xcms.py` says which screen and why it is that one.
    """
    parts = spec.split("/")
    if len(parts) != _COMPONENTS:
        return None
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    if any(number != number for number in numbers):
        return None  # "nan", which `float` reads and a colour is not.
    color = screen_rgb(SPACES[name](*numbers))
    return Color(*color) if color is not None else None


def parse_color(spec: str) -> Color | None:
    """
    The colour that a spec names, or `None` for one that X11 does not
    read.

    This is the syntax of `XParseColor`, which is what a program writing
    "OSC 4" uses. The forms read here:

    - "#rgb", "#rrggbb", "#rrrgggbbb" and "#rrrrggggbbbb".
    - "rgb:r/g/b", with one to four hexadecimal digits per component.
    - "rgbi:r/g/b", with the light that each channel gives.
    - "CIEXYZ:", "CIEuvY:", "CIExyY:", "CIELab:", "CIELuv:" and
      "TekHVC:", which name a colour by what the eye sees.

    A pane keeps eight bits per component, which is what it reports.
    """
    if not spec:
        return None
    if spec.startswith("#"):
        return _parse_hash(spec[1:])
    if spec.startswith("rgb:"):
        return _parse_parts(spec[len("rgb:"):].split("/"), scale=True)
    if spec.startswith("rgbi:"):
        return _parse_intensities(spec[len("rgbi:"):])
    name, colon, rest = spec.partition(":")
    if colon and name in SPACES:
        return _parse_space(name, rest)
    return None
