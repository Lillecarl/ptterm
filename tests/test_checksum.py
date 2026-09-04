"""
DECRQCRA: the checksum of a rectangle of the screen.

A conformance suite reads the screen back with this, one cell at a
time, so it is the instrument that judges everything else. The answer
is "DCS Pid ! ~ xxxx ST", and the value is the negated sum of the
characters.
"""
import re

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def make_screen(lines=24, columns=80):
    "Return (screen, stream, responses)."
    responses = []
    screen = BetterScreen(lines, columns, write_process_input=responses.append)
    stream = BetterStream(screen)
    return screen, stream, responses


def checksum(stream, responses, request):
    "Ask for one checksum and return (identifier, the sum it stands for)."
    responses.clear()
    stream.feed(request)
    assert len(responses) == 1, responses
    found = re.match(r"\x1bP(\d+)!~([0-9A-F]{4})\x1b\\\Z", responses[0])
    assert found, repr(responses[0])
    # The terminal answers the negated sum. Undo that, the way a caller
    # does, so a test can say what it means.
    return int(found.group(1)), (0x10000 - int(found.group(2), 16)) & 0xFFFF


def test_one_cell():
    screen, stream, responses = make_screen()
    stream.feed("abc")
    assert checksum(stream, responses, "\x1b[7;0;1;1;1;1*y") == (7, ord("a"))


def test_a_rectangle_sums_its_cells():
    screen, stream, responses = make_screen()
    stream.feed("abc")
    identifier, total = checksum(stream, responses, "\x1b[1;0;1;1;1;3*y")
    assert (identifier, total) == (1, ord("a") + ord("b") + ord("c"))


def test_a_cell_nobody_wrote_counts_as_a_space():
    # The answer must never be "0000": a caller cannot tell that apart
    # from an answer that never came.
    screen, stream, responses = make_screen()
    assert checksum(stream, responses, "\x1b[1;0;5;5;5;5*y") == (1, ord(" "))


def test_the_rectangle_is_clamped_to_the_screen():
    screen, stream, responses = make_screen(lines=4, columns=4)
    stream.feed("ab")
    # Past the last line and the last column. The whole screen holds
    # "ab" and fourteen spaces.
    identifier, total = checksum(stream, responses, "\x1b[1;0;1;1;99;99*y")
    assert total == ord("a") + ord("b") + 14 * ord(" ")


def test_the_default_is_the_whole_screen():
    screen, stream, responses = make_screen(lines=2, columns=3)
    stream.feed("ab")
    identifier, total = checksum(stream, responses, "\x1b[1;0*y")
    assert total == ord("a") + ord("b") + 4 * ord(" ")


def test_it_reads_the_lines_the_user_sees():
    # The screen scrolls, so the first line of the buffer is no longer
    # the first line of the screen.
    screen, stream, responses = make_screen(lines=2, columns=4)
    stream.feed("a\r\nb\r\nc")
    identifier, total = checksum(stream, responses, "\x1b[1;0;1;1;1;1*y")
    assert total == ord("b")


def test_an_unknown_intermediate_does_not_leak_its_final_byte():
    # "CSI Ps ' }" is DECIC, which nothing here acts on. Reading the
    # "'" as the final byte would end the sequence there and draw the
    # "}" on the screen.
    screen, stream, responses = make_screen()
    stream.feed("\x1b[2'}hi")
    row = screen.pt_screen.data_buffer[0]
    assert "".join(row[i].char for i in range(2)) == "hi"
