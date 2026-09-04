"""
The part of X11 colour management that a colour spec needs.

xterm reads a colour spec with `XParseColor`, and `XParseColor` hands
the forms it does not know itself to Xcms, the colour management of
Xlib. A program that writes "rgbi:0.5/0.5/0.5" and reads the answer
back is really reading Xcms, so a pane that wants to answer the way
xterm does has to do what Xcms does.

Xcms is not a textbook conversion, and a colour library will not give
the same answer. It reads a monitor description that says what each
device value really emits, and it holds a built-in description for a
display that carries none. That description is three tables, one per
channel, and they do not agree with each other: a grey intensity comes
back as a colour that is not grey.

    rgbi:0.5/0.5/0.5   ->   c1c1/bbbb/bbbb

Red comes back 0xc1 where green and blue come back 0xbb. One curve
cannot do that, and this is why the tables are here rather than a
formula.

The source is libX11, `src/xcms/LRGB.c`. The tables are
`Default_RGB_RedTuples`, `Default_RGB_GreenTuples` and
`Default_RGB_BlueTuples`; the search is `_XcmsTableSearch` with
`_XcmsIntensityCmp` and `_XcmsIntensityInterpolation`.
"""
import math
from typing import List, Tuple

__all__ = [
    "BITS_PER_RGB",
    "SPACES",
    "intensity_to_value",
    "screen_rgb",
]

#: How many bits of each component a display really tells apart. Xcms
#: reads this from the visual, and every display that a terminal runs
#: on today carries eight.
BITS_PER_RGB = 8

#: The width of one colour component as Xcms carries it, in bits.
_SPEC_BITS = 16

#: The bits of a value that survive at a given `BITS_PER_RGB`. Xcms
#: drops the rest, because a display cannot show them. This is `MASK`
#: of `src/xcms/LRGB.c`, written as the sum it really is.
_MASK = [
    ((1 << bits) - 1) << (_SPEC_BITS - bits) & 0xFFFF
    for bits in range(_SPEC_BITS + 1)
]

#: One entry of a channel table: the value that a display takes, and
#: the light that it gives for it.
Entry = Tuple[int, float]

#: What the red channel of the built-in display gives. The first two
#: entries both give nothing: a display that is told to emit a little
#: emits none at all.
_RED: List[Entry] = [
    (0x0000, 0.000000), (0x0909, 0.000000), (0x0A0A, 0.000936),
    (0x0F0F, 0.001481), (0x1414, 0.002329), (0x1919, 0.003529),
    (0x1E1E, 0.005127), (0x2323, 0.007169), (0x2828, 0.009699),
    (0x2D2D, 0.012759), (0x3232, 0.016392), (0x3737, 0.020637),
    (0x3C3C, 0.025533), (0x4141, 0.031119), (0x4646, 0.037431),
    (0x4B4B, 0.044504), (0x5050, 0.052373), (0x5555, 0.061069),
    (0x5A5A, 0.070624), (0x5F5F, 0.081070), (0x6464, 0.092433),
    (0x6969, 0.104744), (0x6E6E, 0.118026), (0x7373, 0.132307),
    (0x7878, 0.147610), (0x7D7D, 0.163958), (0x8282, 0.181371),
    (0x8787, 0.199871), (0x8C8C, 0.219475), (0x9191, 0.240202),
    (0x9696, 0.262069), (0x9B9B, 0.285089), (0xA0A0, 0.309278),
    (0xA5A5, 0.334647), (0xAAAA, 0.361208), (0xAFAF, 0.388971),
    (0xB4B4, 0.417945), (0xB9B9, 0.448138), (0xBEBE, 0.479555),
    (0xC3C3, 0.512202), (0xC8C8, 0.546082), (0xCDCD, 0.581199),
    (0xD2D2, 0.617552), (0xD7D7, 0.655144), (0xDCDC, 0.693971),
    (0xE1E1, 0.734031), (0xE6E6, 0.775322), (0xEBEB, 0.817837),
    (0xF0F0, 0.861571), (0xF5F5, 0.906515), (0xFAFA, 0.952662),
    (0xFFFF, 1.000000),
]

#: What the green channel gives.
_GREEN: List[Entry] = [
    (0x0000, 0.000000), (0x1313, 0.000000), (0x1414, 0.000832),
    (0x1919, 0.001998), (0x1E1E, 0.003612), (0x2323, 0.005736),
    (0x2828, 0.008428), (0x2D2D, 0.011745), (0x3232, 0.015740),
    (0x3737, 0.020463), (0x3C3C, 0.025960), (0x4141, 0.032275),
    (0x4646, 0.039449), (0x4B4B, 0.047519), (0x5050, 0.056520),
    (0x5555, 0.066484), (0x5A5A, 0.077439), (0x5F5F, 0.089409),
    (0x6464, 0.102418), (0x6969, 0.116485), (0x6E6E, 0.131625),
    (0x7373, 0.147853), (0x7878, 0.165176), (0x7D7D, 0.183604),
    (0x8282, 0.203140), (0x8787, 0.223783), (0x8C8C, 0.245533),
    (0x9191, 0.268384), (0x9696, 0.292327), (0x9B9B, 0.317351),
    (0xA0A0, 0.343441), (0xA5A5, 0.370580), (0xAAAA, 0.398747),
    (0xAFAF, 0.427919), (0xB4B4, 0.458068), (0xB9B9, 0.489165),
    (0xBEBE, 0.521176), (0xC3C3, 0.554067), (0xC8C8, 0.587797),
    (0xCDCD, 0.622324), (0xD2D2, 0.657604), (0xD7D7, 0.693588),
    (0xDCDC, 0.730225), (0xE1E1, 0.767459), (0xE6E6, 0.805235),
    (0xEBEB, 0.843491), (0xF0F0, 0.882164), (0xF5F5, 0.921187),
    (0xFAFA, 0.960490), (0xFFFF, 1.000000),
]

#: What the blue channel gives.
_BLUE: List[Entry] = [
    (0x0000, 0.000000), (0x0E0E, 0.000000), (0x0F0F, 0.001341),
    (0x1414, 0.002080), (0x1919, 0.003188), (0x1E1E, 0.004729),
    (0x2323, 0.006766), (0x2828, 0.009357), (0x2D2D, 0.012559),
    (0x3232, 0.016424), (0x3737, 0.021004), (0x3C3C, 0.026344),
    (0x4141, 0.032489), (0x4646, 0.039481), (0x4B4B, 0.047357),
    (0x5050, 0.056154), (0x5555, 0.065903), (0x5A5A, 0.076634),
    (0x5F5F, 0.088373), (0x6464, 0.101145), (0x6969, 0.114968),
    (0x6E6E, 0.129862), (0x7373, 0.145841), (0x7878, 0.162915),
    (0x7D7D, 0.181095), (0x8282, 0.200386), (0x8787, 0.220791),
    (0x8C8C, 0.242309), (0x9191, 0.264937), (0x9696, 0.288670),
    (0x9B9B, 0.313499), (0xA0A0, 0.339410), (0xA5A5, 0.366390),
    (0xAAAA, 0.394421), (0xAFAF, 0.423481), (0xB4B4, 0.453547),
    (0xB9B9, 0.484592), (0xBEBE, 0.516587), (0xC3C3, 0.549498),
    (0xC8C8, 0.583291), (0xCDCD, 0.617925), (0xD2D2, 0.653361),
    (0xD7D7, 0.689553), (0xDCDC, 0.726454), (0xE1E1, 0.764013),
    (0xE6E6, 0.802178), (0xEBEB, 0.840891), (0xF0F0, 0.880093),
    (0xF5F5, 0.919723), (0xFAFA, 0.959715), (0xFFFF, 1.000000),
]

#: The three channels, in the order that a colour holds them.
_TABLES = (_RED, _GREEN, _BLUE)


def _interpolate(
    low: Entry, high: Entry, intensity: float, bits: int
) -> int:
    """
    The value between two entries that gives the wanted light.

    A straight line between the two entries says where it falls. The
    answer then moves to the nearest value that the display really
    tells apart, which is why this needs `bits`.

    This is `_XcmsIntensityInterpolation` of `src/xcms/LRGB.c`.
    """
    shift = _SPEC_BITS - bits
    largest = (1 << bits) - 1
    ratio = (intensity - low[1]) / (high[1] - low[1])
    target = int((high[0] - low[0]) * ratio) + low[0]

    # The two values that the display tells apart, one on each side.
    above = ((target >> shift) * 0xFFFF) // largest
    if above < target:
        below = above
        above = (min((below >> shift) + 1, largest) * 0xFFFF) // largest
    else:
        below = (max((above >> shift) - 1, 0) * 0xFFFF) // largest

    nearest = above if (above - target) < (target - below) else below
    return nearest & _MASK[bits]


def intensity_to_value(
    channel: int, intensity: float, bits: int = BITS_PER_RGB
) -> int:
    """
    The value that makes one channel of a display give `intensity`.

    `channel` is 0 for red, 1 for green and 2 for blue. The answer
    carries sixteen bits, of which `bits` are real.

    This is `_XcmsTableSearch` of `src/xcms/LRGB.c`, walking the table
    of the channel. Xcms searches it and interpolates between the two
    entries it lands between.
    """
    table = _TABLES[channel]

    # No light always means no value. Xcms says so in as many words,
    # because the first entries of a table give no light for a value
    # that is not zero, and a search would find one of those.
    if intensity <= table[0][1]:
        return table[0][0] & _MASK[bits]

    low, high = 0, len(table) - 1
    last, middle = high, low
    while middle != last:
        last = middle
        middle = low + (high - low) // 2
        if intensity == table[middle][1]:
            return table[middle][0] & _MASK[bits]
        if intensity < table[middle][1]:
            high = middle
        else:
            low = middle

    return _interpolate(table[low], table[high], intensity, bits)


# ----------------------------------------------------------------------
# The colour spaces of CIE, and the screen that Xcms converts them for.
#
# `XParseColor` reads six names that are not device values at all. They
# describe a colour by what the eye sees, so turning one into something
# a display can show needs to know what that display emits. Xcms holds
# the two matrices below for the display it assumes, and the tables
# above for its channels.
#
# The conversions come from libX11: `src/xcms/LRGB.c` for the matrices,
# and `Lab.c`, `Luv.c`, `uvY.c`, `xyY.c` and `HVC.c` for the spaces.
# They are ported as written and not from the textbook, because the
# answer has to be the one xterm gives. Where the two differ, the
# comment says so.


#: The matrix that turns CIEXYZ into the light each channel gives.
#: `XYZtoRGBmatrix` of `Default_RGB_SCCData`.
_XYZ_TO_RGB = (
    (3.48340481253539000, -1.52176374927285200, -0.55923133354049780),
    (-1.07152751306193600, 1.96593795204372400, 0.03673691339553462),
    (0.06351179790497788, -0.20020501000496480, 0.81070942031648220),
)

#: The matrix the other way. `RGBtoXYZmatrix` of the same.
_RGB_TO_XYZ = (
    (0.38106149108714790, 0.32025712365352110, 0.24834578525933100),
    (0.20729745115140850, 0.68054638776373240, 0.11215616108485920),
    (0.02133944350088028, 0.14297193020246480, 1.24172892629665500),
)

#: How far a value may leave the range before Xcms calls the colour
#: unshowable. `EPS` of `src/xcms/LRGB.c`.
_GAMUT_SLOP = 0.001

#: Below this the CIE lightness formula turns into a straight line.
#: `903.29` is the slope, and this is where the two meet.
_LOW_LIGHTNESS = 7.99953624

#: The lightness that the cube root formula gives at that point.
_LOW_Y = 0.008856

#: The colour that TekHVC measures its hue from: "best red".
#: `u_BR` and `v_BR` of `src/xcms/HVC.c`.
_BEST_RED = (0.7127, 0.4931)

#: What TekHVC divides its chroma by. `CHROMA_SCALE_FACTOR`.
_CHROMA_SCALE = 7.50725

#: A full turn, in degrees.
_TURN = 360.0


def _matvec(matrix, vector) -> Tuple[float, float, float]:
    "One 3x3 matrix times one vector. `_XcmsMatVec`."
    return tuple(  # type: ignore[return-value]
        sum(matrix[row][column] * vector[column] for column in range(3))
        for row in range(3)
    )


def _uvy_to_xyz(u_prime: float, v_prime: float, cap_y: float):
    "`XcmsCIEuvYToCIEXYZ`."
    divisor = 6.0 * u_prime - 16.0 * v_prime + 12.0
    if divisor == 0.0:
        return (0.0, cap_y, 0.0)
    x = 9.0 * u_prime / divisor
    y = 4.0 * v_prime / divisor
    z = 1.0 - x - y
    if y == 0.0:
        return (x, cap_y, z)
    return (x * cap_y / y, cap_y, z * cap_y / y)


def _xyz_to_uvy(xyz):
    "`XcmsCIEXYZToCIEuvY`."
    cap_x, cap_y, cap_z = xyz
    divisor = cap_x + 15.0 * cap_y + 3.0 * cap_z
    if divisor == 0.0:
        return (0.0, 0.0, cap_y)
    return (4.0 * cap_x / divisor, 9.0 * cap_y / divisor, cap_y)


#: The white of the assumed screen: what a full signal on every channel
#: gives. The CIE spaces measure a colour against it.
_WHITE = _matvec(_RGB_TO_XYZ, (1.0, 1.0, 1.0))
_WHITE_UVY = _xyz_to_uvy(_WHITE)

#: Where TekHVC starts counting hue, given that white. `ThetaOffset`.
_THETA_OFFSET = math.degrees(math.atan(
    (_BEST_RED[1] - _WHITE_UVY[1]) / (_BEST_RED[0] - _WHITE_UVY[0])
))


def _lightness_to_y(lightness: float) -> float:
    "The CIE lightness formula, as `Luv.c` and `HVC.c` write it."
    if lightness < _LOW_LIGHTNESS:
        return lightness / 903.29
    root = (lightness + 16.0) / 116.0
    return root * root * root


def _xyz(x: float, y: float, z: float):
    "CIEXYZ, which needs no conversion at all."
    return (x, y, z)


def _xyy(x: float, y: float, cap_y: float):
    "`XcmsCIExyYToCIEXYZ`."
    if y == 0.0:
        return (x, cap_y, 1.0 - x - y)
    return (x * cap_y / y, cap_y, (1.0 - x - y) * cap_y / y)


def _lab(lightness: float, a_star: float, b_star: float):
    """
    `XcmsCIELabToCIEXYZ`.

    The low branch divides the lightness by 9.03292. The CIE formula
    says 903.292, so libX11 is a hundred times bright here. It is not a
    difference that can be corrected: xterm answers what libX11
    computes, and a colour spec is only useful if it means the same
    thing on both. "CIELab:1/1/1" comes back 0x6c and not 0x07.
    """
    root = (lightness + 16.0) / 116.0
    cap_y = root * root * root
    if cap_y < _LOW_Y:
        root = lightness / 9.03292
        return (
            _WHITE[0] * (a_star / 3893.5 + root),
            root,
            _WHITE[2] * (root - b_star / 1557.4),
        )
    return (
        _WHITE[0] * (root + a_star / 5.0) ** 3,
        cap_y,
        _WHITE[2] * (root - b_star / 2.0) ** 3,
    )


def _luv(lightness: float, u_star: float, v_star: float):
    """
    `XcmsCIELuvToCIEuvY`, then on to CIEXYZ.

    The chroma is divided by the lightness over a hundred, where the
    CIE formula divides by the lightness itself.
    """
    cap_y = _lightness_to_y(lightness)
    if lightness == 0.0:
        return _uvy_to_xyz(_WHITE_UVY[0], _WHITE_UVY[1], cap_y)
    scale = 13.0 * (lightness / 100.0)
    return _uvy_to_xyz(
        u_star / scale + _WHITE_UVY[0],
        v_star / scale + _WHITE_UVY[1],
        cap_y,
    )


def _uvy(u_prime: float, v_prime: float, cap_y: float):
    "`XcmsCIEuvYToCIEXYZ`."
    return _uvy_to_xyz(u_prime, v_prime, cap_y)


def _hvc(hue: float, value: float, chroma: float):
    "`XcmsTekHVCToCIEuvY`, then on to CIEXYZ."
    if value == 0.0 or value == 100.0:
        cap_y = 1.0 if value == 100.0 else 0.0
        return _uvy_to_xyz(_WHITE_UVY[0], _WHITE_UVY[1], cap_y)
    turned = math.radians((hue + _THETA_OFFSET) % _TURN)
    reach = chroma / (value * _CHROMA_SCALE)
    return _uvy_to_xyz(
        math.cos(turned) * reach + _WHITE_UVY[0],
        math.sin(turned) * reach + _WHITE_UVY[1],
        _lightness_to_y(value),
    )


#: The colour spaces that a spec may name, and the conversion of each
#: one to CIEXYZ. The name is what the spec writes before the colon.
SPACES = {
    "CIEXYZ": _xyz,
    "CIEuvY": _uvy,
    "CIExyY": _xyy,
    "CIELab": _lab,
    "CIELuv": _luv,
    "TekHVC": _hvc,
}


def screen_rgb(xyz) -> Tuple[int, int, int] | None:
    """
    The eight bit colour that shows a CIEXYZ colour on the screen that
    Xcms assumes, or `None` for a colour it cannot show.

    A screen reaches only part of what the eye sees. Xcms answers a
    colour outside that part by pulling it in, which is a search
    through the TekHVC space that is not here yet. Until it is, an
    unshowable colour is no colour: an answer that guessed would be a
    colour the program did not ask for, and it could not tell.
    """
    lights = _matvec(_XYZ_TO_RGB, xyz)
    if min(lights) < -_GAMUT_SLOP or max(lights) > 1.0 + _GAMUT_SLOP:
        return None
    kept = []
    for channel, intensity in enumerate(lights):
        # The slop above lets a value just outside the range through,
        # so it is cut back before the table reads it.
        intensity = max(0.0, min(1.0, intensity))
        kept.append(intensity_to_value(channel, intensity) >> 8)
    return kept[0], kept[1], kept[2]
