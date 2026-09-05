"""
DA and DA2: what the terminal can do, and what it is.

They are two questions, not one, and they take differently shaped
answers. A program tells them apart by the prefix of the reply.
"""
import pytest

from ptterm.screen import (
    DEVICE_EXTENSIONS,
    XTERM_PATCH_LEVEL,
    XTERM_TYPE,
    BetterScreen,
    ConformanceLevel,
    DeviceExtension,
)
from ptterm.stream import BetterStream


@pytest.fixture
def pane():
    responses = []
    screen = BetterScreen(24, 80, write_process_input=responses.append)
    return screen, BetterStream(screen), responses


# ----------------------------------------------------------------------
# The two questions.


@pytest.mark.parametrize("sequence", ["\x1b[c", "\x1b[0c"])
def test_da_answers_the_level_and_the_extensions(pane, sequence):
    _screen, stream, responses = pane
    stream.feed(sequence)
    assert responses == [
        "\x1b[?%i;%sc"
        % (
            ConformanceLevel.VT500,
            ";".join(str(one) for one in DEVICE_EXTENSIONS),
        )
    ]


@pytest.mark.parametrize("sequence", ["\x1b[>c", "\x1b[>0c"])
def test_da2_answers_the_type_and_the_firmware(pane, sequence):
    _screen, stream, responses = pane
    stream.feed(sequence)
    assert responses == ["\x1b[>%i;%i;0c" % (XTERM_TYPE, XTERM_PATCH_LEVEL)]


def test_the_two_answers_carry_different_prefixes(pane):
    # A program reads the prefix to tell one answer from the other. A
    # DA that answers in the DA2 shape is read as a DA2 reply, and
    # every answer after it lands one place out of step.
    _screen, stream, responses = pane
    stream.feed("\x1b[c\x1b[>c")
    assert responses[0].startswith("\x1b[?")
    assert responses[1].startswith("\x1b[>")


def test_da_names_nothing_that_a_pane_cannot_do(pane):
    # A capability that is claimed and not served is worse than one
    # that is missing: the program stops asking and draws what the
    # pane cannot draw.
    for absent in (
        DeviceExtension.PRINTER,
        DeviceExtension.LOCATOR_PORT,
        DeviceExtension.USER_WINDOWS,
        DeviceExtension.ANSI_TEXT_LOCATOR,
    ):
        assert absent not in DEVICE_EXTENSIONS


def test_a_da_with_a_parameter_that_is_not_zero_is_ignored(pane):
    _screen, stream, responses = pane
    stream.feed("\x1b[1c")
    assert responses == []




def test_decid_answers_the_way_da_answers(pane):
    """
    DECID ("ESC Z") is the older way to ask what DA asks.

    A VT100 had it and xterm keeps it, so a program written for one
    still gets an answer. esctest2 asks for it in
    `DECIDTests.test_DECID_Basic`.
    """
    _screen, stream, responses = pane
    stream.feed("\x1bZ")
    first = responses[:]
    responses.clear()
    stream.feed("\x1b[c")
    assert first == responses
    assert first[0].startswith("\x1b[?")
