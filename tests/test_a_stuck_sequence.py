"""
A sequence that never finishes must not wedge a pane.

A program can write a partial escape and then stop. The parser then
reads every later byte as part of that sequence, and the pane shows
the wrong screen for ever. `GroundTimer` bounds that. The rule is
pyte's; this checks the pane gives itself one. Lillecarl/pymux#390.
"""

from __future__ import annotations

from no_backend import NoBackend

from ptterm.terminal import _TerminalControl

LINES = 4
COLUMNS = 20


def control():
    "A pane of a known size, with no program under it."
    made = _TerminalControl(backend=NoBackend())
    made.create_content(COLUMNS, LINES)
    return made


def row_text(made, number):
    row = made.screen.page.data_buffer[number]
    return "".join(row[x].char for x in range(COLUMNS)).rstrip()


def test_a_pane_gives_its_parser_a_ground_timer():
    made = control()
    assert made._ground_timer.timeout == 5
    assert made.process.receive == made._ground_timer.feed


def test_a_dangling_sequence_does_not_swallow_the_next_output():
    made = control()
    made.process.receive("abc\x1b[1;")
    assert made.stream.ground_timer_active

    made._ground_timer.since -= 5  # The timeout passed with no byte.
    made.process.receive("def")

    assert not made.stream.ground_timer_active
    assert row_text(made, 0) == "abcdef"


def test_a_sequence_still_arriving_is_not_dropped_early():
    made = control()
    made.process.receive("abc\x1b[1;")
    made.process.receive("5m")  # Within the timeout, so it stands.

    assert not made.stream.ground_timer_active
    assert row_text(made, 0) == "abc"
