"""
Tests for the queries that a program in a pane sends.

A program that asks and gets no answer waits. Every query that ptterm
understands therefore gets an answer, and one that it does not
understand gets the answer that says so.
"""
import pytest

from ptterm.screen import TERMINAL_VERSION, BetterScreen
from ptterm.stream import BetterStream


def make_screen(lines=24, columns=80):
    answers = []
    screen = BetterScreen(lines, columns, write_process_input=answers.append)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream, answers


# ----------------------------------------------------------------------
# XTVERSION.


def test_the_version_query_names_the_terminal():
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[>q")
    assert answers == ["\x1bP>|%s\x1b\\" % TERMINAL_VERSION]


def test_the_version_query_takes_a_parameter():
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[>0q")
    assert answers == ["\x1bP>|%s\x1b\\" % TERMINAL_VERSION]


@pytest.mark.parametrize("sequence", ["\x1b[q", "\x1b[2q", "\x1b[?q", "\x1b[ q"])
def test_another_q_sequence_is_not_the_version_query(sequence):
    "DECLL and DECSCUSR share the final byte, and answer nothing."
    _screen, stream, answers = make_screen()
    stream.feed(sequence)
    assert answers == []


# ----------------------------------------------------------------------
# DECRQM.


def query_mode(stream, number, private=True):
    stream.feed("\x1b[%s%i$p" % ("?" if private else "", number))


def test_a_mode_that_is_set_reports_one():
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[?2004h")  # Bracketed paste on.
    query_mode(stream, 2004)
    assert answers == ["\x1b[?2004;1$y"]


def test_a_mode_that_is_reset_reports_two():
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[?2004h\x1b[?2004l")
    query_mode(stream, 2004)
    assert answers == ["\x1b[?2004;2$y"]


def test_a_mode_that_was_never_set_reports_two():
    _screen, stream, answers = make_screen()
    query_mode(stream, 1000)
    assert answers == ["\x1b[?1000;2$y"]


def test_a_mode_that_is_on_by_default_reports_one():
    "Autowrap and the visible cursor start enabled."
    _screen, stream, answers = make_screen()
    query_mode(stream, 7)
    query_mode(stream, 25)
    assert answers == ["\x1b[?7;1$y", "\x1b[?25;1$y"]


def test_a_mode_that_the_screen_does_not_act_on_reports_zero():
    "A program that reads zero falls back, instead of trusting us."
    _screen, stream, answers = make_screen()
    query_mode(stream, 1003)  # Any-event mouse tracking.
    query_mode(stream, 9999)
    assert answers == ["\x1b[?1003;0$y", "\x1b[?9999;0$y"]


def test_setting_a_mode_that_we_do_not_act_on_still_reports_zero():
    "The set holds every mode, but the answer says what we serve."
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[?1003h")
    query_mode(stream, 1003)
    assert answers == ["\x1b[?1003;0$y"]


def test_the_alternate_screen_mode_is_reported():
    _screen, stream, answers = make_screen()
    query_mode(stream, 1049)
    stream.feed("\x1b[?1049h")
    query_mode(stream, 1049)
    assert answers == ["\x1b[?1049;2$y", "\x1b[?1049;1$y"]


def test_a_mode_without_a_private_marker_is_answered_without_one():
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[4h")  # IRM: insert mode.
    query_mode(stream, 4, private=False)
    query_mode(stream, 20, private=False)  # LNM: never set.
    query_mode(stream, 4, private=True)  # Not the same mode.
    assert answers == ["\x1b[4;1$y", "\x1b[20;2$y", "\x1b[?4;0$y"]


def test_the_query_does_not_change_the_mode():
    screen, stream, _answers = make_screen()
    before = set(screen.mode)
    query_mode(stream, 2004)
    query_mode(stream, 4, private=False)
    assert screen.mode == before


# ----------------------------------------------------------------------
# DECRQSS.


def request_setting(stream, name):
    stream.feed("\x1bP$q%s\x1b\\" % name)


def test_the_rendition_of_a_fresh_screen_is_plain():
    _screen, stream, answers = make_screen()
    request_setting(stream, "m")
    assert answers == ["\x1bP1$r0m\x1b\\"]


def test_the_rendition_reports_the_attributes():
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[1;3;4;7m")
    request_setting(stream, "m")
    assert answers == ["\x1bP1$r0;1;3;4;7m\x1b\\"]


def test_the_rendition_reports_a_24_bit_colour():
    "A program that probes for 24 bit colour reads its own colour back."
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[38;2;1;2;3m")
    request_setting(stream, "m")
    assert answers == ["\x1bP1$r0;38;2;1;2;3m\x1b\\"]


def test_a_colour_by_index_comes_back_as_its_components():
    "The screen keeps the colour, not the index it was named with."
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[48;5;196m")
    request_setting(stream, "m")
    assert answers == ["\x1bP1$r0;48;2;255;0;0m\x1b\\"]


def test_a_reset_clears_the_rendition():
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[1;38;2;1;2;3m\x1b[0m")
    request_setting(stream, "m")
    assert answers == ["\x1bP1$r0m\x1b\\"]


def test_the_cursor_style_comes_back():
    _screen, stream, answers = make_screen()
    request_setting(stream, " q")
    stream.feed("\x1b[4 q")  # A steady underline.
    request_setting(stream, " q")
    assert answers == ["\x1bP1$r1 q\x1b\\", "\x1bP1$r4 q\x1b\\"]


def test_the_cursor_style_zero_is_the_default():
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[6 q\x1b[0 q")
    request_setting(stream, " q")
    assert answers == ["\x1bP1$r1 q\x1b\\"]


def test_a_cursor_style_out_of_range_is_ignored():
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[4 q\x1b[9 q")
    request_setting(stream, " q")
    assert answers == ["\x1bP1$r4 q\x1b\\"]


def test_the_margins_come_back():
    _screen, stream, answers = make_screen(lines=24)
    request_setting(stream, "r")
    stream.feed("\x1b[3;10r")
    request_setting(stream, "r")
    assert answers == ["\x1bP1$r1;24r\x1b\\", "\x1bP1$r3;10r\x1b\\"]


def test_a_setting_that_the_screen_does_not_keep_is_refused():
    _screen, stream, answers = make_screen()
    request_setting(stream, "|")  # DECSCPP: the column count.
    request_setting(stream, "")
    assert answers == ["\x1bP0$r\x1b\\", "\x1bP0$r\x1b\\"]


def test_a_sixel_image_is_still_decoded():
    "DECRQSS shares the DCS entry point with the images."
    screen, stream, answers = make_screen()
    stream.feed('\x1bP0;0;0q"1;1;6;6#4;2;100;0;0#4!6~\x1b\\')
    assert answers == []
    assert len(screen.graphics.placements) == 1
