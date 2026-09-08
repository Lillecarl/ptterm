"""
A colour that a program names by number ("CSI 38 ; 5 ; n m").

The palette is not 256 colours. It is 256 questions, and the terminal
of the user answers them from its own theme. A pane that turns number
234 into the grey of xterm throws that answer away, so a number stays
a number all the way through the screen.

The first sixteen carry a name that prompt_toolkit already knows, and
the other 240 are written "ansi16" up to "ansi255".
"""
from pyte.screen import Screen
from pyte.streams import Stream
from ptterm.style import style_of as spell
from pyte import escape
from pyte.sequences import csi


def style_of(data, column=0):
    "The style of one cell, after `data`."
    screen = Screen(2, 8, write_process_input=lambda answer: None)
    stream = Stream(screen)
    stream.feed(data)
    cell = screen.page.data_buffer[screen.line_offset][column]
    return spell(cell.appearance)


def test_the_first_sixteen_keep_their_name():
    assert style_of(csi(escape.SGR, 38, 5, 1) + "A") == "#ansired "
    assert style_of(csi(escape.SGR, 38, 5, 9) + "A") == "#ansibrightred "
    assert style_of(csi(escape.SGR, 48, 5, 15) + "A") == "bg:#ansiwhite "


def test_a_number_above_fifteen_keeps_its_number():
    assert style_of(csi(escape.SGR, 38, 5, 200) + "A") == "#ansi200 "
    assert style_of(csi(escape.SGR, 48, 5, 234) + "A") == "bg:#ansi234 "


def test_the_last_two_numbers_are_colours_too():
    """
    The table of prompt_toolkit held 254 colours, so 254 and 255 were
    dropped and the cell took no colour at all.
    """
    assert style_of(csi(escape.SGR, 38, 5, 254) + "A") == "#ansi254 "
    assert style_of(csi(escape.SGR, 38, 5, 255) + "A") == "#ansi255 "


def test_a_number_outside_the_palette_paints_nothing():
    "There is no colour 256, so the cell keeps the one it had."
    assert style_of(csi(escape.SGR, 38, 5, 256) + "A") == ""


def test_a_colour_of_its_own_stays_a_colour():
    "A program that names three components asks for those components."
    assert style_of(csi(escape.SGR, 38, 2, 1, 2, 3) + "A") == "#010203 "


def test_the_colour_of_an_underline_takes_a_number():
    assert style_of(csi(escape.SGR, 4, 58, 5, 200) + "A") == "underline ul:#ansi200 "
