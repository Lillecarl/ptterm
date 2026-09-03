"""
The sequences that carry a string, checked against kitty.

OSC, DCS, APC, PM and SOS all hold a payload that ends at a string
terminator. None of them writes a cell. What matters is that the parser
eats the whole payload: a payload that leaks writes text on the screen
that the program never meant to show.
"""
import pytest

from kitty_oracle import differences, kitty_is_available

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)

#: A sequence of each kind, with a payload that has to stay invisible.
SEQUENCES = [
    "\x1b]0;a title\x07",  # The title, ended by a bell.
    "\x1b]0;a title\x1b\\",  # The same, ended by a string terminator.
    "\x1b]2;a title\x1b\\",
    "\x1b]4;1;?\x1b\\",  # A palette query.
    "\x1b]8;;http://example.com\x1b\\",  # A hyperlink.
    "\x1b]52;c;aGVsbG8=\x07",  # A clipboard write.
    "\x1b]99;i=1;done\x1b\\",  # A notification.
    "\x1b]30001;whatever\x1b\\",  # A code that nobody answers.
    "\x1bP1$r0m\x1b\\",  # DCS.
    "\x1bPq#0;2;0;0;0\x1b\\",  # DCS with a sixel payload.
    "\x1b_Ga=T,f=24\x1b\\",  # APC, the graphics protocol.
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
    assert not differences("abc\x1b[1;2H" + sequence + "X", lines=4, columns=12)


def test_a_payload_that_holds_a_semicolon():
    assert not differences("\x1b]99;i=1;a;b;c\x1b\\X", lines=4, columns=12)


def test_an_empty_payload():
    assert not differences("\x1b]0;\x07X", lines=4, columns=12)
