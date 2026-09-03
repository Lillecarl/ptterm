"""
Sixel image decoding.

A program inside a pane draws a sixel image with a DCS string
sequence: ``ESC P P1;P2;P3 q <body> ST``. The body carries the pixels
in bands of six rows, one character per column per band.

The decoder turns such a body into RGBA pixels. `BetterScreen.dcs`
stores the result in the graphics state of the pane, next to the images
of the kitty graphics protocol, so that one renderer can draw both.

Not implemented: the pixel aspect ratio of the raster attributes (the
`Pan`/`Pad` pair), and the "print" and "cursor" DCS sequences that
share the introducer.
"""
import colorsys
import re
import sys
from array import array
from typing import List, Optional, Tuple

__all__ = [
    "DEFAULT_PALETTE",
    "decode_sixel",
]

# The head of a sixel sequence: "P1;P2;P3 q".
_HEADER_RE = re.compile(r"^([\d;]*)q", re.DOTALL)

# A sixel data character carries six vertical pixels.
_DATA_LOW = 0x3F  # "?"
_DATA_HIGH = 0x7E  # "~"

# Colour registers of a VT340, as percentages of red, green and blue.
# A program may select a register without defining it.
_VT340_PALETTE_PERCENT = [
    (0, 0, 0),
    (20, 20, 80),
    (80, 13, 13),
    (20, 80, 20),
    (80, 20, 80),
    (20, 80, 80),
    (80, 80, 20),
    (53, 53, 53),
    (26, 26, 26),
    (33, 33, 60),
    (60, 26, 26),
    (33, 60, 33),
    (60, 33, 60),
    (33, 60, 60),
    (60, 60, 33),
    (80, 80, 80),
]


def _percent(value: int) -> int:
    "A DEC colour component (0 to 100) as a byte."
    return min(255, max(0, round(value * 255 / 100)))


DEFAULT_PALETTE: List[Tuple[int, int, int]] = [
    (_percent(r), _percent(g), _percent(b))
    for r, g, b in _VT340_PALETTE_PERCENT
]

# Number of colour registers. (A VT340 has 256.)
MAX_REGISTERS = 256

# A runaway program must not take the machine down. Anything past
# these bounds is dropped; a bigger image than MAX_PIXELS is refused.
MAX_WIDTH = 16384
MAX_HEIGHT = 16384
MAX_PIXELS = 4 * 1024 * 1024


def _hls_to_rgb(hue: int, lightness: int, saturation: int) -> Tuple[int, int, int]:
    """
    A DEC HLS colour as RGB bytes.

    The DEC hue wheel starts at blue, not at red: it is turned by 120
    degrees against the usual one. Lightness and saturation are
    percentages.
    """
    turned = (hue + 240) % 360
    red, green, blue = colorsys.hls_to_rgb(
        turned / 360.0,
        min(100, max(0, lightness)) / 100.0,
        min(100, max(0, saturation)) / 100.0,
    )
    return (round(red * 255), round(green * 255), round(blue * 255))


def _pack(red: int, green: int, blue: int, alpha: int) -> int:
    "One RGBA pixel as a machine word, so that `array` can hold it."
    if sys.byteorder == "little":
        return red | (green << 8) | (blue << 16) | (alpha << 24)
    return alpha | (blue << 8) | (green << 16) | (red << 24)


class _Canvas:
    """
    The pixels of one image while it is decoded.

    Every pixel holds a colour register plus one, so that zero means
    "never written". Rows grow as the body writes to them.

    A band is always six pixels tall, also when the body only lights
    some of its rows. The height therefore follows the bands, not the
    lit pixels.
    """

    def __init__(self) -> None:
        self._rows: List[array] = []
        self.width = 0
        self.height = 0

    def _row(self, y: int) -> array:
        while len(self._rows) <= y:
            self._rows.append(array("H"))
        return self._rows[y]

    def write(self, band: int, x: int, count: int, bits: int, register: int) -> int:
        """
        Write one sixel data character `count` times, from column `x` of
        the band that starts at row `band`. Returns the number of
        columns that were written. (Fewer than `count` at the edge.)
        """
        count = min(count, MAX_WIDTH - x)
        if count <= 0 or band >= MAX_HEIGHT:
            return 0

        # The band exists even where no pixel is lit.
        self.width = max(self.width, x + count)
        self.height = max(self.height, min(band + 6, MAX_HEIGHT))

        value = array("H", [register + 1]) * count
        for offset in range(6):
            if bits & (1 << offset):
                y = band + offset
                if y >= MAX_HEIGHT:
                    break
                row = self._row(y)
                if len(row) < x + count:
                    row.extend([0] * (x + count - len(row)))
                row[x : x + count] = value
        return count

    def to_rgba(
        self,
        palette: List[Tuple[int, int, int]],
        width: int,
        height: int,
        background: Optional[Tuple[int, int, int]],
    ) -> bytes:
        """
        The RGBA bytes of the canvas, in a `width` x `height` box.

        `background` fills the pixels that the body never wrote. `None`
        leaves them transparent.
        """
        if background is None:
            empty = _pack(0, 0, 0, 0)
        else:
            empty = _pack(background[0], background[1], background[2], 255)

        lookup = array("I", [empty])
        lookup.extend(_pack(r, g, b, 255) for r, g, b in palette)

        out = array("I", [empty]) * (width * height)
        for y, row in enumerate(self._rows[:height]):
            count = min(len(row), width)
            if count:
                base = y * width
                out[base : base + count] = array(
                    "I", [lookup[value] for value in row[:count]]
                )
        return out.tobytes()


def decode_sixel(payload: str) -> Optional[Tuple[int, int, bytes]]:
    """
    Decode the payload of a sixel DCS sequence.

    `payload` is everything between the DCS introducer and the string
    terminator, so it starts with the "P1;P2;P3 q" head. Returns
    (width, height, RGBA bytes), or None when the payload is not a
    sixel image or holds no pixels.
    """
    header = _HEADER_RE.match(payload)
    if header is None:
        return None

    params = [int(p) for p in header.group(1).split(";") if p.isdigit()]
    # P2 == 1 leaves the pixels that the body does not write alone. Any
    # other value fills them with the background colour, for which
    # register 0 stands in.
    transparent = len(params) >= 2 and params[1] == 1

    body = payload[header.end() :]
    palette = list(DEFAULT_PALETTE) + [(0, 0, 0)] * (
        MAX_REGISTERS - len(DEFAULT_PALETTE)
    )

    canvas = _Canvas()
    register = 0
    x = 0
    band = 0
    raster_width = 0
    raster_height = 0

    index = 0
    length = len(body)

    while index < length:
        char = body[index]

        if _DATA_LOW <= ord(char) <= _DATA_HIGH:
            x += canvas.write(band, x, 1, ord(char) - _DATA_LOW, register)
            index += 1

        elif char == "!":
            index += 1
            count, index = _read_int(body, index)
            if index < length:
                data = body[index]
                index += 1
                if _DATA_LOW <= ord(data) <= _DATA_HIGH:
                    # A missing or zero count means one, like xterm.
                    x += canvas.write(
                        band, x, count or 1, ord(data) - _DATA_LOW, register
                    )

        elif char == "#":
            index += 1
            number, index = _read_int(body, index)
            if index < length and body[index] == ";":
                # A colour definition: "#Pc;Pu;Px;Py;Pz".
                values = []
                while index < length and body[index] == ";" and len(values) < 4:
                    index += 1
                    value, index = _read_int(body, index)
                    values.append(value)
                if len(values) == 4:
                    palette[number % MAX_REGISTERS] = _define_color(values)
            else:
                # A colour selection.
                register = number % MAX_REGISTERS

        elif char == "$":
            x = 0
            index += 1

        elif char == "-":
            x = 0
            band += 6
            index += 1

        elif char == '"':
            # Raster attributes: "Pan;Pad;Ph;Pv.
            index += 1
            values = []
            while len(values) < 4:
                value, index = _read_int(body, index)
                values.append(value)
                if index < length and body[index] == ";":
                    index += 1
                else:
                    break
            if len(values) == 4:
                raster_width, raster_height = values[2], values[3]

        else:
            # Whitespace and anything else that the body may carry.
            index += 1

    width = max(canvas.width, min(max(0, raster_width), MAX_WIDTH))
    height = max(canvas.height, min(max(0, raster_height), MAX_HEIGHT))

    # Bands round the height up to a multiple of six. When the raster
    # attributes name a height inside the last band, they hold the exact
    # one, so the image is cropped to it.
    if 0 < raster_height <= canvas.height and canvas.height - raster_height < 6:
        height = raster_height
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        return None

    background = None if transparent else palette[0]
    return (width, height, canvas.to_rgba(palette, width, height, background))


def _define_color(values: List[int]) -> Tuple[int, int, int]:
    "A colour from the four parameters of a `#` definition."
    system, first, second, third = values
    if system == 1:
        return _hls_to_rgb(first, second, third)
    # System 2 is RGB in percent. Anything else is treated the same
    # way: it is the only other system that DEC defines.
    return (_percent(first), _percent(second), _percent(third))


def _read_int(text: str, index: int) -> Tuple[int, int]:
    "Read digits at `index`. Returns the value and the new index."
    start = index
    while index < len(text) and text[index].isdigit():
        index += 1
    if start == index:
        return (0, index)
    return (int(text[start:index]), index)


