"""
How prompt_toolkit spells a colour.

A screen holds a colour as a number, and `ptterm/style.py` turns that
number into the word a prompt_toolkit renderer reads. It is the whole
of what a front end adds to a colour, so a second front end replaces
this file and nothing else (Lillecarl/pymux#82).

`test_indexed_colors.py` and `test_colon_colors.py` judge the same
words through a whole screen. This file judges the spelling alone, so
a failure says which half is wrong.
"""
import pytest

from pyte.colors import DEFAULT_COLOR, PALETTE, Color, SgrColor
from ptterm.style import style_word


@pytest.mark.parametrize(
    "index, word",
    [
        (0, "#ansiblack"),
        (1, "#ansired"),
        (7, "#ansigray"),
        (8, "#ansibrightblack"),
        (15, "#ansiwhite"),
        # Above the sixteen that have names, the number itself.
        (16, "#ansi16"),
        (234, "#ansi234"),
        (255, "#ansi255"),
    ],
)
def test_a_number_of_the_palette_keeps_its_number(index, word):
    """
    A pane never paints a colour of the palette itself. The terminal of
    the user has a theme, and prompt_toolkit writes the SGR code back
    out so that terminal paints its own red.
    """
    assert style_word(SgrColor(index=index)) == word


def test_a_colour_of_its_own_is_six_digits():
    "No theme has an opinion about a colour a program named itself."
    assert style_word(SgrColor(rgb=Color(0x12, 0xAB, 0x00))) == "#12ab00"


def test_the_default_colour_has_a_word_of_its_own():
    """
    "SGR 39" names the colour of the terminal. It is not the same as no
    colour at all, and a renderer has to be told which one it is.
    """
    assert style_word(DEFAULT_COLOR) == "#ansidefault"


def test_every_word_opens_with_a_hash():
    """
    It tells prompt_toolkit to take the colour and not to look it up.

    The range is the palette, and it stops there on purpose: `sgr_color`
    is the only thing that makes a number, and it refuses one the
    palette does not hold. A number above 255 would spell "#ansi256",
    which prompt_toolkit reads as a style class it cannot find.
    """
    colors = [DEFAULT_COLOR, SgrColor(rgb=Color(1, 2, 3))]
    colors += [SgrColor(index=number) for number in range(len(PALETTE))]
    assert all(style_word(color).startswith("#") for color in colors)
