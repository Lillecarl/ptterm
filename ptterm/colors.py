"""
What a colour is, how a spec of X11 becomes one, and which colour each
SGR code names.

A pane answers colour queries, so it has to read the colour that a
program names and write the colour that it holds. Neither job is about
a terminal: the syntax is `XParseColor`'s, the arithmetic is Xcms's,
and the palette is a table. `xcms.py` holds the arithmetic that this
one calls, and `osc.py` holds the sequences that carry the answers.

The second half is the translation between an SGR code and the colour
it names. "SGR 31" is the first colour of the palette and "SGR 38;5;n"
is the nth, and both are numbers here. **No spelling lives in this
file.** How a renderer writes a colour is that renderer's, and
`style.py` holds prompt_toolkit's answer.

Nothing here reads or writes a sequence.
"""
from string import hexdigits
from typing import Dict, List, NamedTuple

from .xcms import SPACES, intensity_to_value, screen_rgb

__all__ = [
    "COLOR_OF_A_BACKGROUND",
    "COLOR_OF_A_FOREGROUND",
    "Color",
    "DEFAULT_COLOR",
    "DEFAULT_COLORS",
    "PALETTE",
    "SgrColor",
    "parse_color",
    "sgr_code_of",
    "sgr_color",
    "sgr_color_parameters",
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


#: What the second parameter of "SGR 38", "48" and "58" says the rest
#: of them are.
_A_NUMBER_OF_THE_PALETTE = 5
_A_COLOUR_OF_ITS_OWN = 2

#: How many parameters each of those two forms takes, counting the "38"
#: itself.
_PALETTE_PARAMETERS = 3
_OWN_PARAMETERS = 5


class SgrColor(NamedTuple):
    """
    The colour that "SGR 38", "48" or "58" names. One of the two.

    `index` is a number of the palette. It stays a number: a program
    that asks for one asks the terminal of the user to paint it, and
    that terminal has a theme. `rgb` is a colour a program named itself,
    which no theme has an opinion about.
    """

    index: int | None = None
    rgb: Color | None = None


def sgr_color_parameters(parameters: List[int]) -> int:
    """
    How many parameters a colour of "38", "48" or "58" takes.

    Two name a colour of the palette and five name one of its own. The
    count is one more, for the "38" itself.
    """
    if len(parameters) < 2:
        return _PALETTE_PARAMETERS
    if parameters[1] == _A_NUMBER_OF_THE_PALETTE:
        return _PALETTE_PARAMETERS
    if parameters[1] == _A_COLOUR_OF_ITS_OWN:
        return _OWN_PARAMETERS
    return len(parameters)


def sgr_color(parameters: List[int]) -> SgrColor | None:
    """
    The colour that "38", "48" or "58" names, or None for nonsense.

    The parameters arrive with semicolons between them or with colons;
    both forms end up here. The form with colons may name the colour
    space first, which nobody uses, so an extra number goes away.
    """
    if len(parameters) < _PALETTE_PARAMETERS:
        return None
    kind = parameters[1]
    values = parameters[2:]

    if kind == _A_NUMBER_OF_THE_PALETTE:
        # A number outside the palette names no colour. The rendition
        # then keeps the colour it had, which is what a terminal that
        # drops a parameter it cannot read does.
        if not 0 <= values[0] < len(PALETTE):
            return None
        return SgrColor(index=values[0])

    if kind == _A_COLOUR_OF_ITS_OWN:
        if len(values) > len(Color._fields):
            values = values[1:]
        if len(values) < len(Color._fields):
            return None
        return SgrColor(rgb=Color(*values[: len(Color._fields)]))

    return None


#: The colour of the terminal itself, which "SGR 39" and "SGR 49" ask
#: for. It names no number of the palette and no colour of its own,
#: because the terminal that draws the pane decides what it is.
#:
#: It is not the same answer as no colour at all. "SGR 0" leaves a
#: rendition that names nothing; "SGR 39" leaves one that names the
#: default, and DECRQSS has to tell a reader which of the two a
#: program asked for.
DEFAULT_COLOR = SgrColor()

#: How many of the first colours of the palette have a single SGR code
#: of their own, and where the second eight start.
_CODED_COLORS = 16
_HALF = _CODED_COLORS // 2

#: The first code of each of the four runs: plain foreground, plain
#: background, bright foreground, bright background.
_FIRST_FOREGROUND = 30
_FIRST_BACKGROUND = 40
_FIRST_BRIGHT_FOREGROUND = 90
_FIRST_BRIGHT_BACKGROUND = 100

#: The code that asks for the colour of the terminal itself.
_DEFAULT_FOREGROUND = 39
_DEFAULT_BACKGROUND = 49


def _coded_colors(first: int, bright: int, default: int) -> Dict[int, SgrColor]:
    "The single SGR codes of one side, and the colour each one names."
    table = {default: DEFAULT_COLOR}
    for number in range(_HALF):
        table[first + number] = SgrColor(index=number)
        table[bright + number] = SgrColor(index=_HALF + number)
    return table


#: The colour that each of the single SGR codes names. "SGR 31" is the
#: first colour of the palette and "SGR 101" is the ninth, as a
#: background.
COLOR_OF_A_FOREGROUND = _coded_colors(
    _FIRST_FOREGROUND, _FIRST_BRIGHT_FOREGROUND, _DEFAULT_FOREGROUND
)
COLOR_OF_A_BACKGROUND = _coded_colors(
    _FIRST_BACKGROUND, _FIRST_BRIGHT_BACKGROUND, _DEFAULT_BACKGROUND
)


def sgr_code_of(index: int, background: bool = False) -> int | None:
    """
    The single SGR code that asks for this number of the palette, or
    None when the number has none.

    Only the first sixteen have one. Everything above travels as
    "38;5;n" or "48;5;n" instead.
    """
    if not 0 <= index < _CODED_COLORS:
        return None
    if index < _HALF:
        first = _FIRST_BACKGROUND if background else _FIRST_FOREGROUND
        return first + index
    first = _FIRST_BRIGHT_BACKGROUND if background else _FIRST_BRIGHT_FOREGROUND
    return first + index - _HALF
