"""
A sequence that never finishes must not wedge a pane.

A program can write a partial escape and then stop. The parser then
reads every later byte as part of that sequence, and the pane shows
the wrong screen for ever. `GroundTimer` bounds that. The rule is
pyte's; this checks the pane gives itself one. Lillecarl/pymux#390.

**The tests that time it fork.** A stalled loop is only a stall when a
real program keeps writing behind it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from no_backend import NoBackend

from ptterm.control import TerminalControl
from ptterm.program import create_backend

LINES = 4
COLUMNS = 20

#: A ground timeout short enough for a test, and the program's pauses
#: around it.
TIMEOUT = 0.2


def control():
    "A pane of a known size, with no program under it."
    made = TerminalControl(backend=NoBackend())
    made.create_content(COLUMNS, LINES)
    return made


def row_text(made, number):
    row = made.screen.page.data_buffer[number]
    return "".join(row[x].char for x in range(COLUMNS)).rstrip()


@asynccontextmanager
async def running(script: str) -> AsyncIterator[TerminalControl]:
    "A pane running `sh -c script`, with a short ground timeout."
    async with anyio.create_task_group() as group:
        made = TerminalControl(backend=create_backend(["sh", "-c", script]))
        made._ground_timer.timeout = TIMEOUT
        made.create_content(COLUMNS, LINES)
        await made.start(group)
        try:
            yield made
        finally:
            made.process.kill()
            group.cancel_scope.cancel()


async def until(condition) -> None:
    with anyio.fail_after(5):
        while not condition():
            await anyio.sleep(0.01)


def test_a_pane_gives_its_parser_a_ground_timer():
    made = control()
    assert made._ground_timer.timeout == 5
    assert made.process.receive == made._read


async def test_a_dangling_sequence_does_not_swallow_the_next_output(caplog):
    with caplog.at_level(logging.WARNING, logger="ptterm"):
        async with running("printf 'a\\033[1;'; sleep 1; printf 'b'; sleep 30") as made:
            await until(lambda: made.stream.ground_timer_active)
            # Dropped at the deadline, with nothing written after it.
            await until(lambda: not made.stream.ground_timer_active)
            await until(lambda: row_text(made, 0).endswith("b"))

    assert row_text(made, 0) == "ab"
    # The drop is silent on the screen, so the log names it.
    # Lillecarl/pymux#935.
    (record,) = caplog.records
    assert "'\\x1b[1;'" in record.getMessage()


async def test_a_sequence_survives_a_loop_that_stood_still():
    """
    The program wrote the rest of its sequence while the loop stood
    still, so the pane read it late. The program was never silent, and
    the sequence stands. On a live pane an 18s stall dropped `ESC[?20`
    and drew `26l` as text. Lillecarl/pymux#938.
    """
    async with running("printf 'a\\033[?20'; sleep 0.3; printf '26lb'; sleep 30") as made:
        await until(lambda: made.stream.ground_timer_active)
        time.sleep(1)  # Holds the loop past the timeout.
        await until(lambda: row_text(made, 0).endswith("b"))

    assert row_text(made, 0) == "ab"


def test_a_sequence_still_arriving_is_not_dropped_early():
    made = control()
    made.process.receive("abc\x1b[1;")
    made.process.receive("5m")  # Within the timeout, so it stands.

    assert not made.stream.ground_timer_active
    assert row_text(made, 0) == "abc"
