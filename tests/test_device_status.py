"""
What "CSI Ps n" and "CSI ? Ps n" answer.

DSR asks the terminal about itself. Most of the questions are about a
part that a pane does not have: a printer, a keyboard, a locator, a
macro store. Each of those has a legal answer that says "no", and a
terminal has to give it.

A query with no answer is worse than a wrong answer. The program waits
for one, and every answer after it arrives one place out of step. That
is why the whole class of these tests failed while only some of them
were missing.
"""
import pytest

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def _screen(lines=8, columns=20):
    answers = []
    screen = BetterScreen(lines, columns, write_process_input=answers.append)
    stream = BetterStream(screen)
    return screen, stream, answers


@pytest.mark.parametrize(
    "query, answer",
    [
        # DSRPrinterPort: no printer.
        ("\x1b[?15n", "\x1b[?13n"),
        # DSRUDKLocked: the user defined keys are unlocked.
        ("\x1b[?25n", "\x1b[?20n"),
        # DSRKeyboard: North American, ready, a PC keyboard.
        ("\x1b[?26n", "\x1b[?27;1;0;5n"),
        # DSRLocatorStatus: no locator.
        ("\x1b[?55n", "\x1b[?50n"),
        # DSRLocatorId: the kind of locator is not known.
        ("\x1b[?56n", "\x1b[?57;0n"),
        # DECMSR: no room for a macro. This answer carries no private
        # marker, and ends with "* {".
        ("\x1b[?62n", "\x1b[0*{"),
        # DSRDataIntegrity: no error since the last report.
        ("\x1b[?75n", "\x1b[?70n"),
        # DSRMultipleSessionStatus: one session.
        ("\x1b[?85n", "\x1b[?83n"),
    ],
)
def test_a_part_that_is_not_here_still_answers(query, answer):
    _screen_, stream, answers = _screen()
    stream.feed(query)
    assert answers == [answer]


def test_the_checksum_of_the_macros_is_zero():
    "DECCKSR carries the number of the request back with the answer."
    _screen_, stream, answers = _screen()
    stream.feed("\x1b[?63;123n")
    assert answers == ["\x1bP123!~0000\x1b\\"]


def test_the_terminal_says_it_is_well():
    _screen_, stream, answers = _screen()
    stream.feed("\x1b[5n")
    assert answers == ["\x1b[0n"]


def test_the_cursor_position_comes_back():
    _screen_, stream, answers = _screen()
    stream.feed("\x1b[6;5H\x1b[6n")
    assert answers == ["\x1b[6;5R"]


def test_the_page_number_follows_the_position():
    "DECXCPR ('CSI ? 6 n') adds the page, and a pane holds one page."
    _screen_, stream, answers = _screen()
    stream.feed("\x1b[6;5H\x1b[?6n")
    assert answers == ["\x1b[?6;5;1R"]


def test_a_report_nobody_knows_is_left_alone():
    "An answer to a question ptterm does not know would be a wrong answer."
    _screen_, stream, answers = _screen()
    stream.feed("\x1b[?4242n")
    assert answers == []
