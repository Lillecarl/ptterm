"""
The form of a C1 control that a reply carries.

Every C1 control has two spellings. Seven bits is `ESC` and a letter,
and eight bits is the single byte 0x40 above that letter: `CSI` is
`ESC [` or 0x9b. S8C1T ("ESC SP G") picks the second, S7C1T
("ESC SP F") picks the first, and DECSCL sets the same thing.

The mode exists so that a program can parse an answer without the
escape. It only works when it reaches every control the terminal
writes, which is why one helper spells all of them.

An eight bit control is a byte and not a character, so UTF-8 has no
spelling for it. It travels as a surrogate, and the backend encodes it
back with "surrogateescape". These tests read the wire, not the string.

libvterm's `26state_query.test` line 62 asks the same question.
Lillecarl/pymux#94.
"""
import pytest

from pyte.screen import TERMINAL_VERSION, Screen
from pyte.streams import Stream

#: "ESC SP G", which turns eight bit controls on.
S8C1T = "\x1b G"

#: "ESC SP F", which turns them off again.
S7C1T = "\x1b F"


def make_screen(lines=24, columns=80):
    answers = []
    screen = Screen(lines, columns, write_process_input=answers.append)
    stream = Stream(screen)
    return screen, stream, answers


def wire(answers) -> bytes:
    "The bytes that reach the program, the way the backend writes them."
    return "".join(answers).encode("utf-8", "surrogateescape")


def answered(data: str) -> bytes:
    "What the terminal writes back for `data`."
    _screen, stream, answers = make_screen()
    stream.feed(data)
    return wire(answers)


# ----------------------------------------------------------------------
# The mode itself.


def test_seven_bit_controls_is_where_a_terminal_starts():
    screen, _stream, _answers = make_screen()
    assert screen.seven_bit_controls is True


def test_s8c1t_turns_the_mode_on():
    screen, stream, _answers = make_screen()
    stream.feed(S8C1T)
    assert screen.seven_bit_controls is False


def test_s7c1t_turns_the_mode_off_again():
    screen, stream, _answers = make_screen()
    stream.feed(S8C1T + S7C1T)
    assert screen.seven_bit_controls is True


def test_an_announcer_draws_nothing():
    """
    The space is an intermediate byte. A stream that stops at it puts
    the "G" on the screen as text.
    """
    screen, stream, _answers = make_screen()
    stream.feed(S8C1T + S7C1T)
    assert screen.page.data_buffer[0] == {}


def test_a_reset_puts_seven_bit_controls_back():
    screen, stream, _answers = make_screen()
    stream.feed(S8C1T + "\x1bc")
    assert screen.seven_bit_controls is True


# ----------------------------------------------------------------------
# DECSCL says the same thing.


@pytest.mark.parametrize("parameter", [0, 2])
def test_decscl_asks_for_eight_bit_controls(parameter):
    "xterm's ctlseqs.txt: 0 and 2 both name eight bit controls."
    screen, stream, _answers = make_screen()
    stream.feed('\x1b[62;%i"p' % parameter)
    assert screen.seven_bit_controls is False


def test_decscl_asks_for_seven_bit_controls():
    "1 is the DEC factory default."
    screen, stream, _answers = make_screen()
    stream.feed(S8C1T + '\x1b[62;1"p')
    assert screen.seven_bit_controls is True


def test_level_one_ignores_the_second_parameter():
    "ctlseqs.txt says the parameter is ignored in conformance level 1."
    screen, stream, _answers = make_screen()
    stream.feed('\x1b[61;0"p')
    assert screen.seven_bit_controls is True


def test_decscl_with_no_second_parameter_changes_nothing():
    screen, stream, _answers = make_screen()
    stream.feed(S8C1T + '\x1b[62"p')
    assert screen.seven_bit_controls is False


def test_decrqss_reports_the_form_that_is_on():
    "The report names 1 for seven bit and 2 for eight."
    assert answered('\x1b[62;1"p\x1bP$q"p\x1b\\') == b'\x1bP1$r62;1"p\x1b\\'
    assert answered('\x1b[62;0"p\x1bP$q"p\x1b\\') == b'\x901$r62;2"p\x9c'


# ----------------------------------------------------------------------
# Every control the terminal writes.


def test_a_control_sequence_carries_one_byte():
    'DSR ("CSI 5 n"), which is what libvterm asks.'
    assert answered(S8C1T + "\x1b[5n") == b"\x9b0n"


def test_a_control_sequence_stays_two_bytes_without_the_mode():
    assert answered("\x1b[5n") == b"\x1b[0n"


def test_a_device_control_string_carries_two_bytes():
    "DCS opens it and ST closes it, and both are C1 controls."
    answer = answered(S8C1T + "\x1b[>q")
    assert answer == b"\x90>|" + TERMINAL_VERSION.encode("utf-8") + b"\x9c"


def test_an_operating_system_command_carries_two_bytes():
    "The window title, which OSC asks for and ST closes."
    assert answered(S8C1T + "\x1b]0;hi\x1b\\\x1b[21t") == b"\x9dlhi\x9c"


def test_the_answer_of_a_table_carries_one_byte():
    """
    `_DEVICE_STATUS_ANSWERS` is a table of literals, and it holds the
    body of each answer without the control in front of it.
    """
    assert answered(S8C1T + "\x1b[?15n") == b"\x9b?13n"


def test_the_position_report_carries_one_byte():
    assert answered(S8C1T + "\x1b[3;4H\x1b[6n") == b"\x9b3;4R"


def test_the_device_attributes_carry_one_byte():
    assert answered(S8C1T + "\x1b[>c") == b"\x9b>64;383;0c"


# ----------------------------------------------------------------------
# The mode reaches the wire and not only the string.


def test_the_byte_is_one_byte_and_not_two():
    """
    UTF-8 spells 0x9b as two bytes, and no program reads that. The
    surrogate is what keeps it one.
    """
    _screen, stream, answers = make_screen()
    stream.feed(S8C1T + "\x1b[5n")
    assert len(wire(answers)) == 3
    assert "".join(answers).encode("utf-8", "replace") != b"\x9b0n"
