"""
A sequence that never finishes must not wedge a pane.

A program can write a partial escape and then stop. The parser then
reads every later byte as part of that sequence, and the pane shows
the wrong screen for ever. A pane gives its parser a five second
ground timer: the next bytes after that drop the unfinished sequence.
Lillecarl/pymux#390.
"""

import asyncio

import pytest

from no_backend import NoBackend
from ptterm.terminal import _TerminalControl

LINES = 4
COLUMNS = 20


@pytest.fixture(autouse=True)
def _a_loop():
    "`Process` reads the running event loop, and pytest starts none."
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    asyncio.set_event_loop(None)
    loop.close()


def control():
    "A pane of a known size, with no program under it."
    made = _TerminalControl(backend=NoBackend())
    made.create_content(COLUMNS, LINES)
    return made


def row_text(made, number):
    row = made.screen.page.data_buffer[number]
    return "".join(row[x].char for x in range(COLUMNS)).rstrip()


def test_a_dangling_sequence_does_not_swallow_the_next_output():
    made = control()
    made.process.receive("abc\x1b[1;")
    assert made.stream.ground_timer_active

    made._blocked_since -= 5  # The timeout passed with no byte.
    made.process.receive("def")

    assert not made.stream.ground_timer_active
    assert row_text(made, 0) == "abcdef"


def test_a_sequence_still_arriving_is_not_dropped_early():
    made = control()
    made.process.receive("abc\x1b[1;")
    made.process.receive("5m")  # Within the timeout, so it stands.

    assert not made.stream.ground_timer_active
    assert row_text(made, 0) == "abc"
