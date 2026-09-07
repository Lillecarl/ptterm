"""
The colour arithmetic of SGR, on its own.

"SGR 38", "48" and "58" carry a colour in one of two forms, and how
many parameters each form takes decides where the next attribute
starts. That is arithmetic on numbers: no sequence is read and none is
written, so it lives in `ptterm/colors.py` beside the palette.

What a screen does with the answer is the other half. It keeps the
number, and `ptterm/style.py` spells it as a prompt_toolkit style
word, because the spelling belongs to whoever draws.

`test_indexed_colors.py` and `test_colon_colors.py` judge the whole
path through a screen. This file judges the arithmetic alone, so a
failure says which half is wrong.
"""
import pytest

from pyte.colors import Color, sgr_color, sgr_color_parameters


#: How many parameters each form takes, counting the "38" itself.
@pytest.mark.parametrize(
    "parameters, count",
    [
        ([38, 5, 200], 3),
        ([38, 2, 1, 2, 3], 5),
        # Nothing after the "38" yet: read one more and ask again.
        ([38], 3),
        # A form nobody defines takes what is there and no more, so one
        # bad sequence does not eat the attributes after it.
        ([38, 7, 1], 3),
        ([38, 7, 1, 2], 4),
    ],
)
def test_how_many_parameters_a_colour_takes(parameters, count):
    assert sgr_color_parameters(parameters) == count


def test_a_number_of_the_palette_stays_a_number():
    "The terminal of the user paints it, and that terminal has a theme."
    assert sgr_color([38, 5, 200]) == (200, None)


def test_a_colour_of_its_own_is_three_components():
    assert sgr_color([48, 2, 1, 2, 3]).rgb == Color(1, 2, 3)


def test_the_colon_form_may_name_a_colour_space_first():
    "Nobody uses it, so the extra number goes away."
    assert sgr_color([58, 2, 0, 1, 2, 3]).rgb == Color(1, 2, 3)


@pytest.mark.parametrize(
    "parameters",
    [
        [38],
        [38, 5],
        # Two components is not a colour.
        [38, 2, 1, 2],
        # A form nobody defines.
        [38, 7, 1, 2, 3],
        # A number outside the palette. The rendition keeps the colour
        # it had, the way a terminal that cannot read a parameter does.
        [38, 5, 256],
        [38, 5, -1],
    ],
)
def test_what_is_not_a_colour(parameters):
    assert sgr_color(parameters) is None


def test_the_last_number_of_the_palette_is_a_colour():
    "The edge of the range above, from the inside."
    assert sgr_color([38, 5, 255]).index == 255


def test_the_two_forms_are_told_apart_by_which_field_is_set():
    "Exactly one of the two, so a caller reads `index is not None`."
    of_the_palette = sgr_color([38, 5, 9])
    of_its_own = sgr_color([38, 2, 9, 9, 9])
    assert of_the_palette.index == 9 and of_the_palette.rgb is None
    assert of_its_own.index is None and of_its_own.rgb == Color(9, 9, 9)
