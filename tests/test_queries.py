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
    # Private mode 4 is DECSCLM, the slow scroll. It is a different
    # mode from IRM, and the marker is the only thing that says so.
    query_mode(stream, 4, private=True)
    assert answers == ["\x1b[4;1$y", "\x1b[20;2$y", "\x1b[?4;2$y"]


def test_a_mode_that_can_never_be_on_reports_four():
    """
    The ANSI modes that no terminal implements.

    Four reads as "permanently reset". It says the mode exists and can
    never be on, which is what a program needs to stop asking. A zero
    would say "I never heard of this", and the program would guess.
    """
    _screen, stream, answers = make_screen()
    query_mode(stream, 1, private=False)  # GATM.
    query_mode(stream, 19, private=False)  # EBM.
    query_mode(stream, 60)  # DECHCCM.
    assert answers == ["\x1b[1;4$y", "\x1b[19;4$y", "\x1b[?60;4$y"]


def test_setting_a_mode_that_can_never_be_on_changes_no_answer():
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[1h")  # GATM on, which does nothing.
    query_mode(stream, 1, private=False)
    assert answers == ["\x1b[1;4$y"]


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


# ----------------------------------------------------------------------
# The size in band (private mode 2048).


from ptterm.graphics import ASSUMED_CELL_HEIGHT, ASSUMED_CELL_WIDTH  # noqa: E402


def resize_report(lines, columns):
    return "\x1b[48;%i;%i;%i;%it" % (
        lines,
        columns,
        lines * ASSUMED_CELL_HEIGHT,
        columns * ASSUMED_CELL_WIDTH,
    )


def test_setting_the_mode_reports_the_size_at_once():
    "A program need not ask separately for the size it just subscribed to."
    _screen, stream, answers = make_screen(lines=24, columns=80)
    stream.feed("\x1b[?2048h")
    assert answers == [resize_report(24, 80)]


def test_setting_the_mode_again_reports_again():
    _screen, stream, answers = make_screen()
    stream.feed("\x1b[?2048h\x1b[?2048h")
    assert len(answers) == 2


def test_a_resize_reports_the_new_size():
    screen, stream, answers = make_screen(lines=24, columns=80)
    stream.feed("\x1b[?2048h")
    del answers[:]
    screen.resize(lines=10, columns=40)
    assert answers == [resize_report(10, 40)]


def test_a_resize_without_the_mode_reports_nothing():
    "SIGWINCH is the only report until a program asks for the other one."
    screen, _stream, answers = make_screen(lines=24, columns=80)
    screen.resize(lines=10, columns=40)
    assert answers == []


def test_a_resize_to_the_same_size_reports_nothing():
    screen, stream, answers = make_screen(lines=24, columns=80)
    stream.feed("\x1b[?2048h")
    del answers[:]
    screen.resize(lines=24, columns=80)
    assert answers == []


def test_resetting_the_mode_stops_the_reports():
    screen, stream, answers = make_screen(lines=24, columns=80)
    stream.feed("\x1b[?2048h\x1b[?2048l")
    del answers[:]
    screen.resize(lines=10, columns=40)
    assert answers == []


def test_the_mode_is_answered_by_a_mode_query():
    _screen, stream, answers = make_screen()
    query_mode(stream, 2048)
    stream.feed("\x1b[?2048h")
    del answers[:]
    query_mode(stream, 2048)
    assert answers == ["\x1b[?2048;1$y"]


def test_the_pixel_size_agrees_with_the_window_report():
    "Both sides count the same cell, so an image covers the same cells."
    _screen, stream, answers = make_screen(lines=24, columns=80)
    stream.feed("\x1b[?2048h")
    stream.feed("\x1b[14t")  # The text area, in pixels.
    report = answers[0]
    _rows, _cols, height, width = report[len("\x1b[48;") : -1].split(";")
    assert answers[1] == "\x1b[4;%s;%st" % (height, width)


def test_a_mode_that_is_kept_and_not_acted_on_reports_one_or_two():
    """
    A mode this screen keeps, and does nothing about.

    DECSCLM asks for a slow scroll, and a pane draws as fast as it can.
    DECPFF and DECPEX are about a printer that is not there. A program
    still writes one and reads it back, to learn whether the terminal
    took it, and an answer of zero sends that program to a guess.

    So the answer follows the mode: one after a set, two after a reset.
    xterm keeps every one of these the same way.
    """
    _screen, stream, answers = make_screen()
    for mode in (4, 18, 19, 35, 42, 66, 67):
        stream.feed("\x1b[?%ih" % mode)
        query_mode(stream, mode)
        stream.feed("\x1b[?%il" % mode)
        query_mode(stream, mode)

    expected = []
    for mode in (4, 18, 19, 35, 42, 66, 67):
        expected += ["\x1b[?%i;1$y" % mode, "\x1b[?%i;2$y" % mode]
    assert answers == expected


def test_the_two_ansi_modes_that_are_kept_report_one_or_two():
    "KAM locks the keyboard and SRM echoes it. Neither is acted on yet."
    _screen, stream, answers = make_screen()
    for mode in (2, 12):
        stream.feed("\x1b[%ih" % mode)
        query_mode(stream, mode, private=False)
        stream.feed("\x1b[%il" % mode)
        query_mode(stream, mode, private=False)
    assert answers == [
        "\x1b[2;1$y",
        "\x1b[2;2$y",
        "\x1b[12;1$y",
        "\x1b[12;2$y",
    ]
