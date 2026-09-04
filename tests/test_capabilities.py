"""
XTGETTCAP ("DCS + q <names> ST"): what this terminal can do.

A program that wants to know whether it may draw a curly underline has
two ways to find out. It can read the terminfo database of the machine
it runs on, which says what `TERM` names and may not have the entry at
all. Or it can ask the terminal, which always knows.

The second way is the only one that survives ssh, and it is what
modern programs use. The answer has to be true: a capability that is
claimed and not served is worse than one that is missing, because the
program stops asking and draws what the terminal cannot draw.
"""
import pytest

from ptterm.screen import CAPABILITIES, TERMINAL_NAME, BetterScreen
from ptterm.stream import BetterStream


def ask(names):
    "Ask for capabilities by name, and read the answers back."
    answers = []
    screen = BetterScreen(2, 10, write_process_input=answers.append)
    stream = BetterStream(screen)
    query = ";".join(name.encode("ascii").hex() for name in names)
    stream.feed("\x1bP+q" + query + "\x1b\\")
    return answers


def unwrap(answer):
    "The three parts of one answer: is it there, the name, the value."
    assert answer.startswith("\x1bP") and answer.endswith("\x1b\\")
    body = answer[2:-2]
    assert body[1:3] == "+r"
    known = body[0] == "1"
    rest = body[3:]
    name, _, value = rest.partition("=")
    return (
        known,
        bytes.fromhex(name).decode("ascii"),
        bytes.fromhex(value).decode("utf-8") if value else None,
    )


def test_the_name_of_the_entry():
    assert unwrap(ask(["TN"])[0]) == (True, "TN", TERMINAL_NAME)


def test_a_capability_that_is_only_there_or_not():
    assert unwrap(ask(["RGB"])[0]) == (True, "RGB", None)


def test_a_capability_that_carries_a_value():
    known, name, value = unwrap(ask(["Smulx"])[0])
    assert (known, name) == (True, "Smulx")
    assert value == r"\E[4:%p1%dm"


def test_a_capability_that_this_terminal_does_not_have():
    known, name, value = unwrap(ask(["kittykittybangbang"])[0])
    assert not known
    assert name == "kittykittybangbang"
    assert value is None


def test_one_answer_for_every_name_that_is_asked():
    names = ["TN", "RGB", "Smulx", "nope"]
    assert len(ask(names)) == len(names)
    assert [unwrap(answer)[1] for answer in ask(names)] == names


def test_a_name_that_is_not_hexadecimal():
    "Nothing is claimed for something that cannot be read."
    answers = []
    screen = BetterScreen(2, 10, write_process_input=answers.append)
    stream = BetterStream(screen)
    stream.feed("\x1bP+qzzzz\x1b\\")
    assert answers == ["\x1bP0+rzzzz\x1b\\"]


@pytest.mark.parametrize("name", sorted(CAPABILITIES))
def test_every_capability_answers(name):
    known, back, _ = unwrap(ask([name])[0])
    assert known
    assert back == name


def test_the_underline_capabilities_say_what_the_screen_draws():
    """
    "Smulx" and "Setulc" are the two that this terminal grew last, and
    a program only writes them when it reads them here.
    """
    assert CAPABILITIES["Su"] is True
    assert "4:%p1%d" in CAPABILITIES["Smulx"]
    assert "58:2:" in CAPABILITIES["Setulc"]
