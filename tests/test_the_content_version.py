"""
A pane says when it would draw what it drew before.

`content_version` is what the window compares: the same answer, and the
window writes the cells of the frame before instead of asking for
content. So every change that reaches the picture has to change it,
the cursor included, which moves with no write to any row.
Lillecarl/pymux#577.
"""

from __future__ import annotations

from no_backend import NoBackend
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input import DummyInput
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.output import DummyOutput
from pyte.modes import PrivateMode
from pyte.sequences import set_mode

from ptterm.control import TerminalControl
from ptterm.window import TerminalWindow

LINES = 4
COLUMNS = 20


def a_control() -> TerminalControl:
    control = TerminalControl(backend=NoBackend())
    control.create_content(COLUMNS, LINES)
    return control


def version(control: TerminalControl):
    return control.content_version(COLUMNS, LINES)


def test_nothing_new_is_the_same_version():
    control = a_control()
    control.feed_output("text")
    control.create_content(COLUMNS, LINES)
    assert version(control) == version(control)


def test_a_write_moves_the_version():
    control = a_control()
    before = version(control)
    control.feed_output("text")
    assert version(control) != before


def test_a_cursor_that_moved_without_a_write_moves_the_version():
    control = a_control()
    control.feed_output("text")
    before = version(control)
    control.feed_output("\x1b[3;5H")
    assert version(control) != before


def test_a_hidden_cursor_moves_the_version():
    control = a_control()
    before = version(control)
    control.feed_output("\x1b[?25l")
    assert version(control) != before


def test_another_size_is_another_version():
    control = a_control()
    assert control.content_version(COLUMNS + 1, LINES) != version(control)


def test_a_held_frame_keeps_its_version_through_writes():
    control = a_control()
    control.feed_output("before")
    control.create_content(COLUMNS, LINES)
    control.feed_output(set_mode(PrivateMode.SYNCHRONIZED_OUTPUT) + "\x1b[Hafter")
    held = version(control)
    control.create_content(COLUMNS, LINES)
    control.feed_output("more")
    assert version(control) == held


def test_a_control_that_keeps_no_rows_cannot_say():
    control = a_control()
    control.keep_rows = False
    assert version(control) is None


def test_a_pane_draws_the_cursor_where_it_moved():
    "Through a window: a frame drawn again would leave it where it was."
    control = a_control()
    window = TerminalWindow(terminal_control=control, content=control, wrap_lines=False)
    app = Application(layout=Layout(window), input=DummyInput(), output=DummyOutput())
    app.layout.update_parents_relations()
    position = WritePosition(xpos=0, ypos=0, width=COLUMNS, height=LINES)

    def draw() -> Screen:
        screen = Screen()
        window.write_to_screen(screen, MouseHandlers(), position, "", False, None)
        return screen

    control.feed_output("text\r\n\r\n\r\nend")
    with set_app(app):
        first = draw()
        assert first.get_cursor_position(window) == (3, 3)
        for _ in range(2):
            draw()
        # The window kept the frame, so an unchanged version would replay it.
        assert window._drawn is not None and window._drawn.rows is not None
        control.feed_output("\x1b[3;5H")
        screen = draw()

    assert screen.get_cursor_position(window) == (4, 2)
