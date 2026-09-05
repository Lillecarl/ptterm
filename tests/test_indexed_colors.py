"""
A colour that a program names by number ("CSI 38 ; 5 ; n m").

The palette is not 256 colours. It is 256 questions, and the terminal
of the user answers them from its own theme. A pane that turns number
234 into the grey of xterm throws that answer away, so a number stays
a number all the way through the screen.

The first sixteen carry a name that prompt_toolkit already knows, and
the other 240 are written "ansi16" up to "ansi255".
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def style_of(data, column=0):
    "The style of one cell, after `data`."
    screen = BetterScreen(2, 8, write_process_input=lambda answer: None)
    stream = BetterStream(screen)
    stream.feed(data)
    return screen.pt_screen.data_buffer[screen.line_offset][column].style


def test_the_first_sixteen_keep_their_name():
    assert style_of("\x1b[38;5;1mA") == "#ansired "
    assert style_of("\x1b[38;5;9mA") == "#ansibrightred "
    assert style_of("\x1b[48;5;15mA") == "bg:#ansiwhite "


def test_a_number_above_fifteen_keeps_its_number():
    assert style_of("\x1b[38;5;200mA") == "#ansi200 "
    assert style_of("\x1b[48;5;234mA") == "bg:#ansi234 "


def test_the_last_two_numbers_are_colours_too():
    """
    The table of prompt_toolkit held 254 colours, so 254 and 255 were
    dropped and the cell took no colour at all.
    """
    assert style_of("\x1b[38;5;254mA") == "#ansi254 "
    assert style_of("\x1b[38;5;255mA") == "#ansi255 "


def test_a_number_outside_the_palette_paints_nothing():
    "There is no colour 256, so the cell keeps the one it had."
    assert style_of("\x1b[38;5;256mA") == ""


def test_a_colour_of_its_own_stays_a_colour():
    "A program that names three components asks for those components."
    assert style_of("\x1b[38;2;1;2;3mA") == "#010203 "


def test_the_colour_of_an_underline_takes_a_number():
    assert style_of("\x1b[4;58;5;200mA") == "underline ul:#ansi200 "
