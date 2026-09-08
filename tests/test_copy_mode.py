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

**A line of the document is a line a program wrote**, not a row of the
pane. The window wraps it again for the eye. Lillecarl/pymux#135.
"""

import asyncio

import pytest
from prompt_toolkit.application.current import set_app
from prompt_toolkit.application.dummy import DummyApplication
from prompt_toolkit.key_binding.key_processor import KeyPress, _Flush
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.selection import SelectionType

from no_backend import NoBackend
from ptterm.terminal import Terminal
from pyte.modes import PrivateMode
from pyte.sequences import set_mode
from pyte import escape
from pyte.sequences import csi

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
    Every line of the buffer, styled, in one list.

    **It walks the rows itself** rather than asking `Page.unwrap`, so
    that it judges the answer and does not repeat it. A run of rows
    that a wrap made is one line, because that is one line a program
    wrote. Lillecarl/pymux#135.
    """
    buffer = terminal.terminal_control.screen.page.data_buffer
    lines = []
    if buffer:
        for index in range(min(buffer), max(buffer) + 1):
            row = buffer[index]
            if not (row is not None and row.wrapped) or not lines:
                lines.append([])
            if row:
                for column in range(0, max(row) + 1):
                    char = row[column]
                    lines[-1].append((terminal._copy_cell_style(char), char.char))
    return lines


#: What a program writes, in the shapes that give a cell a style. One
#: of them is longer than the pane, so a line takes two rows. The last
#: one scrolls the screen, so the buffer holds history as well.
CHUNKS = [
    "plain text",
    "\r\n" + csi(escape.SGR, 31, 44) + "coloured" + csi(escape.SGR, 0) + " and not",
    "\r\n" + csi(escape.SGR, 1, 4, 7) + "bold underlined reversed" + csi(escape.SGR, 0),
    "\r\n" + set_mode(PrivateMode.REVERSE_VIDEO) + "under reverse video",
    "\r\na line that is longer than the pane is wide",
    "\r\n" + "".join("scrolled row %d\r\n" % number for number in range(20)),
]


@pytest.mark.parametrize("upto", range(1, len(CHUNKS) + 1))
def test_every_line_is_what_the_eager_build_said(upto):
    terminal = a_terminal("".join(CHUNKS[:upto]))
    eager = every_line_the_eager_way(terminal)
    lazy = [terminal.styled_line(number) for number in range(len(eager))]
    assert lazy == eager


def test_the_document_has_one_line_for_each_line_of_the_buffer():
    terminal = a_terminal("".join(CHUNKS))
    eager = every_line_the_eager_way(terminal)
    assert terminal.copy_buffer.document.text.count("\n") + 1 == len(eager)


def test_a_line_the_pane_wrapped_is_one_line_of_the_document():
    """
    The pane cut the line to fit. A person copying wants the line the
    program wrote, so the cut is not in the document at all.
    """
    text = "a line that is longer than the pane is wide"
    terminal = a_terminal(text)
    assert terminal.copy_buffer.document.text.rstrip() == text


def test_a_line_is_built_once():
    "The point of the whole thing: the second ask does no work."
    terminal = a_terminal("first\r\nsecond")
    once = terminal.styled_line(0)
    assert terminal.styled_line(0) is once


def test_a_line_that_is_not_there_is_empty():
    "prompt_toolkit asks for the rows of the window, and a window is bigger."
    terminal = a_terminal("one line")
    assert terminal.styled_line(1000) == []


def test_copy_mode_on_the_alternate_screen_shows_the_screen():
    """
    A full-screen program draws on a screen of its own, and what
    scrolls off the top of it is gone. So copy mode there offers that
    screen and nothing above it.

    It offered a hundred rows more: the alternate screen kept its rows
    to `history-limit`, which is the depth a person chose for the
    scrollback of their shell, and pruned once every hundred lines.
    Lillecarl/pymux#132.
    """
    terminal = a_terminal(
        set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "".join("row %d\r\n" % number for number in range(60))
    )
    document = terminal.copy_buffer.document

    # Six rows of screen, and the last one holds nothing yet.
    assert document.line_count <= LINES
    assert document.lines[0] == "row 55"


# ----------------------------------------------------------------------
# Where copy mode opens. Lillecarl/pymux#189.


def _cursor(terminal):
    "The row and the column the copy cursor opened on."
    document = terminal.copy_buffer.document
    return document.cursor_position_row, document.cursor_position_col


def test_copy_mode_opens_where_the_pane_cursor_is():
    """
    Copy mode opens on what a person was looking at.

    It opened at the end of the whole flattened buffer, which is where
    a shell prompt happens to be and is nowhere in particular for a
    program that draws its own screen. The window follows the cursor,
    so a full screen program saw the view pop as copy mode opened.
    """
    terminal = a_terminal(
        set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "one\r\ntwo\r\nthree"
        + csi(escape.CUP, 2, 2)
    )

    assert _cursor(terminal) == (1, 1)


def test_the_cursor_of_a_shell_is_still_at_the_end():
    "Which is where it always was, because that is where a shell is."
    terminal = a_terminal("one\r\ntwo\r\nthree")

    row, column = _cursor(terminal)
    assert (row, column) == (2, 5)


def test_a_cursor_on_a_row_a_wrap_made():
    """
    A line the pane wrapped is one line of the document, so the rows
    before the cursor's own row inside that line count for what they
    hold.
    """
    text = "a line that is longer than the pane is wide"
    terminal = a_terminal(text)

    document = terminal.copy_buffer.document
    assert document.line_count == 1
    assert document.cursor_position == len(text)


def test_a_cursor_past_the_end_of_its_row():
    "It stands where the next character goes, which is past the cells."
    terminal = a_terminal("one\r\ntwo" + csi(escape.CUP, 1, 10))

    assert _cursor(terminal) == (0, 3)


async def press(terminal, *keys):
    """
    Open copy mode, press these keys, and give the terminal back.

    The keys go through the key processor of a real application, which
    is what decides which binding a key reaches. A test that called the
    handler itself would pass with no binding at all, and that is the
    fault these keys had. Lillecarl/pymux#133.
    """
    app = DummyApplication()
    app.layout = Layout(terminal.container)

    with set_app(app):
        terminal.enter_copy_mode()
        for key in keys:
            app.key_processor.feed(KeyPress(key, ""))
        app.key_processor.process_keys()

    return terminal


@pytest.mark.parametrize("key", ["q", Keys.ControlM, Keys.ControlC])
async def test_a_key_that_leaves_copy_mode(key):
    "tmux leaves copy mode on all of these, and pymux left on one."
    assert not (await press(a_terminal("first\r\nsecond"), key)).is_copying


async def test_escape_leaves_copy_mode():
    """
    Escape has its own test because the key processor holds one back:
    it may be the start of a sequence, and only a flush says it is not.
    """
    terminal = a_terminal("first\r\nsecond")
    app = DummyApplication()
    app.layout = Layout(terminal.container)

    with set_app(app):
        terminal.enter_copy_mode()
        app.key_processor.feed(KeyPress(Keys.Escape, "\x1b"))
        app.key_processor.process_keys()
        # The timeout feeds this when no key followed the escape.
        app.key_processor.feed(_Flush)
        app.key_processor.process_keys()

    assert not terminal.is_copying


async def test_space_starts_a_selection_and_enter_keeps_copy_mode():
    "Enter copies the selection there, so it may not also leave."
    terminal = await press(a_terminal("first\r\nsecond"), " ", Keys.ControlM)
    assert terminal.is_copying


async def test_v_swaps_what_a_selection_selects():
    terminal = await press(a_terminal("first\r\nsecond"), " ", "v")
    assert terminal.copy_buffer.selection_state.type == SelectionType.LINES
    assert terminal.is_copying


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
