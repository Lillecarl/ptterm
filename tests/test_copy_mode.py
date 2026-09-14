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
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.key_binding.key_processor import KeyPress, _Flush
from prompt_toolkit.key_binding.vi_state import InputMode
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


def a_terminal(data: str, copy_func=None) -> Terminal:
    "A widget that has been written to, with copy mode read in."
    terminal = Terminal(backend=NoBackend(), copy_func=copy_func)
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


def test_copy_mode_and_the_pane_agree_after_a_narrowing():
    """
    The alternate screen does not reflow, so it never holds more rows
    than it can show, and copy mode reads the same rows the pane draws.

    It used to reflow. Five rows that each filled a wide screen wrapped
    into ten on a narrow one; the pane drew the last six of them and
    copy mode read all ten, so the first row of the pane and the first
    row of copy mode were different lines. Lillecarl/pymux#192.
    """
    wide = COLUMNS + 12
    terminal = Terminal(backend=NoBackend())
    control = terminal.terminal_control
    control.create_content(wide, LINES)
    control.stream.feed(
        set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR)
        + "\r\n".join(letter * (wide - 1) for letter in "ABCDE")
    )

    # The resize a person makes by dragging the edge of the window.
    control.create_content(COLUMNS, LINES)
    terminal.read_the_screen_into_the_copy_buffer()

    document = terminal.copy_buffer.document
    screen = control.screen

    assert document.line_count <= LINES, document.lines

    # The row the pane draws at the top of the screen is the row copy
    # mode offers at the top of its document.
    top = screen.line_offset
    drawn = "".join(
        cell.char or " " for cell in screen.page.data_buffer[top].values()
    ).rstrip()
    assert document.lines[0] == drawn, (document.lines, drawn)


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


async def press(terminal, *keys, vi=False):
    """
    Open copy mode, press these keys, and give back the application.

    The keys go through the key processor of a real application, which
    is what decides which binding a key reaches. A test that called the
    handler itself would pass with no binding at all, and that is the
    fault these keys had. Lillecarl/pymux#133.

    `vi` is the `mode-keys` option of tmux, which pymux spells as the
    editing mode of the application. A read-only buffer holds the vi
    state in navigation mode, which is what pymux does on a change of
    focus.
    """
    app = DummyApplication()
    app.layout = Layout(terminal.container)
    if vi:
        app.editing_mode = EditingMode.VI

    with set_app(app):
        terminal.enter_copy_mode()
        if vi:
            app.vi_state.input_mode = InputMode.NAVIGATION
        for key in keys:
            # The data of a key press is the character it stands for.
            # A vi count reads it, and so does a jump like `f`.
            app.key_processor.feed(KeyPress(key, key if len(key) == 1 else ""))
        app.key_processor.process_keys()

    return app


@pytest.mark.parametrize("key", ["q", Keys.ControlM, Keys.ControlC])
async def test_a_key_that_leaves_copy_mode(key):
    "tmux leaves copy mode on all of these, and pymux left on one."
    terminal = a_terminal("first\r\nsecond")
    await press(terminal, key)
    assert not terminal.is_copying


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


async def test_v_swaps_what_a_selection_selects():
    terminal = a_terminal("first\r\nsecond")
    await press(terminal, " ", "v")
    assert terminal.copy_buffer.selection_state.type == SelectionType.LINES
    assert terminal.is_copying


# ----------------------------------------------------------------------
# Copying. Lillecarl/pymux#376.


def _to_the_start_of_the_line(vi):
    "The keys that take the caret to column nought."
    return ["0"] if vi else [Keys.ControlA]


@pytest.mark.parametrize("vi, copied", [(False, "h"), (True, "he")])
async def test_enter_leaves_copy_mode_with_the_copy_made(vi, copied):
    """
    tmux leaves: `Enter` is `copy-pipe-and-cancel` in both of its key
    tables. It stayed, so a person had made the copy and nothing said
    so.

    A vi selection holds the character under the caret as well, which
    is why the two halves copy a different number of them.
    """
    terminal = a_terminal("hello world")
    app = await press(
        terminal, *_to_the_start_of_the_line(vi), " ", Keys.Right, Keys.ControlM, vi=vi
    )
    assert not terminal.is_copying
    assert app.clipboard.get_data().text == copied


async def test_y_copies_and_leaves_with_vi_keys():
    """
    tmux leaves `y` unbound and a person with vi keys binds it to
    `copy-selection-and-cancel`, which is the first thing they press.
    """
    terminal = a_terminal("hello world")
    app = await press(terminal, "0", "v", "l", "y", vi=True)
    assert app.clipboard.get_data().text == "he"
    assert not terminal.is_copying


@pytest.mark.parametrize(
    "vi, keys",
    [
        (True, ["g", "g", "V", "y"]),
        (False, [Keys.ControlP, Keys.ControlA, " ", "v", Keys.ControlM]),
    ],
)
async def test_a_selection_of_lines_does_not_carry_the_break(vi, keys):
    """
    A copy of one line is one line. The keys reach it from both sides:
    `V` selects lines with vi keys, and `v` swaps a selection to lines
    with emacs keys.
    """
    terminal = a_terminal("hello world\r\nsecond")
    app = await press(terminal, *keys, vi=vi)
    assert app.clipboard.get_data().text == "hello world"


async def test_y_with_no_selection_is_still_the_vi_operator():
    "`yy` is prompt_toolkit's, and copy mode does not take it away."
    terminal = a_terminal("hello world")
    app = await press(terminal, "y", "y", vi=True)
    assert app.clipboard.get_data().text == "hello world"
    assert terminal.is_copying


async def test_the_copy_is_handed_to_the_embedder():
    """
    The clipboard of the user belongs to their terminal, which this
    widget does not own. So a copy is handed over, and the embedder
    decides: pymux asks `set-clipboard`.
    """
    copied = []
    terminal = a_terminal("hello world", copy_func=copied.append)
    await press(terminal, "0", "v", "l", "y", vi=True)

    assert copied == ["he"]


async def test_nothing_is_handed_over_when_the_selection_is_empty():
    copied = []
    terminal = a_terminal("hello world", copy_func=copied.append)
    await press(terminal, "0", " ", Keys.ControlM)

    assert copied == []


async def test_v_is_vis_own_key_with_vi_keys():
    "It ends the selection, the way vi does. `V` selects lines."
    terminal = a_terminal("hello world")
    await press(terminal, "0", "v", "l", "v", vi=True)
    assert terminal.copy_buffer.selection_state is None


# ----------------------------------------------------------------------
# Where the caret may stand. Lillecarl/pymux#377.


async def test_the_caret_does_not_stand_on_the_line_break():
    """
    `$` is one past the last character, which is where an editor puts
    what a person types next. vi does not allow it and neither does
    tmux: `window_copy_cursor_limit` returns `grid_line_limit` for vi
    mode keys, the last character of the row.
    """
    terminal = a_terminal("hello world\r\nsecond")
    await press(terminal, "g", "g", "0", "$", vi=True)
    assert terminal.copy_buffer.document.cursor_position == len("hello world") - 1


async def test_a_selection_to_the_end_of_a_line_leaves_the_break_behind():
    "The copy carried a line ending that nobody selected."
    terminal = a_terminal("hello world\r\nsecond")
    app = await press(terminal, "g", "g", "0", "v", "$", "y", vi=True)
    assert app.clipboard.get_data().text == "hello world"


async def test_the_caret_stops_at_the_last_character_of_the_last_line():
    "There is no break under it, and a selected cell was drawn there."
    terminal = a_terminal("hello world")
    await press(terminal, "0", "$", vi=True)
    assert terminal.copy_buffer.document.cursor_position == len("hello world") - 1


async def test_an_empty_line_holds_the_caret_at_its_start():
    "There is nowhere else to stand, and the line before is not it."
    terminal = a_terminal("one\r\n\r\nthree")
    await press(terminal, "g", "g", "j", "$", vi=True)
    assert terminal.copy_buffer.document.cursor_position_row == 1
    assert terminal.copy_buffer.document.cursor_position_col == 0


async def test_emacs_keys_keep_the_caret_past_the_last_character():
    "tmux clamps for vi mode keys alone, and this is the other half."
    terminal = a_terminal("hello world\r\nsecond")
    await press(terminal, Keys.ControlP, Keys.ControlE)
    assert terminal.copy_buffer.document.cursor_position == len("hello world")


async def test_copy_mode_opens_where_the_pane_is_with_vi_keys():
    """
    The caret opens past the last character of a shell prompt, which is
    where the next character goes. Only a move of the caret is clamped.
    Lillecarl/pymux#189.
    """
    terminal = a_terminal("one\r\ntwo\r\nthree")
    await press(terminal, vi=True)
    assert _cursor(terminal) == (2, 5)


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
