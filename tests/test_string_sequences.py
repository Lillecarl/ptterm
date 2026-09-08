"""
The sequences that carry a string, checked against kitty.

OSC, DCS, APC, PM and SOS all hold a payload that ends at a string
terminator. None of them writes a cell. What matters is that the parser
eats the whole payload: a payload that leaks writes text on the screen
that the program never meant to show.
"""
import pytest

from kitty_oracle import differences, kitty_is_available
from pyte import escape
from pyte.sequences import csi
from pyte.osc import Osc
from pyte.sequences import Terminator, apc, dcs, osc

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)

#: A sequence of each kind, with a payload that has to stay invisible.
SEQUENCES = [
    osc("0", "a title", end=Terminator.BEL),  # The title, ended by a bell.
    osc("0", "a title"),  # The same, ended by a string terminator.
    osc("2", "a title"),
    osc(Osc.PALETTE_COLOR, "1", "?"),  # A palette query.
    osc(Osc.HYPERLINK, "", "http://example.com"),  # A hyperlink.
    osc(Osc.CLIPBOARD, "c", "aGVsbG8=", end=Terminator.BEL),  # A clipboard write.
    osc(Osc.NOTIFICATION, "i=1", "done"),  # A notification.
    osc("30001", "whatever"),  # A code that nobody answers.
    dcs("1$r0m"),  # DCS.
    dcs("q#0;2;0;0;0"),  # DCS with a sixel payload.
    apc("Ga=T,f=24"),  # APC, the graphics protocol.
    "\x1b^a private message\x1b\\",  # PM.
    "\x1bXa start of string\x1b\\",  # SOS.
]


@pytest.mark.parametrize("sequence", SEQUENCES)
def test_a_string_sequence_writes_no_cell(sequence):
    assert not differences(sequence, lines=4, columns=12)


@pytest.mark.parametrize("sequence", SEQUENCES)
def test_the_text_after_a_string_sequence_lands_on_the_screen(sequence):
    "The payload ends where the terminator says, and not later."
    assert not differences(sequence + "abc", lines=4, columns=12)


@pytest.mark.parametrize("sequence", SEQUENCES)
def test_a_string_sequence_between_two_words(sequence):
    assert not differences("ab" + sequence + "cd", lines=4, columns=12)


@pytest.mark.parametrize("sequence", SEQUENCES)
def test_a_string_sequence_does_not_move_the_cursor(sequence):
    assert not differences((
        "abc"
        + csi(escape.CUP, 1, 2)
    ) + sequence + "X", lines=4, columns=12)


def test_a_payload_that_holds_a_semicolon():
    assert not differences((
        osc(Osc.NOTIFICATION, "i=1", "a", "b", "c")
        + "X"
    ), lines=4, columns=12)


def test_an_empty_payload():
    assert not differences(osc("0", "", end=Terminator.BEL) + "X", lines=4, columns=12)
