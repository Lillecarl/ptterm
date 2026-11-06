"""
A sequence that never finishes must not wedge a pane.

A program can write a partial escape and then stop. The parser then
reads every later byte as part of that sequence, and the pane shows
the wrong screen for ever. `GroundTimer` bounds that. The rule is
pyte's; this checks the pane gives itself one. Lillecarl/pymux#390.
"""

from __future__ import annotations

import logging

from no_backend import NoBackend

from ptterm.control import TerminalControl

LINES = 4
COLUMNS = 20


def control():
    "A pane of a known size, with no program under it."
    made = TerminalControl(backend=NoBackend())
    made.create_content(COLUMNS, LINES)
    return made


def row_text(made, number):
    row = made.screen.page.data_buffer[number]
    return "".join(row[x].char for x in range(COLUMNS)).rstrip()


def test_a_pane_gives_its_parser_a_ground_timer():
    made = control()
    assert made._ground_timer.timeout == 5
    assert made.process.receive == made._read


def test_a_dangling_sequence_does_not_swallow_the_next_output(caplog):
    made = control()
    made.process.receive("abc\x1b[1;")
    assert made.stream.ground_timer_active

    made._ground_timer.since -= 5  # The timeout passed with no byte.
    with caplog.at_level(logging.WARNING, logger="ptterm"):
        made.process.receive("def")

    assert not made.stream.ground_timer_active
    assert row_text(made, 0) == "abcdef"
    # The drop is silent on the screen, so the log names it.
    # Lillecarl/pymux#935.
    (record,) = caplog.records
    assert "'\\x1b[1;'" in record.getMessage()
    assert "'def'" in record.getMessage()


def test_a_sequence_the_reader_cut_survives_a_late_read():
    """
    A read that filled its page cut the write, and the rest was already
    waiting. A server held up past the timeout then reads it late, and
    the program never stopped: the sequence stands. On a live pane the
    dropped `ESC[` left `1;3H` drawn as text. Lillecarl/pymux#935.
    """
    made = control()
    made.process.backend.more_is_waiting = True
    made.process.receive("abc\x1b[2;")
    made.process.backend.more_is_waiting = False

    made._ground_timer.since -= 6  # The server stalled.
    made.process.receive("3Hx")

    assert row_text(made, 0) == "abc"
    assert row_text(made, 1) == "  x"


def test_a_sequence_still_arriving_is_not_dropped_early():
    made = control()
    made.process.receive("abc\x1b[1;")
    made.process.receive("5m")  # Within the timeout, so it stands.

    assert not made.stream.ground_timer_active
    assert row_text(made, 0) == "abc"
