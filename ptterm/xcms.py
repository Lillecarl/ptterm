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
import sys
from typing import List, NamedTuple, Tuple

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

#: How far the TekHVC search may miss the value it aims at. `EPS` of
#: `src/xcms/HVC.c` and `src/xcms/HVCMxC.c`.
_SEARCH_SLOP = 0.001

#: What stands in for a zero that would divide. `EPS` of
#: `src/xcms/xyY.c`.
_NEARLY_NOTHING = 0.00001

#: Below `_LOW_LIGHTNESS` the CIE lightness formula turns into a
#: straight line. This is the slope of that line.
_LIGHTNESS_SLOPE = 903.29

#: Below this the CIE lightness formula turns into a straight line.
#: `_LIGHTNESS_SLOPE` is the slope, and this is where the two meet.
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

#: A quarter turn. The hue search reads the tangent, which repeats
#: every half turn, and puts the answer back in its quadrant by steps
#: of this.
_QUADRANT = 90.0

#: The most value and the most chroma a TekHVC colour can carry.
_MAX_VALUE = 100.0
_MAX_CHROMA = 100.0

#: Where the search for the most chroma of a hue starts. `START_V` and
#: `START_C` of `src/xcms/HVCMxVC.c`. Both name a colour no screen can
#: show, which is the point: the search walks in from outside.
_START_VALUE = 40.0
_START_CHROMA = 120.0

#: How many steps the chroma search takes before it gives up.
#: `MAXBISECTCOUNT` of `src/xcms/HVCMxC.c`.
_MAX_STEPS = 100

#: What `_XcmsTekHVC_CheckModify` moves a value by to bring it inside
#: the range. `XMY_DBL_EPSILON`, which is `DBL_EPSILON` here.
_TINY = sys.float_info.epsilon


# ----------------------------------------------------------------------
# The arithmetic of Xcms.
#
# Xcms carries its own square root, cube root and arc tangent, in
# `src/xcms/cmsMath.c` and `src/xcms/cmsTrig.c`. It wrote them when a
# machine could not be trusted to carry a maths library, and it still
# calls them.
#
# The arc tangent is the one that matters. It stops as soon as it is
# within a millionth, where the one of Python is exact to the last bit.
# A millionth of a hue moves the gamut search by enough to change the
# answer: a channel that should sit just above nothing comes out at
# nothing, and the table below turns that into a different colour.
#
# So these are here. They are slower and less exact, and that is the
# point: they are what xterm answers with.

#: How near the arc tangent has to come before it stops.
#: `XCMS_MAXERROR`.
_MAX_ERROR = 0.000001

#: How many turns of the loop it takes at the most. `XCMS_MAXITER`.
#: The loop reaches `_MAX_ERROR` in a few, so this only guards.
_MAX_ITER = 10000


def _square_root(a: float) -> float:
    "`_XcmsSquareRoot`: Newton's method, until the step is one bit."
    if a <= 0.0:
        return 0.0
    guess = a / 4.0 if a > 1.0 else a * 4.0
    while True:
        delta = (guess - a / guess) / 2.0
        guess -= delta
        if delta < 0.0:
            delta = -delta
        if delta < guess * _TINY:
            return guess


def _cube_root(a: float) -> float:
    "`_XcmsCubeRoot`, the same way."
    if a == 0.0:
        return 0.0
    size = -a if a < 0.0 else a
    guess = size / 8.0 if size > 1.0 else size * 8.0
    while True:
        delta = (guess - size / (guess * guess)) / 3.0
        guess -= delta
        if delta < 0.0:
            delta = -delta
        if delta < guess * _TINY:
            return -guess if a < 0.0 else guess


def _arc_tangent(x: float) -> float:
    """
    `_XcmsArcTangent`: the arc tangent, in radians, by the algorithm
    of Gauss.

    It stops within `_MAX_ERROR`, so it answers about six digits and
    not sixteen. For a negative `x` below one the margin is negative
    too, and then it runs until the two bounds meet. That is what
    libX11 does, so it is what this does.
    """
    if x == 0.0:
        return 0.0
    margin = x * _MAX_ERROR if x < 1.0 else _MAX_ERROR
    low = _square_root(1.0 / (1.0 + x * x))
    high = 1.0
    middle = geometric = 0.0
    for _turn in range(_MAX_ITER):
        middle = (low + high) / 2.0
        geometric = _square_root(middle * high)
        if middle == geometric:
            break
        if abs(middle - geometric) < margin:
            break
        low, high = middle, geometric
    return x / (_square_root(1 + x * x) * min(middle, geometric))


#: The turn, the half turn and the quarter turn in radians, written
#: the way `src/xcms/cmsTrig.c` writes them. They are the decimals of
#: libX11 and not the nearest double to the true number, and the
#: argument reduction below subtracts them.
_TWO_PI = 6.28318530717958620
_HALF_PI = 1.57079632679489660
_FOURTH_PI = 0.785398163397448280

#: Below this the sixth power of the argument underflows, and the
#: polynomial cannot be read. `XCMS_X6_UNDERFLOWS`.
_TOO_SMALL = 4.209340e-52

#: The largest power of two a double holds exactly. Adding it to a
#: number and taking it away again drops the fraction.
#: `XCMS_DMAXPOWTWO`.
_BIG = 2147483647.0 * (1 << 22)

#: The coefficients of the two fractions that give the cosine and the
#: sine. Hart, "Computer Approximations", tables 3843 and 3341.
_COS_TOP = (
    0.12905394659037374438e7, -0.37456703915723204710e6,
    0.13432300986539084285e5, -0.11231450823340933092e3)
_COS_BOTTOM = (
    0.12905394659037373590e7, 0.23467773107245835052e5,
    0.20969518196726306286e3, 1.0)
_SIN_TOP = (
    0.20664343336995858240e7, -0.18160398797407332550e6,
    0.35999306949636188317e4, -0.20107483294588615719e2)
_SIN_BOTTOM = (
    0.26310659102647698963e7, 0.39270242774649000308e5,
    0.27811919481083844087e3, 1.0)


def _polynomial(coefficients, x: float) -> float:
    "`_XcmsPolynomial`: Horner's rule, from the last coefficient back."
    answer = coefficients[-1]
    for coefficient in reversed(coefficients[:-1]):
        answer = coefficient + x * answer
    return answer


def _modulo(value: float, base: float) -> float:
    "`_XcmsModulo`: the remainder, by dropping a fraction with `_BIG`."
    value /= base
    size = -value if value < 0.0 else value
    if size >= _BIG:
        whole = value
    else:
        whole = size + _BIG
        whole -= _BIG
        if whole > size:
            whole -= 1.0
        whole = -whole if whole < 0.0 else whole
    return (value - whole) * base


def _cosine(x: float) -> float:
    "`_XcmsCosine`: the cosine, by argument reduction and Hart's fraction."
    if x < -math.pi or x > math.pi:
        x = _modulo(x, _TWO_PI)
        if x > math.pi:
            x = x - _TWO_PI
        elif x < -math.pi:
            x = x + _TWO_PI
    if x > _HALF_PI:
        return -_cosine(x - math.pi)
    if x < -_HALF_PI:
        return -_cosine(x + math.pi)
    if x > _FOURTH_PI:
        return _sine(_HALF_PI - x)
    if x < -_FOURTH_PI:
        return _sine(_HALF_PI + x)
    if -_TOO_SMALL < x < _TOO_SMALL:
        return _square_root(1.0 - x * x)
    y = x / _FOURTH_PI
    square = y * y
    return _polynomial(_COS_TOP, square) / _polynomial(_COS_BOTTOM, square)


def _sine(x: float) -> float:
    "`_XcmsSine`, the same way."
    if x < -math.pi or x > math.pi:
        x = _modulo(x, _TWO_PI)
        if x > math.pi:
            x = x - _TWO_PI
        elif x < -math.pi:
            x = x + _TWO_PI
    if x > _HALF_PI:
        return -_sine(x - math.pi)
    if x < -_HALF_PI:
        return -_sine(x + math.pi)
    if x > _FOURTH_PI:
        return _cosine(_HALF_PI - x)
    if x < -_FOURTH_PI:
        return -_cosine(_HALF_PI + x)
    if -_TOO_SMALL < x < _TOO_SMALL:
        return x
    y = x / _FOURTH_PI
    square = y * y
    return y * (
        _polynomial(_SIN_TOP, square) / _polynomial(_SIN_BOTTOM, square)
    )


def _degrees(radians: float) -> float:
    """
    Radians as degrees, the way libX11 writes it.

    `math.degrees` multiplies by one constant that it rounded once.
    libX11 multiplies by 180 and then divides. The two answers differ
    in the last bit, and the search below reads that bit.
    """
    return radians * 180.0 / math.pi


def _radians(degrees: float) -> float:
    "Degrees as radians, the way libX11 writes it."
    return degrees * math.pi / 180.0


def _matvec(matrix, vector) -> Tuple[float, float, float]:
    """
    One 3x3 matrix times one vector. `_XcmsMatVec`.

    The three products are added one at a time, from a running total
    that starts at nothing, the way the C loop does it. `sum` of
    Python corrects the error as it goes and answers a different last
    bit, and that bit decides whether a channel comes out at nothing
    or a little above it.
    """
    answer = []
    for row in range(3):
        total = 0.0
        for column in range(3):
            total += matrix[row][column] * vector[column]
        answer.append(total)
    return answer[0], answer[1], answer[2]


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
#:
#: The Y is set to one and not to the sum. libX11 does that in
#: `LINEAR_RGB_InitSCCData`: it reads the sum, refuses a screen whose
#: sum is not one within a thousandth, and then writes one anyway. The
#: last bits of the sum are what the hue search subtracts, so the
#: difference between the sum and one changes the answer.
#: The X and the Z are added one at a time. `sum` of Python corrects
#: the error as it goes, which gives a different last bit from the
#: plain addition that C does.
_WHITE = (
    _RGB_TO_XYZ[0][0] + _RGB_TO_XYZ[0][1] + _RGB_TO_XYZ[0][2],
    1.0,
    _RGB_TO_XYZ[2][0] + _RGB_TO_XYZ[2][1] + _RGB_TO_XYZ[2][2],
)
_WHITE_UVY = _xyz_to_uvy(_WHITE)

#: Where TekHVC starts counting hue, given that white. `ThetaOffset`.
_THETA_OFFSET = _degrees(_arc_tangent(
    (_BEST_RED[1] - _WHITE_UVY[1]) / (_BEST_RED[0] - _WHITE_UVY[0])
))


def _lightness_to_y(lightness: float) -> float:
    "The CIE lightness formula, as `Luv.c` and `HVC.c` write it."
    if lightness < _LOW_LIGHTNESS:
        return lightness / _LIGHTNESS_SLOPE
    root = (lightness + 16.0) / 116.0
    return root * root * root


def _xyz(x: float, y: float, z: float):
    "CIEXYZ, which needs no conversion at all."
    return (x, y, z)


def _xyy(x: float, y: float, cap_y: float):
    """
    `XcmsCIExyYToCIEXYZ`.

    It goes the long way round: x and y to u' and v', and then back to
    x and y again. The two are the same on paper. They are not the
    same in the last bit, and a colour near the edge of the gamut
    reads that bit.
    """
    divisor = -2 * x + 12 * y + 3
    if divisor == 0.0:
        return (0.0, 0.0, 0.0)
    u_prime = 4 * x / divisor
    v_prime = 9 * y / divisor
    divisor = 6.0 * u_prime - 16.0 * v_prime + 12.0
    if divisor == 0.0:
        # libX11 reads a white point it never filled in here. No
        # chromaticity reaches this, so answer nothing instead.
        return (0.0, 0.0, 0.0)
    x = 9.0 * u_prime / divisor
    y = 4.0 * v_prime / divisor
    z = 1.0 - x - y
    if y == 0.0:
        y = _NEARLY_NOTHING
    return (x * cap_y / y, cap_y, z * cap_y / y)


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
    # Multiplied out one at a time, the way libX11 writes it. A cube
    # rounds once; three products round three times.
    reach_x = root + a_star / 5.0
    reach_z = root - b_star / 2.0
    return (
        _WHITE[0] * reach_x * reach_x * reach_x,
        cap_y,
        _WHITE[2] * reach_z * reach_z * reach_z,
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
    turned = _radians((hue + _THETA_OFFSET) % _TURN)
    reach = value * _CHROMA_SCALE
    return _uvy_to_xyz(
        _cosine(turned) * chroma / reach + _WHITE_UVY[0],
        _sine(turned) * chroma / reach + _WHITE_UVY[1],
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


# ----------------------------------------------------------------------
# Gamut compression.
#
# A screen shows only part of what the eye sees. Xcms answers a colour
# outside that part by pulling it in rather than by cutting each
# channel to its range. Cutting gives a different colour: "CIEXYZ:1/1/1"
# cut per channel is ffff/f6f6/d5d5, where xterm answers ffff/ffff/ffff.
#
# The way in is `XcmsTekHVCClipC`, named at `src/xcms/cmsInt.c:47`. It
# keeps the hue and the value of the colour and takes the chroma down
# to the most that the screen can carry for them.


class Hvc(NamedTuple):
    "One colour in the TekHVC space: hue, value and chroma."

    hue: float
    value: float
    chroma: float


def _valid(color: Hvc) -> Hvc:
    """
    `_XcmsTekHVC_CheckModify`: bring a TekHVC colour into range.

    The value goes inside the range by one step of `_TINY`, and not to
    the edge, because the conversion out divides by it.
    """
    hue, value, chroma = color
    if value < 0.0:
        value = 0.0 + _TINY
    elif value > _MAX_VALUE:
        value = _MAX_VALUE - _TINY
    if chroma < 0.0:
        chroma = 0.0 - _TINY
    return Hvc(hue % _TURN, value, chroma)


def _uvy_to_hvc(u_prime: float, v_prime: float, cap_y: float) -> Hvc:
    """
    `XcmsCIEuvYToTekHVC`, the way back from `_hvc`.

    The hue is the angle from the white point. libX11 reads it with a
    plain arc tangent and then puts it back in its quadrant by hand,
    so this does the same rather than call `atan2`: the two differ on
    an axis, where the tangent is not defined.
    """
    u = u_prime - _WHITE_UVY[0]
    v = v_prime - _WHITE_UVY[1]
    theta = 0.0 if u == 0.0 else _degrees(_arc_tangent(v / u))
    low, high = 0.0, _TURN
    if u > 0.0 and v > 0.0:
        low, high = 0.0, _QUADRANT
    elif u < 0.0 and v > 0.0:
        low, high = _QUADRANT, 2.0 * _QUADRANT
    elif u < 0.0 and v < 0.0:
        low, high = 2.0 * _QUADRANT, 3.0 * _QUADRANT
    elif u > 0.0 and v < 0.0:
        low, high = 3.0 * _QUADRANT, _TURN
    while theta < low:
        theta += _QUADRANT
    while theta >= high:
        theta -= _QUADRANT

    if cap_y < _LOW_Y:
        value = cap_y * _LIGHTNESS_SLOPE
    else:
        value = _cube_root(cap_y) * 116.0 - 16.0
    chroma = value * _CHROMA_SCALE * _square_root(u * u + v * v)
    if chroma < 0.0:
        theta = 0.0
    hue = theta - _THETA_OFFSET
    while hue < -_SEARCH_SLOP:
        hue += _TURN
    while hue >= _TURN + _SEARCH_SLOP:
        hue -= _TURN
    return Hvc(hue, value, chroma)


def _xyz_to_hvc(xyz) -> Hvc:
    "CIEXYZ to TekHVC, through CIEuvY."
    return _uvy_to_hvc(*_xyz_to_uvy(xyz))


def _rgb_to_hvc(rgb) -> Hvc:
    "The light each channel gives, as a TekHVC colour."
    return _xyz_to_hvc(_matvec(_RGB_TO_XYZ, rgb))


def _hvc_to_rgb(color: Hvc) -> Tuple[float, float, float]:
    """
    A TekHVC colour as the light each channel gives.

    The answer may leave the range 0 to 1. That is what the search
    below reads: libX11 hands the out of range values back on purpose
    when no compressor is installed, and calls it "that little trick".
    """
    return _matvec(_XYZ_TO_RGB, _hvc(*color))


def _most_chroma_of_hue(hue: float) -> Tuple[Hvc, Tuple[float, float, float]]:
    """
    `_XcmsTekHVCQueryMaxVCRGB`: the most chroma a hue can carry, with
    the value that goes with it, and the channel lights that show it.

    It starts from a colour of that hue that no screen can show, and
    walks in: it takes the smallest of the three lights off all three,
    which puts one channel at nothing, then divides by the largest,
    which puts another at full. That corner of the cube is the most
    saturated colour of the hue.
    """
    lights = _hvc_to_rgb(Hvc(hue, _START_VALUE, _START_CHROMA))
    smallest = min(lights)
    lights = tuple(light - smallest for light in lights)
    largest = max(lights)
    lights = tuple(light / largest for light in lights)
    found = _rgb_to_hvc(lights)
    return Hvc(hue, found.value, found.chroma), lights  # type: ignore[return-value]


def _most_chroma(hue: float, value: float) -> Hvc:
    """
    `XcmsTekHVCQueryMaxC`: the most chroma that a hue and a value
    allow.

    Below the value of the most saturated colour of the hue, the edge
    of the gamut is the straight line from black to that colour, so
    one division answers. Above it the edge is a curve, and libX11
    walks towards the wanted value by mixing the saturated colour with
    white. The step is the miss of the last try, and the step shrinks
    whenever the walk stalls or overshoots.
    """
    aim = _valid(Hvc(hue, value, _MAX_CHROMA))
    corner, saturated = _most_chroma_of_hue(hue)

    if value <= corner.value:
        return _valid(aim._replace(chroma=value * corner.chroma / corner.value))

    wanted = value
    reached = aim
    # Two values that no colour carries, so that the first two steps
    # cannot read a try that never happened.
    last = Hvc(hue, -1.0, -1.0)
    distance = _MAX_VALUE - corner.value
    shrink = 1.0

    def closer() -> Hvc:
        "Whichever of the last two tries came nearer the wanted value."
        if abs(last.value - value) < abs(reached.value - value):
            return Hvc(hue, last.value, last.chroma)
        return reached._replace(hue=hue)

    for _step in range(_MAX_STEPS):
        before_last = last
        last = reached

        # How far from the saturated colour towards white to stand.
        share = (wanted - corner.value) / distance * shrink
        reached = _rgb_to_hvc(
            tuple(light * (1.0 - share) + share for light in saturated)
        )

        if abs(reached.value - value) <= _SEARCH_SLOP:
            return _valid(reached._replace(hue=hue))

        wanted += value - reached.value
        if wanted < corner.value:
            wanted = corner.value
            shrink *= 0.5
        elif wanted > _MAX_VALUE:
            return _valid(closer())
        elif abs(reached.value - before_last.value) <= _SEARCH_SLOP:
            shrink *= 0.5

    # The walk ran out of steps. libX11 answers with the nearer of the
    # last two tries and does not bring it into range, so neither does
    # this.
    return closer()


def _clip_chroma(xyz) -> Tuple[float, float, float]:
    """
    `XcmsTekHVCClipC`: the nearest showable colour of the same hue and
    value.

    The grey branch of libX11 is left out. It answers for a screen
    that shows no colour at all, and a terminal does not run on one.
    """
    color = _xyz_to_hvc(xyz)
    return _hvc(*_most_chroma(color.hue, color.value))


def screen_rgb(xyz) -> Tuple[int, int, int] | None:
    """
    The eight bit colour that shows a CIEXYZ colour on the screen that
    Xcms assumes.

    A colour the screen cannot show is pulled in first. The answer is
    `None` only when that fails, which leaves the pane with no answer
    to give, the same as libX11 gives its caller.
    """
    lights = _matvec(_XYZ_TO_RGB, xyz)
    if min(lights) < -_GAMUT_SLOP or max(lights) > 1.0 + _GAMUT_SLOP:
        lights = _matvec(_XYZ_TO_RGB, _clip_chroma(xyz))
        if min(lights) < -_GAMUT_SLOP or max(lights) > 1.0 + _GAMUT_SLOP:
            return None
    kept = []
    for channel, intensity in enumerate(lights):
        # The slop above lets a value just outside the range through,
        # so it is cut back before the table reads it.
        intensity = max(0.0, min(1.0, intensity))
        kept.append(intensity_to_value(channel, intensity) >> 8)
    return kept[0], kept[1], kept[2]
