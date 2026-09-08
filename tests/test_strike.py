"""
Crossed out text: "CSI 9 m" turns it on and "CSI 29 m" turns it off.

The screen used to read neither. It held a `strike` field that nothing
ever set, and its style string named every other attribute but this
one, so a program that crossed a word out drew a plain word.

The picture harness of pymux found it: the same program in the same
xterm drew a line through "struck" without a pane and no line with one.
"""
import pytest

from pyte.screen import Screen
from pyte.streams import Stream
from ptterm.style import style_of as spell
from pyte import escape
from pyte.sequences import csi


def screen(lines=2, columns=20):
    made = Screen(lines, columns, write_process_input=lambda answer: None)
    return made, Stream(made)


def style_of(made, row=0, column=0):
    cell = made.page.data_buffer[made.line_offset + row][column]
    return spell(cell.appearance)


def test_a_crossed_out_cell_says_so():
    made, stream = screen()
    stream.feed(csi(escape.SGR, 9) + "x")
    assert "strike" in style_of(made)


def test_a_plain_cell_does_not():
    made, stream = screen()
    stream.feed("x")
    assert "strike" not in style_of(made)


def test_twenty_nine_takes_the_line_away_again():
    made, stream = screen()
    stream.feed(csi(escape.SGR, 9) + "a" + csi(escape.SGR, 29) + "b")
    assert "strike" in style_of(made, column=0)
    assert "strike" not in style_of(made, column=1)


def test_a_reset_takes_the_line_away():
    made, stream = screen()
    stream.feed(csi(escape.SGR, 9) + "a" + csi(escape.SGR, 0) + "b")
    assert "strike" not in style_of(made, column=1)


def test_the_line_lives_beside_the_other_attributes():
    made, stream = screen()
    stream.feed(csi(escape.SGR, 1, 4, 9, 31) + "x")
    style = style_of(made)
    for word in ("bold", "underline", "strike"):
        assert word in style, (word, style)


def test_twenty_nine_leaves_the_other_attributes_alone():
    made, stream = screen()
    stream.feed(csi(escape.SGR, 1, 4, 9) + csi(escape.SGR, 29) + "x")
    style = style_of(made)
    assert "strike" not in style
    assert "bold" in style
    assert "underline" in style


@pytest.mark.parametrize("sequence", [csi(escape.SGR, 9), csi(escape.SGR, 0, 9), csi(escape.SGR, 39, 9)])
def test_every_way_a_program_writes_it(sequence):
    made, stream = screen()
    stream.feed(sequence + "x")
    assert "strike" in style_of(made)


def test_decrqss_reports_the_line_back():
    """
    `report_graphic_rendition` already knew the parameter and could
    never reach it, because nothing set the field.
    """
    answers = []
    made = Screen(2, 20, write_process_input=answers.append)
    stream = Stream(made)
    stream.feed("\x1b[9m\x1bP$qm\x1b\\")
    assert answers, "the screen answered nothing"
    assert "9" in answers[-1].split("$r")[-1], answers[-1]
