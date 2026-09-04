"""
The colours that a program sets and reads back.

A pane holds its own palette. A program writes an entry with "OSC 4",
reads it with "OSC 4 ; n ; ?" and gets what it wrote. "OSC 104" puts
the entry back. The special colours work the same way under two codes:
"OSC 5" numbers them from zero and "OSC 4" numbers them after the
palette.

The colour specs are the syntax of X11's `XParseColor`, which is what
xterm reads. The two forms here are the hash form and "rgb:". The
tests for them live beside the ones for the sequences, because the two
are only useful together.
"""
import pytest

from ptterm.osc import (
    DEFAULT_COLORS,
    FIRST_SPECIAL_COLOR,
    PALETTE,
    SPECIAL_COLOR_NAMES,
    Color,
    parse_color,
)
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


@pytest.fixture
def pane():
    "A screen, the stream that feeds it, and what it writes back."
    responses = []
    screen = BetterScreen(24, 80, write_process_input=responses.append)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream, responses


# ----------------------------------------------------------------------
# The spec parser.


@pytest.mark.parametrize("spec, color", [
    # A hash spec pads each component with zeros on the right. "#fff"
    # is 0xf000 and not 0xffff, which is the trap in this form.
    ("#fff", Color(0xF0, 0xF0, 0xF0)),
    ("#888", Color(0x80, 0x80, 0x80)),
    ("#f0f0f0", Color(0xF0, 0xF0, 0xF0)),
    ("#aabbcc", Color(0xAA, 0xBB, 0xCC)),
    ("#f00f00f00", Color(0xF0, 0xF0, 0xF0)),
    ("#f000f000f000", Color(0xF0, 0xF0, 0xF0)),
    ("#aaaabbbbcccc", Color(0xAA, 0xBB, 0xCC)),
    # An "rgb:" spec scales instead, so one "f" is the full value.
    ("rgb:f/f/f", Color(0xFF, 0xFF, 0xFF)),
    ("rgb:f0f0/f0f0/f0f0", Color(0xF0, 0xF0, 0xF0)),
    ("rgb:80/00/00", Color(0x80, 0x00, 0x00)),
    ("rgb:FFFF/0000/0000", Color(0xFF, 0x00, 0x00)),
])
def test_a_spec_reads_as_the_colour_it_names(spec, color):
    assert parse_color(spec) == color


@pytest.mark.parametrize("spec", [
    "",
    "red",            # A name needs a colour database, which a pane has not.
    "#ff",            # Not divisible by three.
    "#fffff",         # Nor this one.
    "#fffffffffffff",  # Too many digits for the form.
    "#gggggg",        # Not hexadecimal.
    "rgb:f/f",        # Two components.
    "rgb:f/f/f/f",    # Four.
    "rgb:/f/f",       # One of them empty.
    "rgb:fffff/f/f",  # One of them too long.
    "rgbx:f/f/f",
])
def test_a_spec_that_x11_does_not_read_is_no_colour(spec):
    assert parse_color(spec) is None


def test_a_colour_writes_the_two_forms_that_a_terminal_sends():
    assert Color(0xAA, 0xBB, 0xCC).spec == "rgb:aaaa/bbbb/cccc"
    assert Color(0xAA, 0xBB, 0xCC).hex == "#aabbcc"


# ----------------------------------------------------------------------
# The palette, under "OSC 4".


def test_a_query_answers_the_default_before_anything_sets_it(pane):
    _screen, stream, responses = pane
    stream.feed("\x1b]4;1;?\x1b\\")
    assert responses == ["\x1b]4;1;%s\x1b\\" % PALETTE[1].spec]


def test_an_entry_reads_back_as_what_was_set(pane):
    _screen, stream, responses = pane
    stream.feed("\x1b]4;0;rgb:f0f0/f0f0/f0f0\x1b\\")
    stream.feed("\x1b]4;0;?\x1b\\")
    assert responses == ["\x1b]4;0;rgb:f0f0/f0f0/f0f0\x1b\\"]


def test_two_queries_come_back_as_two_answers(pane):
    # A program reads one answer for each question. Joining them into
    # one sequence leaves it reading the second answer as part of the
    # first, and every answer after that lands one place out of step.
    _screen, stream, responses = pane
    stream.feed("\x1b]4;0;rgb:f0f0/f0f0/f0f0;1;rgb:f0f0/0000/0000\x1b\\")
    stream.feed("\x1b]4;0;?;1;?\x1b\\")
    assert responses == [
        "\x1b]4;0;rgb:f0f0/f0f0/f0f0\x1b\\",
        "\x1b]4;1;rgb:f0f0/0000/0000\x1b\\",
    ]


def test_a_spec_that_does_not_read_leaves_the_entry_alone(pane):
    _screen, stream, responses = pane
    stream.feed("\x1b]4;0;bogus\x1b\\")
    stream.feed("\x1b]4;0;?\x1b\\")
    assert responses == ["\x1b]4;0;%s\x1b\\" % PALETTE[0].spec]


def test_an_index_past_the_table_answers_nothing(pane):
    # Nothing to answer, and no answer at all. A wrong answer would
    # put every answer after it one place out of step.
    _screen, stream, responses = pane
    stream.feed("\x1b]4;999;?\x1b\\")
    assert responses == []


# ----------------------------------------------------------------------
# Putting the palette back, under "OSC 104".


def test_a_reset_names_the_entry_to_put_back(pane):
    screen, stream, responses = pane
    stream.feed("\x1b]4;3;#aabbcc\x1b\\")
    stream.feed("\x1b]104;3\x1b\\")
    stream.feed("\x1b]4;3;?\x1b\\")
    assert responses == ["\x1b]4;3;%s\x1b\\" % PALETTE[3].spec]
    assert screen.palette_colors == {}


def test_a_reset_with_no_payload_puts_the_whole_palette_back(pane):
    screen, stream, _responses = pane
    stream.feed("\x1b]4;3;#aabbcc;9;#ddeeff\x1b\\")
    assert len(screen.palette_colors) == 2
    stream.feed("\x1b]104\x1b\\")
    assert screen.palette_colors == {}


def test_a_reset_of_the_palette_leaves_the_special_colours(pane):
    screen, stream, _responses = pane
    stream.feed("\x1b]5;0;#aabbcc\x1b\\")
    stream.feed("\x1b]104\x1b\\")
    assert screen.palette_colors == {FIRST_SPECIAL_COLOR: Color(0xAA, 0xBB, 0xCC)}


# ----------------------------------------------------------------------
# The special colours, under "OSC 5" and past the palette in "OSC 4".


def test_a_special_colour_answers_under_both_codes(pane):
    _screen, stream, responses = pane
    stream.feed("\x1b]5;0;rgb:8080/0000/0000\x1b\\")
    stream.feed("\x1b]5;0;?\x1b\\")
    stream.feed("\x1b]4;%i;?\x1b\\" % FIRST_SPECIAL_COLOR)
    assert responses == [
        "\x1b]5;0;rgb:8080/0000/0000\x1b\\",
        "\x1b]4;%i;rgb:8080/0000/0000\x1b\\" % FIRST_SPECIAL_COLOR,
    ]


def test_the_two_codes_reach_the_same_colour(pane):
    _screen, stream, responses = pane
    stream.feed("\x1b]4;%i;#aabbcc\x1b\\" % FIRST_SPECIAL_COLOR)
    stream.feed("\x1b]5;0;?\x1b\\")
    assert responses == ["\x1b]5;0;rgb:aaaa/bbbb/cccc\x1b\\"]


def test_a_special_colour_that_nobody_set_answers_the_text_colour(pane):
    _screen, stream, responses = pane
    stream.feed("\x1b]5;0;?\x1b\\")
    assert responses == ["\x1b]5;0;%s\x1b\\" % DEFAULT_COLORS["foreground"].spec]


def test_a_special_colour_past_the_last_one_answers_nothing(pane):
    _screen, stream, responses = pane
    stream.feed("\x1b]5;%i;?\x1b\\" % len(SPECIAL_COLOR_NAMES))
    assert responses == []


def test_a_special_reset_puts_one_colour_back(pane):
    screen, stream, _responses = pane
    stream.feed("\x1b]5;0;#aabbcc;1;#ddeeff\x1b\\")
    stream.feed("\x1b]105;0\x1b\\")
    assert screen.palette_colors == {
        FIRST_SPECIAL_COLOR + 1: Color(0xDD, 0xEE, 0xFF)
    }


def test_a_special_reset_with_no_payload_puts_them_all_back(pane):
    screen, stream, _responses = pane
    stream.feed("\x1b]4;3;#aabbcc\x1b\\")
    stream.feed("\x1b]5;0;#ddeeff\x1b\\")
    stream.feed("\x1b]105\x1b\\")
    # The palette entry stays: "OSC 105" covers the special colours.
    assert screen.palette_colors == {3: Color(0xAA, 0xBB, 0xCC)}


# ----------------------------------------------------------------------
# The dynamic colours, under "OSC 10" and the codes after it.


def test_a_dynamic_colour_reads_back_as_what_was_set(pane):
    _screen, stream, responses = pane
    stream.feed("\x1b]10;rgb:8080/8080/8080\x1b\\")
    stream.feed("\x1b]10;?\x1b\\")
    assert responses == ["\x1b]10;rgb:8080/8080/8080\x1b\\"]


def test_a_payload_with_two_values_walks_up_the_codes(pane):
    # "OSC 10" with two specs sets the foreground and the background.
    _screen, stream, responses = pane
    stream.feed("\x1b]10;rgb:f0f0/f0f0/f0f0;rgb:f0f0/0000/0000\x1b\\")
    stream.feed("\x1b]10;?;?\x1b\\")
    assert responses == [
        "\x1b]10;rgb:f0f0/f0f0/f0f0\x1b\\",
        "\x1b]11;rgb:f0f0/0000/0000\x1b\\",
    ]


def test_a_dynamic_reset_puts_the_colour_back(pane):
    _screen, stream, responses = pane
    stream.feed("\x1b]10;#aabbcc\x1b\\")
    stream.feed("\x1b]110\x1b\\")
    stream.feed("\x1b]10;?\x1b\\")
    assert responses == ["\x1b]10;%s\x1b\\" % DEFAULT_COLORS["foreground"].spec]


def test_the_kitty_query_reads_the_colour_that_was_set(pane):
    # One colour, two protocols. A program that sets with the xterm
    # sequence and reads with the kitty one gets what it set.
    _screen, stream, responses = pane
    stream.feed("\x1b]10;#aabbcc\x1b\\")
    stream.feed("\x1b]4;1;#ddeeff\x1b\\")
    stream.feed("\x1b]21;foreground=?;1=?\x1b\\")
    assert responses == [
        "\x1b]21;foreground=rgb:aaaa/bbbb/cccc;1=rgb:dddd/eeee/ffff\x1b\\"
    ]


# ----------------------------------------------------------------------
# What a reset of the terminal does.


def test_a_hard_reset_puts_every_colour_back(pane):
    screen, stream, _responses = pane
    stream.feed("\x1b]4;3;#aabbcc\x1b\\")
    stream.feed("\x1b]10;#ddeeff\x1b\\")
    stream.feed("\x1bc")
    assert screen.palette_colors == {}
    assert screen.dynamic_colors == {}
