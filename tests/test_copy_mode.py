"""
Copy mode styles a line when somebody looks at it.

Opening copy mode used to style every row of the buffer: a list of
(style, character) for every cell of the history. A window shows a
screenful, so all but a screenful of that work was for rows nobody
looked at. At fifty thousand rows it cost 22,924,756 bytecode
instructions, and a person pressed a key and waited for it.
Lillecarl/pymux#131.

**A line that is styled late and a line that was styled early have to
be the same line.** So this file does not check the rule. It builds
every line the way the eager code did, asks for every line the lazy way,
and says they match.

The text of the document is still built in full. `Document` holds a
string and prompt_toolkit counts lines in it, so there is nothing to be
lazy about there.
"""
import asyncio

import pytest
from prompt_toolkit.application.current import set_app
from prompt_toolkit.application.dummy import DummyApplication
from prompt_toolkit.layout.layout import Layout

from no_backend import NoBackend
from ptterm.terminal import Terminal

LINES = 6
COLUMNS = 20


@pytest.fixture(autouse=True)
def _a_loop():
    "`Process` reads the running event loop, and pytest starts none."
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    asyncio.set_event_loop(None)
    loop.close()


def a_terminal(data: str) -> Terminal:
    "A widget that has been written to, with copy mode read in."
    terminal = Terminal(backend=NoBackend())
    control = terminal.terminal_control
    control.create_content(COLUMNS, LINES)
    control.stream.feed(data)
    terminal.copy_reverse_video = control.screen.has_reverse_video
    terminal.read_the_screen_into_the_copy_buffer()
    return terminal


def every_line_the_eager_way(terminal):
    """
    What copy mode used to build when it opened: every row of the
    buffer, styled, in one list.
    """
    buffer = terminal.terminal_control.screen.page.data_buffer
    lines = []
    if buffer:
        for index in range(min(buffer), max(buffer) + 1):
            row = buffer[index]
            line = []
            if row:
                for column in range(0, max(row) + 1):
                    char = row[column]
                    line.append(
                        (terminal._copy_cell_style(char), char.char)
                    )
            lines.append(line)
    return lines


#: What a program writes, in the shapes that give a cell a style. The
#: last one scrolls the screen, so the buffer holds history as well.
CHUNKS = [
    "plain text",
    "\r\n\x1b[31;44mcoloured\x1b[0m and not",
    "\r\n\x1b[1;4;7mbold underlined reversed\x1b[0m",
    "\r\n\x1b[?5hunder reverse video",
    "\r\n" + "".join("scrolled row %d\r\n" % number for number in range(20)),
]


@pytest.mark.parametrize("upto", range(1, len(CHUNKS) + 1))
def test_every_line_is_what_the_eager_build_said(upto):
    terminal = a_terminal("".join(CHUNKS[:upto]))
    eager = every_line_the_eager_way(terminal)
    lazy = [terminal.styled_line(number) for number in range(len(eager))]
    assert lazy == eager


def test_the_document_has_one_line_for_each_row_of_the_buffer():
    terminal = a_terminal("".join(CHUNKS))
    eager = every_line_the_eager_way(terminal)
    assert terminal.copy_buffer.document.text.count("\n") + 1 == len(eager)


def test_a_line_is_built_once():
    "The point of the whole thing: the second ask does no work."
    terminal = a_terminal("first\r\nsecond")
    once = terminal.styled_line(0)
    assert terminal.styled_line(0) is once


def test_a_line_that_is_not_there_is_empty():
    "prompt_toolkit asks for the rows of the window, and a window is bigger."
    terminal = a_terminal("one line")
    assert terminal.styled_line(1000) == []


async def test_leaving_copy_mode_forgets_what_was_styled():
    """
    The program runs again, so a line that was styled says what the
    screen held before it did.

    The caller has to be a coroutine: the copy buffer starts a
    background task, and prompt_toolkit reads the running loop for it.
    """
    terminal = Terminal(backend=NoBackend())
    control = terminal.terminal_control
    control.create_content(COLUMNS, LINES)
    control.stream.feed("first\r\nsecond")

    app = DummyApplication()
    app.layout = Layout(terminal.container)
    with set_app(app):
        terminal.enter_copy_mode()
        assert terminal.styled_line(0)
        assert terminal._styled_lines
        terminal.exit_copy_mode()

    assert not terminal._styled_lines
