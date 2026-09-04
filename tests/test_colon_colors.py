"""
A colour that arrives with colons ("CSI 38:2::1:2:3 m").

ECMA-48 writes the parts of one parameter with colons between them,
and a program that follows it sends the colour that way. The parts
reach the screen as one tuple, so the screen has to read a tuple as
well as a row of numbers.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def style_of(data, column=0):
    "The style of one cell, after `data`."
    screen = BetterScreen(2, 8, write_process_input=lambda answer: None)
    stream = BetterStream(screen)
    stream.feed(data)
    return screen.pt_screen.data_buffer[screen.line_offset][column].style


def test_a_colour_of_the_palette_takes_colons():
    assert style_of("\x1b[38:5:9mA") == style_of("\x1b[38;5;9mA")
    assert "#ansibrightred" in style_of("\x1b[38:5:9mA")


def test_a_colour_of_its_own_takes_colons():
    assert style_of("\x1b[38:2::1:2:3mA") == "#010203 "
    assert style_of("\x1b[48:2::1:2:3mA") == "bg:#010203 "


def test_the_colour_space_may_be_left_out():
    "Three numbers name the colour, four name it after a colour space."
    assert style_of("\x1b[38:2:1:2:3mA") == "#010203 "
    assert style_of("\x1b[38:2:0:1:2:3mA") == "#010203 "


def test_a_colour_with_colons_stands_next_to_other_parameters():
    assert style_of("\x1b[1;38:2::1:2:3;4mA") == "#010203 bold underline "


def test_a_short_colour_draws_nothing():
    assert style_of("\x1b[38:2mA") == ""
    assert style_of("\x1b[38:9:1mA") == ""
