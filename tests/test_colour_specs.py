"""
Judge the colour spec parser against the real Xlib.

`ptterm/xcms.py` is a port. A port is only right where it agrees with
what it copies, so this asks libX11 the same question and compares the
two answers.

The check starts an Xvfb for this. Without one the tests skip, and the
build says so, because a judge that cannot run proves nothing.
"""
import pytest

from ptterm.osc import parse_color
from xlib_oracle import xlib_color, xlib_is_available

pytestmark = pytest.mark.skipif(
    not xlib_is_available(), reason="PTTERM_LIBX11 names no display"
)


#: The forms that `XParseColor` reads itself, before Xcms sees
#: anything. A short form pads to the right; `rgb:` scales.
DEVICE_SPECS = [
    "#000",
    "#fff",
    "#f00",
    "#123456",
    "#123456789abc",
    "#abcdef",
    "rgb:0/0/0",
    "rgb:f/f/f",
    "rgb:ff/ff/ff",
    "rgb:12/34/56",
    "rgb:ffff/0000/8000",
    "rgb:1234/5678/9abc",
]

#: The intensity form. Xcms reads it through the three per channel
#: tables of the built-in screen description, and the tables disagree
#: with each other, so a grey intensity is not a grey colour.
INTENSITY_SPECS = [
    "rgbi:0/0/0",
    "rgbi:1/1/1",
    "rgbi:0.5/0.5/0.5",
    "rgbi:0.25/0.5/0.75",
    "rgbi:0.1/0.2/0.3",
    "rgbi:0.9/0.05/0.5",
]

#: The six CIE spaces, with the two vectors that the conformance suite
#: checks in each one. Five hold inside what the screen can show. The
#: other seven leave it, and reach an answer only through the gamut
#: compressor.
CIE_SPECS = [
    "CIEXYZ:1/1/1",
    "CIEXYZ:0.5/0.5/0.5",
    "CIEuvY:1/1/1",
    "CIEuvY:0.5/0.5/0.5",
    "CIExyY:1/1/1",
    "CIExyY:0.5/0.5/0.5",
    "CIELab:1/1/1",
    "CIELab:0.5/0.5/0.5",
    "CIELuv:1/1/1",
    "CIELuv:0.5/0.5/0.5",
    "TekHVC:1/1/1",
    "TekHVC:0.5/0.5/0.5",
]

#: The range that each space counts in. A number means something
#: different in every one of them, so a grid that suits one is
#: nonsense in another.
RANGES = {
    "CIEXYZ": ([0.05, 0.3, 0.64, 0.95], [0.1, 0.4, 0.7, 1.0],
               [0.05, 0.35, 0.8, 1.4]),
    "CIEuvY": ([0.1, 0.19, 0.28, 0.4], [0.3, 0.4, 0.46, 0.55],
               [0.05, 0.3, 0.65, 1.0]),
    "CIExyY": ([0.15, 0.31, 0.45, 0.64], [0.06, 0.25, 0.33, 0.5],
               [0.05, 0.3, 0.65, 1.0]),
    "CIELab": ([5, 30, 60, 95], [-60, -10, 20, 70], [-60, -10, 20, 70]),
    "CIELuv": ([5, 30, 60, 95], [-60, -10, 20, 70], [-60, -10, 20, 70]),
    "TekHVC": ([0, 75, 160, 240, 300], [5, 30, 60, 95],
               [10, 40, 80, 120]),
}

#: A wider sweep of every space, to find the colours that the
#: conformance suite does not ask about. Most of them fall outside
#: what the screen can show, which is the part that has to be right.
GRID_SPECS = [
    "%s:%s/%s/%s" % (space, first, second, third)
    for space, (firsts, seconds, thirds) in RANGES.items()
    for first in firsts
    for second in seconds
    for third in thirds
]


def check(spec: str) -> None:
    "The port and libX11 answer `spec` the same way."
    assert parse_color(spec) == xlib_color(spec), spec


@pytest.mark.parametrize("spec", DEVICE_SPECS)
def test_a_device_spec_reads_the_way_xlib_reads_it(spec):
    check(spec)


@pytest.mark.parametrize("spec", INTENSITY_SPECS)
def test_an_intensity_reads_the_way_xlib_reads_it(spec):
    check(spec)


@pytest.mark.parametrize("spec", CIE_SPECS)
def test_a_cie_colour_reads_the_way_xlib_reads_it(spec):
    check(spec)


@pytest.mark.parametrize("spec", GRID_SPECS)
def test_the_wider_sweep_of_each_space_reads_the_way_xlib_reads_it(spec):
    check(spec)


def test_the_oracle_shows_the_disagreement_between_the_channel_tables():
    # The one measurement that says the tables are really in use: one
    # intensity on all three channels gives three different values.
    assert xlib_color("rgbi:0.5/0.5/0.5") == (0xC1, 0xBB, 0xBB)
