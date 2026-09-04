"""
The three ways a program asks a pane to change size.

DECSLPP ("CSI Ps t", Ps of 24 or more) asks for a page of that many
lines. "CSI 8 ; Ph ; Pw t" asks for rows and columns. "CSI 4 ; Ph ;
Pw t" asks for as many cells as fit in that many pixels.

A pane cannot resize itself. It sits in a layout that somebody else
owns, and making one pane taller makes another shorter. So the ask
goes to `resize_func` and the embedder decides. With no embedder the
ask goes nowhere.
"""
from ptterm.graphics import ASSUMED_CELL_HEIGHT, ASSUMED_CELL_WIDTH
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def _screen(lines=24, columns=80):
    asks = []
    screen = BetterScreen(
        lines,
        columns,
        write_process_input=lambda data: None,
        resize_func=lambda rows, cols: asks.append((rows, cols)),
    )
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream, asks


def test_a_page_length_asks_for_lines_and_leaves_the_columns():
    _screen_, stream, asks = _screen()
    stream.feed("\x1b[27t")
    assert asks == [(27, None)]


def test_the_lowest_page_length_is_twenty_four():
    """
    "CSI Ps t" below 24 names a window operation, not a page.

    23 pops a title, and must not ask for a page of 23 lines.
    """
    _screen_, stream, asks = _screen()
    stream.feed("\x1b[23t")
    assert asks == []


def test_a_resize_in_cells_asks_for_both():
    _screen_, stream, asks = _screen()
    stream.feed("\x1b[8;30;100t")
    assert asks == [(30, 100)]


def test_a_zero_asks_for_as_much_as_there_is():
    "The embedder cuts it down to what it really has."
    screen, stream, asks = _screen()
    stream.feed("\x1b[8;0;100t")
    assert asks == [(screen.MAX_LINES, 100)]


def test_a_number_that_is_not_there_leaves_that_side_alone():
    _screen_, stream, asks = _screen()
    stream.feed("\x1b[8;30t")
    assert asks == [(30, None)]


def test_a_resize_in_pixels_counts_them_in_cells():
    _screen_, stream, asks = _screen()
    stream.feed(
        "\x1b[4;%i;%it" % (30 * ASSUMED_CELL_HEIGHT, 100 * ASSUMED_CELL_WIDTH)
    )
    assert asks == [(30, 100)]


def test_a_resize_in_pixels_keeps_at_least_one_cell():
    "Fewer pixels than one cell still leaves a pane to draw in."
    _screen_, stream, asks = _screen()
    stream.feed("\x1b[4;1;1t")
    assert asks == [(1, 1)]


def test_a_pane_with_no_embedder_changes_nothing():
    screen = BetterScreen(24, 80, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    stream.attach(screen)
    stream.feed("\x1b[27t\x1b[8;30;100t")
    assert (screen.lines, screen.columns) == (24, 80)


def test_a_report_is_not_a_resize():
    "18 asks how big the pane is, and 8 asks it to become that big."
    _screen_, stream, asks = _screen()
    stream.feed("\x1b[18t")
    assert asks == []
