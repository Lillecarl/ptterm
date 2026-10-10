"""
A pane shows its last picture while its program draws a frame.

A program brackets a frame in "?2026h" and "?2026l". A redraw between
the two would show the frame half drawn, so the control asks for no
redraw until the frame ends, and a redraw that comes due for another
reason draws the picture from before. tmux does the same, and lets go
after a second. Lillecarl/pymux#567.
"""

from __future__ import annotations

import anyio
import pytest
from no_backend import NoBackend
from pyte.modes import PrivateMode
from pyte.sequences import reset_mode, set_mode

import ptterm.terminal
from ptterm.terminal import _TerminalControl

BEGIN = set_mode(PrivateMode.SYNCHRONIZED_OUTPUT)
END = reset_mode(PrivateMode.SYNCHRONIZED_OUTPUT)
HOME = "\x1b[H"

LINES = 4
COLUMNS = 20


def a_control():
    "A control that has drawn one frame, and the list of redraws it asked for."
    control = _TerminalControl(backend=NoBackend())
    asked = []
    control.on_content_changed += lambda _: asked.append(True)
    control.create_content(COLUMNS, LINES)
    return control, asked


def first_row(control) -> str:
    content = control.create_content(COLUMNS, LINES)
    return "".join(text for _style, text in content.get_line(0)).rstrip()


def test_a_frame_being_drawn_asks_for_no_redraw():
    control, asked = a_control()
    control.feed_output(BEGIN + "half")
    assert asked == []


def test_a_redraw_while_the_frame_is_drawn_shows_the_picture_before():
    control, _asked = a_control()
    control.feed_output("before")
    assert first_row(control) == "before"
    control.feed_output(BEGIN + HOME + "after ")
    assert first_row(control) == "before"


def test_the_end_of_the_frame_draws_it():
    control, asked = a_control()
    control.feed_output("before")
    first_row(control)
    asked.clear()
    control.feed_output(BEGIN + HOME + "after ")
    control.feed_output(END)
    assert asked == [True]
    assert first_row(control) == "after"


def test_a_frame_that_ends_and_begins_again_in_one_feed_draws():
    "The feed ends with the mode set, and the count of frames says one ended."
    control, asked = a_control()
    control.feed_output(BEGIN + "one")
    control.feed_output(END + BEGIN + HOME + "two")
    assert asked == [True]
    assert first_row(control) == "two"


def test_a_frame_that_takes_too_long_draws_as_it_comes(monkeypatch):
    "Until the program ends it: a hold that ran out does not start again."
    now = [0.0]
    monkeypatch.setattr(ptterm.terminal.time, "monotonic", lambda: now[0])
    control, asked = a_control()
    control.feed_output(BEGIN + "slow")
    now[0] = 2.0
    control.feed_output(" frame")
    assert asked == [True]
    control.feed_output(" still")
    assert asked == [True, True]
    assert first_row(control) == "slow frame still"


async def test_a_program_that_never_ends_the_frame_is_drawn_after_a_while(monkeypatch):
    monkeypatch.setattr(ptterm.terminal, "_FRAME_HELD_AT_MOST", 0.05)
    control, asked = a_control()
    async with anyio.create_task_group() as task_group:
        control._task_group = task_group
        control.feed_output(BEGIN + "stuck")
        assert asked == []
        with anyio.fail_after(5):
            while not asked:
                await anyio.sleep(0.01)
    assert first_row(control) == "stuck"


async def test_a_frame_that_ends_in_time_leaves_no_timer_behind(monkeypatch):
    monkeypatch.setattr(ptterm.terminal, "_FRAME_HELD_AT_MOST", 0.05)
    control, asked = a_control()
    with anyio.fail_after(5):
        async with anyio.create_task_group() as task_group:
            control._task_group = task_group
            control.feed_output(BEGIN + "quick")
            control.feed_output(END)
    assert asked == [True]


@pytest.mark.parametrize("keep_rows", [True, False])
def test_the_held_picture_holds_every_row(keep_rows):
    control, _asked = a_control()
    control.keep_rows = keep_rows
    control.feed_output("one\r\ntwo\r\nthree")
    before = control.create_content(COLUMNS, LINES)
    lines = [before.get_line(n) for n in range(before.line_count)]
    control.feed_output(BEGIN + "\x1b[2J" + HOME + "gone")
    held = control.create_content(COLUMNS, LINES)
    assert held.line_count == before.line_count
    assert held.cursor_position == before.cursor_position
    assert [held.get_line(n) for n in range(held.line_count)] == lines
