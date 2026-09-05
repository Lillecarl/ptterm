"""
The background of a line that a scroll brings in.

A terminal that claims `bce` paints a new line with the background
that is set. The terminfo entry of a pane claims it, so every way of
bringing a line in has to paint it: SU, a linefeed at the bottom of
the screen, and a linefeed or IND at the bottom of a scrolling region.

A linefeed at the bottom of a screen with no region painted nothing,
so the same linefeed painted or did not paint by whether a program had
set a region. Alacritty's `vim_large_window_scroll` reference test
found it: vim writes a line, moves over eight cells with `CSI 8 C` and
writes again, so those eight cells hold what the scroll left there.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def row_style(data, row=3, lines=4, columns=6):
    "The style of the first cell of one visible row, after `data`."
    screen = BetterScreen(lines, columns, write_process_input=lambda answer: None)
    stream = BetterStream(screen)
    stream.feed(data)
    return screen.pt_screen.data_buffer[screen.line_offset + row][0].style


def test_a_scroll_up_paints_the_line_it_brings_in():
    assert row_style("\x1b[42m\x1b[1S") == "bg:#ansigreen "


def test_a_linefeed_at_the_bottom_paints_the_line_it_brings_in():
    "Four judges paint it: WezTerm, Alacritty, libvterm and xterm.js."
    assert row_style("\x1b[4;1H\x1b[42m\n") == "bg:#ansigreen "


def test_a_linefeed_in_a_region_paints_the_line_it_brings_in():
    "The region is rows one to three, so the new line is the third."
    assert row_style("\x1b[1;3r\x1b[3;1H\x1b[42m\n", row=2) == "bg:#ansigreen "


def test_an_index_in_a_region_paints_the_line_it_brings_in():
    assert row_style("\x1b[1;3r\x1b[3;1H\x1b[42m\x1bD", row=2) == "bg:#ansigreen "


def test_a_linefeed_with_no_background_leaves_the_row_out():
    "A row that carries nothing is absent, which keeps the screen sparse."
    screen = BetterScreen(4, 6, write_process_input=lambda answer: None)
    stream = BetterStream(screen)
    stream.feed("\x1b[4;1H\n")
    assert screen.line_offset + 3 not in screen.data_buffer


def test_a_linefeed_over_a_row_that_holds_text_keeps_it():
    "A linefeed in the middle of a screen brings no line in."
    screen = BetterScreen(4, 6, write_process_input=lambda answer: None)
    stream = BetterStream(screen)
    stream.feed("\x1b[3;1Hkeep\x1b[1;1H\x1b[42m\n")
    row = screen.pt_screen.data_buffer[screen.line_offset + 2]
    assert "".join(row[column].char for column in range(4)) == "keep"
