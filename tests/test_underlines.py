"""
The shape of an underline ("SGR 4:3") and its colour ("SGR 58").

A terminal draws five shapes of line, and paints the line in a colour
that is not the colour of the text. Both belong to a cell, so both
travel in the style of that cell: the shape as one word, the colour
after "ul:". prompt_toolkit reads them back and writes the sequences
again on the terminal of the user.
"""
import pytest

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def screen_of(data, lines=2, columns=20):
    "A screen that has read `data`."
    screen = BetterScreen(lines, columns, write_process_input=lambda answer: None)
    stream = BetterStream(screen)
    stream.feed(data)
    return screen


def styles(data, count):
    "The style of the first `count` cells of the first line."
    screen = screen_of(data)
    row = screen.pt_screen.data_buffer[screen.line_offset]
    return [row[x].style for x in range(count)]


@pytest.mark.parametrize(
    "parameter, word",
    [
        ("4", "underline"),
        ("4:1", "underline"),
        ("4:2", "underdouble"),
        ("4:3", "undercurl"),
        ("4:4", "underdotted"),
        ("4:5", "underdashed"),
        ("21", "underdouble"),
    ],
)
def test_every_shape_takes_its_own_word(parameter, word):
    assert styles("\x1b[%smA" % parameter, 1) == [word + " "]


def test_no_line_at_all():
    assert styles("\x1b[4:0mA", 1) == [""]
    assert styles("\x1b[4:3m\x1b[24mA", 1) == [""]
    assert styles("\x1b[4:3m\x1b[0mA", 1) == [""]


def test_a_plain_four_draws_a_single_line():
    "Whatever shape came before it. kitty and libvterm both do this."
    assert styles("\x1b[4:3m\x1b[4mA", 1) == ["underline "]


def test_the_colour_of_the_line():
    assert styles("\x1b[4;58:2::255:0:0mA", 1) == ["underline ul:#ff0000 "]
    assert styles("\x1b[4;58;2;255;0;0mA", 1) == ["underline ul:#ff0000 "]
    assert styles("\x1b[4;58:5:9mA", 1) == ["underline ul:#ansibrightred "]
    assert styles("\x1b[4;58;5;9mA", 1) == ["underline ul:#ansibrightred "]


def test_the_colour_goes_away_again():
    assert styles("\x1b[4;58:5:9m\x1b[59mA", 1) == ["underline "]
    assert styles("\x1b[4;58:5:9m\x1b[0mA", 1) == [""]


def test_a_colour_with_no_line_reaches_no_cell():
    """
    The colour stays on the screen, so a program that turns the line on
    again writes no colour a second time. It reaches a cell only while
    the line is drawn, because nobody sees a colour of a line that is
    not there.
    """
    assert styles("\x1b[58:5:9mA\x1b[4mB", 2) == ["", "underline ul:#ansibrightred "]
    # "SGR 24" takes the line away and keeps the colour, as kitty does.
    assert styles("\x1b[4;58:5:9m\x1b[24mA\x1b[4mB", 2) == [
        "",
        "underline ul:#ansibrightred ",
    ]


def test_an_erased_cell_keeps_the_line():
    "A reader sees a line on a blank, so an erase carries it over."
    assert styles("\x1b[4:3;58:5:9m\x1b[K", 2) == [
        "undercurl ul:#ansibrightred ",
        "undercurl ul:#ansibrightred ",
    ]


def test_the_screen_reports_the_shape_and_the_colour():
    "DECRQSS: a program reads back what it wrote."
    answers = []
    screen = BetterScreen(2, 10, write_process_input=answers.append)
    stream = BetterStream(screen)
    stream.feed("\x1b[4:3;58:2::1:2:3m\x1bP$qm\x1b\\")
    assert answers == ["\x1bP1$r0;4:3;58:2::1:2:3m\x1b\\"]


def test_a_shape_that_nobody_knows_is_left_alone():
    assert styles("\x1b[4:9mA", 1) == [""]


def test_a_private_marker_makes_another_sequence():
    """
    "CSI > 4 m" is XTMODKEYS, not SGR 4.

    A program sends it to put modifyOtherKeys back where it started.
    Claude Code sends it on startup. Read as SGR it turns the underline
    on, and every character the program draws after it carries a line
    that nobody asked for.
    """
    assert styles("\x1b[>4m> hello", 3) == ["", "", ""]
    # The same for the other markers, and for a plain SGR after one of
    # them: the marker belongs to that one sequence alone.
    assert styles("\x1b[?4mA", 1) == [""]
    assert styles("\x1b[<4mA", 1) == [""]
    assert styles("\x1b[>4m\x1b[4mA", 1) == ["underline "]
