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
