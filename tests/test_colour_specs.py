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

#: The CIE spaces that hold inside what the screen can show. The ones
#: that leave it need the gamut compressor.
IN_GAMUT_SPECS = [
    "CIEXYZ:0.5/0.5/0.5",
    "CIELab:1/1/1",
    "CIELab:0.5/0.5/0.5",
    "TekHVC:1/1/1",
    "TekHVC:0.5/0.5/0.5",
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


@pytest.mark.parametrize("spec", IN_GAMUT_SPECS)
def test_a_cie_colour_inside_the_gamut_reads_the_way_xlib_reads_it(spec):
    check(spec)


def test_the_oracle_shows_the_disagreement_between_the_channel_tables():
    # The one measurement that says the tables are really in use: one
    # intensity on all three channels gives three different values.
    assert xlib_color("rgbi:0.5/0.5/0.5") == (0xC1, 0xBB, 0xBB)
