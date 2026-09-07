"""
Where a glyph sits: "CSI 73 m" raises it, "CSI 74 m" lowers it and
"CSI 75 m" puts it back on the line.

A terminal draws a raised or a lowered glyph smaller. A footnote mark
and a chemical formula need it, and a superscript two is a different
number from a two, so a program that asks for one and gets plain text
reads wrong rather than merely plain.

mintty brought the three codes. libvterm reads them, and asks for them
in `30state_pen.test`; WezTerm reads them as well. The panel says the
same: `test_the_panel.py` holds the tally, and the four judges that
cannot see a baseline abstain. Lillecarl/pymux#59.
"""
import pytest

from pyte.screen import Screen
from pyte.streams import Stream
from ptterm.style import style_of as spell


def screen(lines=2, columns=20):
    made = Screen(lines, columns, write_process_input=lambda answer: None)
    return made, Stream(made)


def style_of(made, row=0, column=0):
    cell = made.page.data_buffer[made.line_offset + row][column]
    return spell(cell.appearance)


def test_seventy_three_raises_a_glyph():
    made, stream = screen()
    stream.feed("\x1b[73mx")
    assert "superscript" in style_of(made).split()


def test_seventy_four_lowers_a_glyph():
    made, stream = screen()
    stream.feed("\x1b[74mx")
    assert "subscript" in style_of(made).split()


def test_a_plain_cell_sits_on_the_line():
    made, stream = screen()
    stream.feed("x")
    style = style_of(made).split()
    assert "superscript" not in style
    assert "subscript" not in style


def test_seventy_five_puts_the_glyph_back():
    made, stream = screen()
    stream.feed("\x1b[73ma\x1b[75mb")
    assert "superscript" in style_of(made, column=0).split()
    assert "superscript" not in style_of(made, column=1).split()


def test_the_two_replace_each_other():
    "A glyph sits in one place, so 74 after 73 lowers it rather than both."
    made, stream = screen()
    stream.feed("\x1b[73m\x1b[74mx")
    style = style_of(made).split()
    assert "subscript" in style
    assert "superscript" not in style


def test_a_reset_puts_the_glyph_back():
    made, stream = screen()
    stream.feed("\x1b[73ma\x1b[0mb")
    assert "superscript" not in style_of(made, column=1).split()


def test_the_baseline_lives_beside_the_other_attributes():
    made, stream = screen()
    stream.feed("\x1b[1;4;73;31mx")
    style = style_of(made).split()
    for word in ("bold", "underline", "superscript"):
        assert word in style, (word, style)


def test_seventy_five_leaves_the_other_attributes_alone():
    made, stream = screen()
    stream.feed("\x1b[1;4;73m\x1b[75mx")
    style = style_of(made).split()
    assert "superscript" not in style
    assert "bold" in style
    assert "underline" in style


@pytest.mark.parametrize(
    "sequence,word",
    [
        ("\x1b[73m", "superscript"),
        ("\x1b[0;73m", "superscript"),
        ("\x1b[39;74m", "subscript"),
    ],
)
def test_every_way_a_program_writes_it(sequence, word):
    made, stream = screen()
    stream.feed(sequence + "x")
    assert word in style_of(made).split()


@pytest.mark.parametrize("code", ["73", "74"])
def test_decrqss_reports_the_baseline_back(code):
    answers = []
    made = Screen(2, 20, write_process_input=answers.append)
    stream = Stream(made)
    stream.feed("\x1b[%sm\x1bP$qm\x1b\\" % code)
    assert answers, "the screen answered nothing"
    assert answers[-1].split("$r")[-1].startswith("0;%sm" % code), answers[-1]


def test_a_saved_cursor_brings_the_baseline_back():
    """
    DECSC saves the pen with the position, so DECRC gives the baseline
    back with it. The savepoint holds the whole of `_rendition`.
    """
    made, stream = screen()
    stream.feed("\x1b[73m\x1b7\x1b[75m\x1b8x")
    assert "superscript" in style_of(made).split()
