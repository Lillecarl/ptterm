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

from __future__ import annotations

import gc
import weakref

import pytest
from no_backend import NoBackend
from prompt_toolkit.application.current import set_app
from prompt_toolkit.application.dummy import DummyApplication
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.key_binding.key_processor import KeyPress, _Flush
from prompt_toolkit.key_binding.vi_state import InputMode
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen as PtScreen
from prompt_toolkit.layout.screen import WritePosition
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.selection import SelectionType
from pyte import escape
from pyte.cells import WrittenCell
from pyte.modes import PrivateMode
from pyte.page import RowMark
from pyte.placeholders import PLACEHOLDER
from pyte.sequences import csi, set_mode

from ptterm.terminal import Terminal

LINES = 6
COLUMNS = 20


def a_terminal(data: str, copy_func=None) -> Terminal:
    "A widget that has been written to, with copy mode read in."
    terminal = Terminal(backend=NoBackend(), copy_func=copy_func)
    control = terminal.terminal_control
    control.create_content(COLUMNS, LINES)
    control.stream.feed(data)
    terminal.enter_copy_mode()
    return terminal


def every_line_the_eager_way(terminal):
    """
    Every line of the buffer, styled, in one list.

    **It walks the rows itself** rather than asking `Page.unwrap`, so
    that it judges the answer and does not repeat it. A run of rows
    that a wrap made is one line, because that is one line a program
    wrote. Lillecarl/pymux#135. The spaces at the end of a line are
    not in it, as tmux's `grid_line_length` leaves them out.
    """
    buffer = terminal.terminal_control.screen.page.data_buffer
    lines = []
    if buffer:
        for index in range(min(buffer), max(buffer) + 1):
            row = buffer[index]
            if not (row is not None and row.wrapped) or not lines:
                lines.append([])
            if row:
                for column in range(max(row) + 1):
                    char = row[column]
                    lines[-1].append(terminal.copy_view.cell(char))
    for line in lines:
        while line and line[-1][1] == " ":
            line.pop()
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
    # Padded to the width, as Claude Code pads every row.
    "\r\npadded" + " " * 14,
    "\r\n" + "".join("scrolled row %d\r\n" % number for number in range(20)),
]


@pytest.mark.parametrize("upto", range(1, len(CHUNKS) + 1))
def test_every_line_is_what_the_eager_build_said(upto):
    terminal = a_terminal("".join(CHUNKS[:upto]))
    eager = every_line_the_eager_way(terminal)
    lazy = [terminal.copy_view.styled_line(number) for number in range(len(eager))]
    assert lazy == eager


def test_the_document_has_one_line_for_each_line_of_the_buffer():
    terminal = a_terminal("".join(CHUNKS))
    eager = every_line_the_eager_way(terminal)
    assert terminal.copy_view.buffer.document.text.count("\n") + 1 == len(eager)


def test_a_line_the_pane_wrapped_is_one_line_of_the_document():
    """
    The pane cut the line to fit. A person copying wants the line the
    program wrote, so the cut is not in the document at all.
    """
    text = "a line that is longer than the pane is wide"
    terminal = a_terminal(text)
    assert terminal.copy_view.buffer.document.text.rstrip() == text


def test_the_spaces_at_the_end_of_a_line_are_not_in_the_document():
    """
    tmux measures a row of copy mode to its last cell that is not a
    space. A program that pads every row to the width put a move to the
    end of the line at the right edge, and a copy ran on with blanks.
    """
    terminal = a_terminal("padded" + " " * 14 + "\r\n  indented  ")
    assert terminal.copy_view.buffer.document.lines[:2] == ["padded", "  indented"]


def test_a_line_is_built_once():
    "The point of the whole thing: the second ask does no work."
    terminal = a_terminal("first\r\nsecond")
    once = terminal.copy_view.styled_line(0)
    assert terminal.copy_view.styled_line(0) is once


def test_a_line_that_is_not_there_is_empty():
    "prompt_toolkit asks for the rows of the window, and a window is bigger."
    terminal = a_terminal("one line")
    assert terminal.copy_view.styled_line(1000) == []


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
        set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR) + "".join("row %d\r\n" % number for number in range(60))
    )
    document = terminal.copy_view.buffer.document

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
        set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR) + "\r\n".join(letter * (wide - 1) for letter in "ABCDE")
    )

    # The resize a person makes by dragging the edge of the window.
    control.create_content(COLUMNS, LINES)
    terminal.enter_copy_mode()

    document = terminal.copy_view.buffer.document
    screen = control.screen

    assert document.line_count <= LINES, document.lines

    # The row the pane draws at the top of the screen is the row copy
    # mode offers at the top of its document.
    top = screen.line_offset
    drawn = "".join(cell.char or " " for cell in screen.page.data_buffer[top].values()).rstrip()
    assert document.lines[0] == drawn, (document.lines, drawn)


# ----------------------------------------------------------------------
# Where copy mode opens. Lillecarl/pymux#189.


def _cursor(view):
    "The row and the column the copy cursor opened on."
    document = view.buffer.document
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
        set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR) + "one\r\ntwo\r\nthree" + csi(escape.CUP, 2, 2)
    )

    assert _cursor(terminal.copy_view) == (1, 1)


def test_the_cursor_of_a_shell_is_still_at_the_end():
    "Which is where it always was, because that is where a shell is."
    terminal = a_terminal("one\r\ntwo\r\nthree")

    row, column = _cursor(terminal.copy_view)
    assert (row, column) == (2, 5)


def test_the_position_counts_lines_of_the_history():
    """
    The indicator says which line of the history the cursor is on, from
    the oldest, and does not depend on where the window has scrolled.
    """
    terminal = a_terminal("\r\n".join("line %d" % number for number in range(60)))

    assert terminal.copy_view._position_formatted_text() == "[60/60]"
    terminal.copy_view.scroll(-10)
    assert terminal.copy_view._position_formatted_text() == "[50/60]"
    terminal.copy_view.scroll(-1000)
    assert terminal.copy_view._position_formatted_text() == "[1/60]"


def test_a_cursor_on_a_row_a_wrap_made():
    """
    A line the pane wrapped is one line of the document, so the rows
    before the cursor's own row inside that line count for what they
    hold.
    """
    text = "a line that is longer than the pane is wide"
    terminal = a_terminal(text)

    document = terminal.copy_view.buffer.document
    assert document.line_count == 1
    assert document.cursor_position == len(text)


def test_a_cursor_past_the_end_of_its_row():
    "It stands where the next character goes, which is past the cells."
    terminal = a_terminal("one\r\ntwo" + csi(escape.CUP, 1, 10))

    assert _cursor(terminal.copy_view) == (0, 3)


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
    app = await press(terminal, key)
    assert terminal.copy_views.of(app) is None


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

    assert terminal.copy_views.of(app) is None


async def test_v_swaps_what_a_selection_selects():
    terminal = a_terminal("first\r\nsecond")
    app = await press(terminal, Keys.ControlSpace, "v")
    assert terminal.copy_views.of(app).buffer.selection_state.type == SelectionType.LINES
    assert terminal.copy_views.of(app) is not None


# ----------------------------------------------------------------------
# Copying. Lillecarl/pymux#376.


def _to_the_start_of_the_line(vi):
    "The keys that take the caret to column nought."
    return ["0"] if vi else [Keys.ControlA]


def _begin_selection(vi):
    """
    The key that starts a selection in each table.

    tmux binds `Space` with vi keys and `C-Space` with emacs keys,
    where `Space` is the page under this one. Lillecarl/pymux#379.
    """
    return " " if vi else Keys.ControlSpace


@pytest.mark.parametrize(("vi", "copied"), [(False, "h"), (True, "he")])
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
        terminal,
        *_to_the_start_of_the_line(vi),
        _begin_selection(vi),
        Keys.Right,
        Keys.ControlM,
        vi=vi,
    )
    assert terminal.copy_views.of(app) is None
    assert app.clipboard.get_data().text == copied


async def test_y_copies_and_leaves_with_vi_keys():
    """
    tmux leaves `y` unbound and a person with vi keys binds it to
    `copy-selection-and-cancel`, which is the first thing they press.
    """
    terminal = a_terminal("hello world")
    app = await press(terminal, "0", "v", "l", "y", vi=True)
    assert app.clipboard.get_data().text == "he"
    assert terminal.copy_views.of(app) is None


@pytest.mark.parametrize(
    ("vi", "keys"),
    [
        (True, ["g", "g", "V", "y"]),
        (False, [Keys.ControlP, Keys.ControlA, Keys.ControlSpace, "v", Keys.ControlM]),
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
    assert terminal.copy_views.of(app) is not None


async def test_the_copy_is_handed_to_the_embedder():
    """
    The clipboard of the user belongs to their terminal, which this
    widget does not own. So a copy is handed over, and the embedder
    decides: pymux asks `set-clipboard`.
    """
    copied = []
    terminal = a_terminal("hello world", copy_func=copied.append)
    app = await press(terminal, "0", "v", "l", "y", vi=True)

    assert copied == ["he"]


async def test_nothing_is_handed_over_when_the_selection_is_empty():
    copied = []
    terminal = a_terminal("hello world", copy_func=copied.append)
    app = await press(terminal, "0", " ", Keys.ControlM)

    assert copied == []


@pytest.mark.parametrize("keys", [[Keys.ControlW], [Keys.Escape, "w"]])
async def test_the_two_copy_keys_of_emacs(keys):
    "`C-w` and `M-w` are the two tmux binds, and the two such a person knows."
    terminal = a_terminal("hello world")
    app = await press(terminal, Keys.ControlA, Keys.ControlSpace, Keys.Right, *keys)
    assert app.clipboard.get_data().text == "h"
    assert terminal.copy_views.of(app) is None


# ----------------------------------------------------------------------
# Space. Lillecarl/pymux#379.


def _render(terminal, rows=LINES):
    """
    Draw the copy window once, so that it has a `render_info`.

    Everything that scrolls reads one: how far the page reaches is a
    fact about the window on the screen, and a window that was never
    drawn has none.
    """
    terminal.copy_view.window.write_to_screen(
        PtScreen(),
        MouseHandlers(),
        WritePosition(xpos=0, ypos=0, width=COLUMNS, height=rows),
        "",
        False,
        None,
    )


async def test_space_pages_down_with_emacs_keys():
    """
    tmux gives `Space` to the page with emacs keys and to the
    selection with vi keys. Both tables started a selection here.
    """
    terminal = a_terminal("\r\n".join("row %d" % number for number in range(40)))

    app = DummyApplication()
    app.layout = Layout(terminal.container)
    with set_app(app):
        terminal.enter_copy_mode()
        terminal.copy_views.of(app).buffer.cursor_position = 0
        _render(terminal)
        app.key_processor.feed(KeyPress(" ", " "))
        app.key_processor.process_keys()

    assert terminal.copy_views.of(app).buffer.document.cursor_position_row >= LINES - 1
    assert terminal.copy_views.of(app).buffer.selection_state is None
    assert terminal.copy_views.of(app) is not None


async def test_space_starts_a_selection_with_vi_keys():
    "Which is what tmux binds there, and what both tables did."
    terminal = a_terminal("hello world")
    app = await press(terminal, "0", " ", "l", vi=True)
    assert terminal.copy_views.of(app).buffer.selection_state is not None


async def test_control_space_starts_a_selection_with_emacs_keys():
    "prompt_toolkit binds it, and tmux binds the same key."
    terminal = a_terminal("hello world")
    app = await press(terminal, Keys.ControlA, Keys.ControlSpace, Keys.Right)
    assert terminal.copy_views.of(app).buffer.selection_state is not None
    assert app.clipboard.get_data().text == ""


async def test_v_is_vis_own_key_with_vi_keys():
    "It ends the selection, the way vi does. `V` selects lines."
    terminal = a_terminal("hello world")
    app = await press(terminal, "0", "v", "l", "v", vi=True)
    assert terminal.copy_views.of(app).buffer.selection_state is None


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
    app = await press(terminal, "g", "g", "0", "$", vi=True)
    assert terminal.copy_views.of(app).buffer.document.cursor_position == len("hello world") - 1


async def test_a_selection_to_the_end_of_a_line_leaves_the_break_behind():
    "The copy carried a line ending that nobody selected."
    terminal = a_terminal("hello world\r\nsecond")
    app = await press(terminal, "g", "g", "0", "v", "$", "y", vi=True)
    assert app.clipboard.get_data().text == "hello world"


async def test_the_caret_stops_at_the_last_character_of_the_last_line():
    "There is no break under it, and a selected cell was drawn there."
    terminal = a_terminal("hello world")
    app = await press(terminal, "0", "$", vi=True)
    assert terminal.copy_views.of(app).buffer.document.cursor_position == len("hello world") - 1


async def test_an_empty_line_holds_the_caret_at_its_start():
    "There is nowhere else to stand, and the line before is not it."
    terminal = a_terminal("one\r\n\r\nthree")
    app = await press(terminal, "g", "g", "j", "$", vi=True)
    assert terminal.copy_views.of(app).buffer.document.cursor_position_row == 1
    assert terminal.copy_views.of(app).buffer.document.cursor_position_col == 0


async def test_emacs_keys_keep_the_caret_past_the_last_character():
    "tmux clamps for vi mode keys alone, and this is the other half."
    terminal = a_terminal("hello world\r\nsecond")
    app = await press(terminal, Keys.ControlP, Keys.ControlE)
    assert terminal.copy_views.of(app).buffer.document.cursor_position == len("hello world")


async def test_copy_mode_opens_where_the_pane_is_with_vi_keys():
    """
    The caret opens past the last character of a shell prompt, which is
    where the next character goes. Only a move of the caret is clamped.
    Lillecarl/pymux#189.
    """
    terminal = a_terminal("one\r\ntwo\r\nthree")
    app = await press(terminal, vi=True)
    assert _cursor(terminal.copy_views.of(app)) == (2, 5)


async def test_leaving_copy_mode_forgets_what_was_styled():
    """
    The view goes, and what it styled goes with it: the next copy mode
    copies the buffer again, as it stands then.

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
        view = terminal.enter_copy_mode()
        assert view.styled_line(0)
        terminal.exit_copy_mode()

    assert terminal.copy_views.of(app) is None


# ----------------------------------------------------------------------
# The wheel. Lillecarl/pymux#422.


def a_wheel(control, kind):
    from prompt_toolkit.data_structures import Point
    from prompt_toolkit.mouse_events import MouseButton, MouseEvent

    return control.mouse_handler(
        MouseEvent(
            position=Point(x=0, y=0),
            event_type=kind,
            button=MouseButton.NONE,
            modifiers=frozenset(),
        )
    )


def test_the_wheel_moves_the_caret_and_the_bottom_leaves():
    """
    Wheel up in copy mode moves the caret up, and the wheel down that
    brings it back to the bottom leaves copy mode: the live screen is
    where the program stands, and the way back to it is the same wheel.
    So does a wheel down that finds the caret at the bottom already.
    """
    terminal = a_terminal("\r\n".join("row %d" % n for n in range(40)))
    app = DummyApplication()
    app.layout = Layout(terminal.container)

    with set_app(app):
        view = terminal.enter_copy_mode()
        bottom = view.buffer.cursor_position

        a_wheel(view.control, MouseEventType.SCROLL_UP)
        assert view.buffer.cursor_position < bottom

        a_wheel(view.control, MouseEventType.SCROLL_DOWN)
        assert view.buffer.cursor_position == bottom
        assert terminal.copy_views.of(app) is None

        view = terminal.enter_copy_mode()
        a_wheel(view.control, MouseEventType.SCROLL_DOWN)
        assert terminal.copy_views.of(app) is None


# ----------------------------------------------------------------------
# What a copy holds, and what it only draws. Lillecarl/pymux#449.


def test_a_placeholder_cell_draws_a_blank_and_copies_itself():
    """
    A cell of an image holds a character no font has. The pane blots it
    out, because the embedder draws the image over it. Copy mode has no
    image, so it draws a blank too, underlined to say the cell is not a
    space a program wrote -- and the document keeps the placeholder, so
    a copy carries it.
    """
    terminal = a_terminal("AB" + PLACEHOLDER + chr(0x0305) + "CD")

    style, text = terminal.copy_view.styled_line(0)[2]
    assert text == " " + chr(0x0305)
    assert "underline" in style
    assert PLACEHOLDER + chr(0x0305) in terminal.copy_view.buffer.document.text


def test_a_displayed_line_holds_as_many_characters_as_its_document():
    """
    prompt_toolkit puts a selection on a line by counting the characters
    of the display, so a displayed line must hold as many as its line of
    the document. The stand-in for a cell of an image keeps the marks
    that carry its row and column for this reason.
    """
    terminal = a_terminal("AB" + PLACEHOLDER + chr(0x0305) + chr(0x030D) + "CD")

    document = terminal.copy_view.buffer.document
    for number, line in enumerate(document.lines):
        displayed = sum(len(text) for _, text in terminal.copy_view.styled_line(number))
        assert displayed == len(line)


def test_a_non_breaking_space_is_copied_itself():
    """
    prompt_toolkit marks a non-breaking space with `class:nbsp` when it
    draws it, and the mark is a drawing and not text. The document keeps
    the character, so a copy carries U+00A0 and no underline.
    """
    terminal = a_terminal("a\xa0b")

    assert terminal.copy_view.styled_line(0)[1][1] == "\xa0"
    assert "a\xa0b" in terminal.copy_view.buffer.document.text


def test_a_control_character_is_copied_as_it_stands():
    """
    A control should never be in a cell -- the parser eats those -- and
    the pane draws a blank for one that is. Copy mode keeps the byte and
    prompt_toolkit draws its own stand-in over it.
    """
    terminal = a_terminal("ab")
    buffer = terminal.terminal_control.screen.page.data_buffer
    buffer[0][1] = WrittenCell("\x01", buffer[0][0].appearance)
    terminal.copy_view.freeze()

    assert terminal.copy_view.styled_line(0)[1] == ("", "\x01")
    assert "\x01" in terminal.copy_view.buffer.document.text


# ----------------------------------------------------------------------
# A copy mode for each application. Lillecarl/pymux#470.


def _an_application(terminal):
    app = DummyApplication()
    app.layout = Layout(terminal.container)
    return app


async def test_one_application_reads_the_history_and_another_watches():
    """
    pymux puts one pane in the layout of every client, and each client
    is an application. Copy mode is the one who opened it's, so the
    other still has the screen and the keyboard of the pane.
    """
    terminal = Terminal(backend=NoBackend())
    terminal.terminal_control.create_content(COLUMNS, LINES)
    reading, watching = _an_application(terminal), _an_application(terminal)

    with set_app(reading):
        terminal.enter_copy_mode()
        shown = reading.layout.current_window

    assert shown is terminal.copy_views.of(reading).window
    assert terminal.copy_views.of(watching) is None
    with set_app(watching):
        assert terminal.is_copying is False
        assert terminal.terminal_window in watching.layout.find_all_windows()
        assert terminal.copy_views.of(reading).window not in watching.layout.find_all_windows()


async def test_the_program_writes_on_under_copy_mode():
    """
    Copy mode reads a copy, so the program is not stopped for it: what
    it writes reaches the screen, and the history a person is reading
    stays as it was when they opened it. tmux clones the pane's screen
    the same way (`window_copy_init`).
    """
    terminal = a_terminal("first\r\nsecond")
    control = terminal.terminal_control
    view = terminal.copy_view
    styled = view.styled_line(1)

    assert not control.process.suspended
    control.stream.feed("\rSECOND\r\n" + "".join("more %d\r\n" % number for number in range(LINES)))

    assert view.buffer.document.text.splitlines()[:2] == ["first", "second"]
    assert view.styled_line(1) is styled
    assert "".join(text for _, text in styled) == "second"
    assert any(
        "more" in "".join(cell.char for cell in row.values()) for row in control.screen.page.data_buffer.values()
    )


def test_a_row_of_the_screen_is_copied_and_not_shared():
    """
    The program writes into a row of the screen in place, so the copy
    holds a row of its own for each of those. A row of the history it
    never writes again, so that one is shared.
    """
    terminal = a_terminal("".join("row %d\r\n" % number for number in range(20)))
    screen = terminal.screen
    live, frozen = screen.page.data_buffer, terminal.copy_view.page.data_buffer

    history = min(live)
    assert history < screen.line_offset
    assert frozen[history] is live[history]
    assert frozen[screen.line_offset] is not live[screen.line_offset]
    assert dict(frozen[screen.line_offset]) == dict(live[screen.line_offset])


async def test_an_application_that_goes_takes_its_copy_mode_with_it():
    """
    A client that detaches in copy mode leaves no copy of the history
    behind. The views are keyed weakly by the application, which only
    works while nothing in a view holds the application itself.
    """
    terminal = a_terminal("".join("row %d\r\n" % number for number in range(20)))
    app = _an_application(terminal)
    with set_app(app):
        terminal.enter_copy_mode()
    view_gone = weakref.ref(terminal.copy_views.of(app))
    app_gone = weakref.ref(app)

    del app
    gc.collect()
    assert app_gone() is None
    # The view is a cycle of its own, and it is free only once the
    # collection that freed the application has dropped its entry.
    gc.collect()

    assert view_gone() is None
    assert [application for application, _ in terminal.copy_views.items() if application is not None] == []


def _refresh_after(terminal, app, written: str, vi=False) -> None:
    "The program writes under copy mode, and then the person presses `r`."
    terminal.terminal_control.stream.feed(written)
    with set_app(app):
        if vi:
            app.vi_state.input_mode = InputMode.NAVIGATION
        app.key_processor.feed(KeyPress("r", "r"))
        app.key_processor.process_keys()


@pytest.mark.parametrize("vi", [False, True])
async def test_r_takes_a_new_copy_with_the_caret_on_its_line(vi):
    "tmux's `refresh-from-pane`, which both of its tables bind to `r`."
    terminal = Terminal(backend=NoBackend())
    terminal.terminal_control.create_content(COLUMNS, LINES)
    terminal.terminal_control.stream.feed("".join("row %d\r\n" % number for number in range(10)))
    app = _an_application(terminal)
    if vi:
        app.editing_mode = EditingMode.VI
    with set_app(app):
        view = terminal.enter_copy_mode()
    document = view.buffer.document
    view.buffer.cursor_position = document.translate_row_col_to_index(3, 2)

    _refresh_after(terminal, app, "".join("more %d\r\n" % number for number in range(10)), vi=vi)

    assert terminal.copy_views.of(app) is view
    assert "more 9" in view.buffer.text
    assert view.buffer.document.current_line == "row 3"
    assert view.buffer.document.cursor_position_col == 2


async def test_the_corner_says_when_the_pane_has_newer_output():
    terminal = Terminal(backend=NoBackend())
    terminal.terminal_control.create_content(COLUMNS, LINES)
    terminal.terminal_control.stream.feed("first\r\nsecond")
    app = _an_application(terminal)
    with set_app(app):
        view = terminal.enter_copy_mode()
    assert view._position_formatted_text() == "[2/2]"

    terminal.terminal_control.stream.feed("\r\nthird")
    assert view._position_formatted_text() == "[2/2] r for newer"

    _refresh_after(terminal, app, "")
    assert view._position_formatted_text() == "[2/3]"


async def test_r_drops_the_selection():
    "Its positions name the old copy, and the new one holds other text there."
    terminal = Terminal(backend=NoBackend())
    terminal.terminal_control.create_content(COLUMNS, LINES)
    terminal.terminal_control.stream.feed("first\r\nsecond")
    app = _an_application(terminal)
    with set_app(app):
        view = terminal.enter_copy_mode()
    view.buffer.cursor_position = 0
    view.buffer.start_selection()

    _refresh_after(terminal, app, "\r\nthird")

    assert view.buffer.selection_state is None
    assert view.buffer.text.endswith("third")


async def test_r_on_a_line_the_history_dropped_goes_to_the_first_line():
    terminal = Terminal(backend=NoBackend())
    control = terminal.terminal_control
    control.create_content(COLUMNS, LINES)
    control.screen.get_history_limit = lambda: 4
    control.stream.feed("".join("row %d\r\n" % number for number in range(8)))
    app = _an_application(terminal)
    with set_app(app):
        view = terminal.enter_copy_mode()
    view.buffer.cursor_position = 0

    # The screen trims its history once in a hundred lines.
    _refresh_after(terminal, app, "".join("more %d\r\n" % number for number in range(120)))

    assert view.buffer.document.cursor_position_row == 0
    assert "row 0" not in view.buffer.text


def _a_shell_session() -> Terminal:
    """
    Three prompts, each marked where a shell's "OSC 133 ; A" would, and
    the output of each marked where "C" would. The second
    prompt is longer than the pane, so the pane wraps it, and the third
    scrolls the first into the history.
    """
    terminal = Terminal(backend=NoBackend())
    control = terminal.terminal_control
    control.create_content(COLUMNS, LINES)
    screen, stream = control.screen, control.stream
    for prompt, output in (("$ one", "1\r\n1"), ("$ " + "two " * 8, "2"), ("$ three", "3")):
        screen.mark_row(RowMark.PROMPT)
        stream.feed(prompt + "\r\n")
        if output:
            screen.mark_row(RowMark.OUTPUT)
            stream.feed(output + "\r\n")
    terminal.enter_copy_mode()
    return terminal


def _caret_line(view) -> str:
    document = view.buffer.document
    assert document.cursor_position_col == 0
    return document.current_line


def test_previous_prompt_goes_up_one_prompt_at_a_time():
    view = _a_shell_session().copy_view
    view.buffer.cursor_position = len(view.buffer.text)

    view.jump_to_mark(RowMark.PROMPT, down=False)
    assert _caret_line(view) == "$ three"
    view.jump_to_mark(RowMark.PROMPT, down=False)
    assert _caret_line(view).startswith("$ two two")
    view.jump_to_mark(RowMark.PROMPT, down=False)
    assert _caret_line(view) == "$ one"

    # Past the first, it stays.
    view.jump_to_mark(RowMark.PROMPT, down=False)
    assert _caret_line(view) == "$ one"


def test_next_prompt_with_output_goes_to_where_output_starts():
    view = _a_shell_session().copy_view
    view.buffer.cursor_position = 0

    view.jump_to_mark(RowMark.OUTPUT, down=True)
    assert _caret_line(view) == "1"
    view.jump_to_mark(RowMark.OUTPUT, down=True)
    assert _caret_line(view) == "2"
    view.jump_to_mark(RowMark.PROMPT, down=True)
    assert _caret_line(view) == "$ three"
