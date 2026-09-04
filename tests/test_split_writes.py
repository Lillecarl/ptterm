"""
A sequence that arrives in two reads draws the same screen.

A pty hands over what it has when it has it. A program that writes
"CSI 1 ; 3 1 m" in one call may still reach the terminal as "CSI 1"
and ";31m", because the two sides run at their own speed. The parser
holds its state between reads, and this is the check on that.

The comparison needs no other emulator: the screen of one feed against
the screen of many is a property of ptterm alone.
"""
import pathlib

import pytest

from kitty_oracle import ptterm_cells, ptterm_cells_in_pieces

CORPUS = pathlib.Path(__file__).parent / "corpus"

#: The sizes to cut a stream into. One character at a time is the
#: hardest: every sequence arrives in as many pieces as it has
#: characters.
SIZES = [1, 2, 3, 7, 17, 250]

#: Sequences that hold something a parser keeps state for.
PROGRAMS = [
    "\x1b[1;31mred\x1b[0m",
    "\x1b[38;2;10;20;30mtruecolor",
    "\x1b[38:2::10:20:30mcolons",
    "\x1b]0;a title\x07after",
    "\x1b]8;;https://example.com/a\x1b\\link\x1b]8;;\x1b\\",
    "\x1bP0;0;0q#0;2;0;0;0#0~~\x1b\\",
    "\x1b_Ga=T,f=24,s=1,v=1;AAAA\x1b\\",
    "\x1b[?1049h\x1b[2J\x1b[HX\x1b[?1049l",
    "\x1b#8\x1b[2;4r\x1b[?6h",
    "你好\x1b[1D世界",
    "\x1b(0lqk\x1b(B",
    "\x1b[4:3;58:2::255:0:0munderlined",
]


def in_pieces(data, size):
    return [data[at : at + size] for at in range(0, len(data), size)]


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("data", PROGRAMS, ids=range(len(PROGRAMS)))
def test_a_sequence_survives_a_split(data, size):
    whole = ptterm_cells(data, 6, 20)
    assert ptterm_cells_in_pieces(in_pieces(data, size), 6, 20) == whole


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize(
    "name", sorted(path.name for path in CORPUS.glob("*.bin"))
)
def test_a_real_program_survives_a_split(name, size):
    data = (CORPUS / name).read_bytes().decode("utf-8", "replace")
    whole = ptterm_cells(data, 24, 80)
    assert ptterm_cells_in_pieces(in_pieces(data, size), 24, 80) == whole
