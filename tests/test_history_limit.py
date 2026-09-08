"""
How deep the scrollback of a pane goes, and who decides it.

`Screen` drops the rows above its history limit, and the limit reaches
it as a function. Nothing gave `_TerminalControl` a way to pass one, so
every pane kept two thousand rows whatever its embedder offered. tmux
and pymux both call the option `history-limit`, and a person who sets
it means it.

The limit is a function and not a number so that a change reaches a
pane that is already running. `Screen` calls it on every cleanup.
"""

import asyncio

import pytest

from no_backend import NoBackend
from ptterm.terminal import _TerminalControl

LINES = 24
COLUMNS = 80

#: How often `Screen` prunes the history: one cleanup per hundred
#: linefeeds. So a buffer holds up to a hundred rows more than the
#: limit, and a test that asks for exactly the limit is wrong.
BETWEEN_CLEANUPS = 100


@pytest.fixture(autouse=True)
def _a_loop():
    "`Process` reads the running event loop, and pytest starts none."
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    asyncio.set_event_loop(None)
    loop.close()


def control(get_history_limit=None):
    "A widget of a known size, with no program under it."
    made = _TerminalControl(backend=NoBackend(), get_history_limit=get_history_limit)
    made.create_content(COLUMNS, LINES)
    return made


def scroll(made, rows: int) -> None:
    "Write that many lines, so that the screen scrolls that far."
    made.stream.feed("".join("line %d\r\n" % number for number in range(rows)))


def test_a_pane_keeps_two_thousand_rows_by_default():
    made = control()
    scroll(made, 4000)
    kept = len(made.screen.page.data_buffer)
    assert 2000 <= kept <= 2000 + BETWEEN_CLEANUPS + LINES


def test_the_embedder_says_how_deep_the_history_goes():
    made = control(lambda: 500)
    scroll(made, 4000)
    kept = len(made.screen.page.data_buffer)
    assert 500 <= kept <= 500 + BETWEEN_CLEANUPS + LINES


def test_the_limit_is_read_again_while_the_pane_runs():
    "A person who lowers the option sees the pane follow it."
    limit = 2000
    made = control(lambda: limit)
    scroll(made, 4000)
    assert len(made.screen.page.data_buffer) > 1000

    limit = 200
    scroll(made, BETWEEN_CLEANUPS)
    kept = len(made.screen.page.data_buffer)
    assert 200 <= kept <= 200 + BETWEEN_CLEANUPS + LINES
