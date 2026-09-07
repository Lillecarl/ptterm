"""
The layout engine. This builds the prompt_toolkit layout.
"""
import os
from typing import Callable, Iterable, List

from prompt_toolkit.application.current import get_app, get_app_or_none
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_selection
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import (
    BufferControl,
    FormattedTextControl,
    UIContent,
    UIControl,
)
from prompt_toolkit.layout.processors import (
    HighlightIncrementalSearchProcessor,
    HighlightSearchProcessor,
    HighlightSelectionProcessor,
    Processor,
    Transformation,
)
from prompt_toolkit.layout.screen import Char, Point
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.selection import SelectionType
from prompt_toolkit.token import KeepWhitespace
from prompt_toolkit.utils import Event, is_windows
from prompt_toolkit.widgets.toolbars import SearchToolbar

from ptyhost import Process
from ptyhost.backends import Backend

from pyte.environment import prepare
from pyte.images import ASSUMED_CELL_HEIGHT, ASSUMED_CELL_WIDTH
from pyte.placeholders import PLACEHOLDER
from pyte.cells import Cell, WrittenCell
from pyte.page import TextLine
from pyte.screen import Screen
from pyte.streams import Stream

from .style import style_of

__all__ = ["Terminal"]

E = KeyPressEvent


#: Bit six of the button says the event came from the wheel, so the two
#: wheel directions are the button numbers 64 and 65. kitty calls it
#: `SCROLL_BUTTON_INDICATOR` in `kitty/mouse.c`.
_WHEEL = 1 << 6

#: A release is button three in every protocol older than SGR. kitty:
#: "action == RELEASE && mouse_tracking_protocol < SGR_PROTOCOL".
_RELEASE_BUTTON = 3

#: X10 and urxvt shift the button by 32, so that X10 can write it as a
#: printable byte. SGR does not: it writes the number as text, which is
#: the reason that protocol exists. kitty adds the same 32 in
#: `encode_mouse_event_impl`, for the urxvt and the X10 cases only.
_BUTTON_OFFSET = 32

#: X10 writes each coordinate as one byte as well, one based and
#: shifted by the same 32. So a zero based column travels as `x + 33`.
_COORDINATE_OFFSET = _BUTTON_OFFSET + 1

#: How far to the right an X10 report reaches.
#:
#: This is not X10's own limit, which is 223: a byte holds `223 + 32`
#: and no more, and kitty writes exactly that as
#: "if (x > 223 || y > 223) return 0". It is also one column too
#: generous for what a pane can spell, because column 95 becomes
#: `chr(128)`, which UTF-8 writes as two bytes. Both halves of that are
#: Lillecarl/pymux#139.
_X10_LAST_COLUMN = 96

#: The button that SGR writes, and the final byte that says whether the
#: press went down or came up. SGR is the only protocol that tells them
#: apart that way, and the only one that leaves the button unshifted.
_SGR_BUTTONS = {
    MouseEventType.MOUSE_DOWN: (0, "M"),
    MouseEventType.MOUSE_UP: (0, "m"),
    MouseEventType.SCROLL_UP: (_WHEEL, "M"),
    MouseEventType.SCROLL_DOWN: (_WHEEL + 1, "M"),
}

#: The button that urxvt and X10 write. One table, because the two
#: protocols encode the same number and differ only in how they spell
#: it: urxvt as text, X10 as one byte.
_SHIFTED_BUTTONS = {
    MouseEventType.MOUSE_DOWN: _BUTTON_OFFSET,
    MouseEventType.MOUSE_UP: _RELEASE_BUTTON + _BUTTON_OFFSET,
    MouseEventType.SCROLL_UP: _WHEEL + _BUTTON_OFFSET,
    MouseEventType.SCROLL_DOWN: _WHEEL + 1 + _BUTTON_OFFSET,
}


#: The characters that must not reach the terminal of the user as they
#: stand. prompt_toolkit lists them because it draws them for a person
#: who is typing; the reason here is different, and so is the answer.
#: The non-breaking space is left out: it is a character to draw, not a
#: control to keep out.
_NOT_FOR_A_SCREEN = frozenset(Char.display_mappings) - {"\xa0"}


def cursor_offset(screen) -> int:
    """
    How many characters stand before the cursor on its own line.

    prompt_toolkit places a cursor by the number of characters before
    it, and not by the column. The two differ where a double width
    character is drawn, which is why this counts rather than reads the
    position.

    **The column is the one the cursor stands on, and never the one it
    waits to wrap into.** A character in the last column leaves the
    cursor one column further here, and that column is not on the line.
    prompt_toolkit answers a cursor outside the line by scrolling the
    window sideways to bring it into view, and then every row of the
    pane is drawn one column to the left for as long as the scroll
    lasts. A whole pane moves because one character reached the edge.

    `reported_column` is the same fold that a program reads with DSR, so
    a pane draws the cursor where a program is told it stands.
    """
    row = screen.page.data_buffer[screen.pt_cursor_position.y]
    return len(
        "".join(row[x].char for x in range(0, screen.reported_column))
    )


def _visible_char(char: str) -> str:
    """
    What to draw for a cell.

    A unicode placeholder stands for a cell of an image, and the
    embedder draws that image itself. The character must not reach the
    screen: a terminal that does not know it paints a box, and the
    combining characters that carry the row and the column pile up on
    top of it. A space keeps the cell, and the image covers it.

    A control character is drawn as a blank. It should never be in a
    cell at all, because the parser consumes those, and one that is
    there must not reach the terminal of the user: that terminal would
    read it as a control of its own and the screen after it is anybody's
    guess. prompt_toolkit draws "^@" in blue for the same characters,
    which is a thing to look at rather than a thing to be safe.

    A non-breaking space goes through as it stands. It is a printable
    character that a program wrote on purpose, and the content of this
    control says `apply_display_mappings=False`, which is what stops
    prompt_toolkit from marking it up.
    """
    if char.startswith(PLACEHOLDER):
        return " "
    if char in _NOT_FOR_A_SCREEN:
        return " "
    return char


class _TerminalControl(UIControl):
    #: How many rows this control remembers having drawn.
    #:
    #: A pane draws the rows of the screen, so it remembers about a
    #: hundred of them however deep the history goes. It fills this only
    #: in copy mode, where a person scrolls through the history itself
    #: and every row they pass is a row that was drawn. Emptying the
    #: whole of it costs one frame, and a frame is what this saves
    #: thousands of.
    #:
    #: Ten thousand is a scrollback depth that people configure: tmux
    #: keeps two thousand by default and kitty is commonly set to fifty
    #: thousand, so `tests/measure_instructions.py` measures at 2000,
    #: 10000 and 50000. Under this depth the map holds a whole history
    #: and is never emptied. Over it, a person who scrolls the whole
    #: way pays one frame each time it fills, which is the trade this
    #: number picks.
    _REMEMBER_AT_MOST = 10 * 1000

    def __init__(
        self,
        backend: Backend,
        done_callback: Callable[[], None] | None = None,
        bell_func: Callable[[], None] | None = None,
        osc_func: Callable[[str, str], None] | None = None,
        resize_func: Callable[[int | None, int | None], None] | None = None,
        may_resize: Callable[[], bool] | None = None,
        get_history_limit: Callable[[], int] | None = None,
    ) -> None:

        def has_priority() -> bool:
            # Give priority to the processing of this terminal output, if this
            # user control has the focus.
            app_or_none = get_app_or_none()

            if app_or_none is None:
                # The application has terminated before this process ended.
                return False

            return app_or_none.layout.has_focus(self)

        # The screen belongs to the front end and not to the pty: a
        # `Process` runs a program and pumps its bytes, and what those
        # bytes mean is decided here. Lillecarl/pymux#85.
        self.screen = Screen(
            0,
            0,
            write_process_input=lambda data: self.process.write_input(data),
            bell_func=bell_func,
            osc_func=osc_func,
            resize_func=resize_func,
            may_resize=may_resize,
            # How deep the scrollback goes. The embedder decides, because
            # it is the embedder that offers the option: tmux and pymux
            # both call it `history-limit`. A pane that keeps the answer
            # in a function reads it again on every cleanup, so a change
            # to the option reaches a pane that is already running.
            get_history_limit=get_history_limit,
        )
        self.stream = Stream(self.screen)
        self.stream.attach(self.screen)

        self.process = Process(
            backend=backend,
            receive=self.stream.feed,
            invalidate=lambda: self.on_content_changed.fire(),
            done_callback=done_callback,
            has_priority=has_priority,
        )

        self.on_content_changed = Event(self)
        self._running = False

        # What this control drew for each row, and the write count of
        # the screen that it drew it at. A row whose count has not
        # moved is a row it does not build again. The state is here and
        # not on the screen, because a screen has more than one reader
        # and no way to know how many. Lillecarl/pymux#126.
        self._drawn: dict[int, StyleAndTextTuples] = {}
        self._drawn_at: dict[int, int] = {}
        self._drawn_reversed = False

    def set_size(self, width: int, height: int) -> None:
        "Tell the pty and the screen how big the pane is."
        self.process.set_size(width, height)
        self.screen.resize(lines=height, columns=width)
        self.screen.lines = height
        self.screen.columns = width

    def create_content(self, width: int, height: int) -> UIContent:
        # Report dimensions to the process.
        self.set_size(width, height)

        # The first time that this user control is rendered. Keep track of the
        # 'app' object and start the process.
        if not self._running:
            self.process.start()
            self._running = True

        if not self.screen:
            return UIContent()

        page = self.screen.page
        pt_cursor_position = self.screen.pt_cursor_position
        data_buffer = page.data_buffer
        cursor_y = pt_cursor_position.y

        cursor_x = cursor_offset(self.screen)

        # DECSCNM reverses the screen, and `_Window` paints that over the
        # whole pane. A cell that a program already reversed with "SGR 7"
        # turns the other way, so the two cancel out. libvterm calls this
        # an xor, and it is the same answer.
        reverse_video = self.screen.has_reverse_video

        # DECSCNM belongs to the whole screen and not to a row, so a
        # line built under one answer says nothing about the other.
        # Nothing else outside a row reaches `get_line`.
        if reverse_video != self._drawn_reversed:
            self._drawn.clear()
            self._drawn_at.clear()
            self._drawn_reversed = reverse_video

        # The history grows and the rows that leave it never come back,
        # so what is remembered of them is dead weight. Emptying the
        # whole of it costs one frame, and a frame is what this saves
        # thousands of.
        if len(self._drawn) > self._REMEMBER_AT_MOST:
            self._drawn.clear()
            self._drawn_at.clear()

        written_at = self.screen.written_at
        # A row with no count of its own carries the one that
        # `touch_everything` last set, so a reset or a page swap moves
        # every row at once and costs nothing to say.
        everything_at = self.screen.everything_at
        drawn = self._drawn
        drawn_at = self._drawn_at

        def fragment(cell: Cell) -> tuple[str, str]:
            """
            The style and the character that one cell draws with.

            A blank that a program wrote carries `KeepWhitespace`. The
            renderer drops a blank at the end of a row when nothing
            styles it, so that a person who copies the output gets no
            trailing spaces. That guess is wrong for a pane: a space a
            program wrote is content, and a terminal that reads its own
            screen back has to find the column.

            The test reads what the cell draws and not what it holds.
            The stand-in for a cell of an image and the blank for a
            control are both cells that a program made, and both keep
            their column.
            """
            char = _visible_char(cell.char)
            style = style_of(cell.appearance)
            if reverse_video and cell.appearance.rendition.reverse:
                style += " noreverse"
            if char == " " and isinstance(cell, WrittenCell):
                style += " " + KeepWhitespace
            return style, char

        def build(number: int) -> StyleAndTextTuples:
            row = data_buffer[number]
            empty = True
            if row:
                max_column = max(row)
                empty = False
            else:
                max_column = 0

            if number == cursor_y:
                max_column = max(max_column, cursor_x)
                empty = False

            if empty:
                return [("", " ")]
            else:
                cells = [row[i] for i in range(max_column + 1)]
                return [fragment(cell) for cell in cells]

        def get_line(number: int) -> StyleAndTextTuples:
            """
            One row, built once and kept until the screen writes it
            again. Lillecarl/pymux#126.

            The screen counts every write it makes to a row, and this
            keeps the count it built each row at. A count that has not
            moved is a row that has not changed, and a frame after a
            program wrote one line then builds one line.

            **The row the cursor stands on is never kept.** It is the
            one row whose answer depends on something outside it: the
            cursor pads it out to the column the cursor stands in, so
            that prompt_toolkit places the cursor on the line rather
            than scrolling the pane sideways to reach it.

            The list is handed over as it is and not copied.
            prompt_toolkit reads it, and the one place that changes a
            line -- the horizontal scroll in `Window._copy_body` --
            calls `explode_text_fragments` first, which builds a list
            of its own.
            """
            if number == cursor_y:
                return build(number)

            version = written_at.get(number, everything_at)
            if drawn_at.get(number) != version:
                drawn[number] = build(number)
                drawn_at[number] = version
            return drawn[number]

        # The screen is the rows from `line_offset` to `max_y`, and the
        # buffer can end above `max_y`: an erase with no background
        # drops the row it clears, so "CSI 1000 M" at the top of a full
        # screen takes every row below it away.
        #
        # prompt_toolkit then reads a document shorter than the window
        # and scrolls back to the top, because it does not scroll past
        # the end. Lines that had left the screen come back. So the
        # count is what the screen occupies, and never what is left in
        # the buffer.
        #
        # `highest_row` says which of the two it is without reading the
        # buffer, which holds the history. Lillecarl/pymux#130.
        line_count = self.screen.highest_row() + 1

        return UIContent(
            get_line,
            line_count=line_count,
            show_cursor=page.show_cursor,
            cursor_position=Point(x=cursor_x, y=cursor_y),
            # A terminal draws what the program in it drew. Every
            # character on this screen was chosen by that program, so
            # none of them is a character to mark up for a reader: a
            # non-breaking space is one the program wrote on purpose,
            # and prompt_toolkit would otherwise draw an underlined
            # yellow space in its place.
            apply_display_mappings=False,
        )

    def get_key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add(Keys.Any)
        def handle_key(event):
            """
            Handle any key binding -> write it to the stdin of this terminal.
            """
            key_press = event.key_sequence[0]
            if key_press.data:
                # Forward the raw data. It preserves modifiers that
                # prompt_toolkit splits into multiple keys (like
                # alt+char), so that they can be re-encoded for the
                # keyboard mode of this pane. (The empty-data presses
                # are the remainders of such split sequences.)
                self.process.write_input(self.screen.encode_key(key_press.data))

        @bindings.add(Keys.BracketedPaste)
        def _(event):
            self.process.write_input(self.screen.wrap_paste(event.data))

        return bindings

    def get_invalidate_events(self) -> Iterable[Event]:
        yield self.on_content_changed

    def mouse_handler(self, mouse_event) -> None:
        """
        Handle mouse events in a pane. A click in a non-active pane will select
        it. A click in active pane will send the mouse event to the application
        running inside it.
        """
        app = get_app()

        process = self.process
        x = mouse_event.position.x
        y = mouse_event.position.y

        # The containing Window translates coordinates to the absolute position
        # of the whole screen, but in this case, we need the relative
        # coordinates of the visible area.
        y -= self.screen.line_offset

        if not app.layout.has_focus(self):
            # Focus this process when the mouse has been clicked.
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                app.layout.focus(self)
        else:
            # Already focussed, send event to application when it requested
            # mouse support.
            if self.screen.sgr_mouse_support_enabled:
                # Xterm SGR mode: the button as text, and the final
                # byte says press or release.
                try:
                    ev, m = _SGR_BUTTONS[mouse_event.event_type]
                except KeyError:
                    pass
                else:
                    # `reply_csi` and not a literal "\x1b[": a mouse
                    # report is a C1 control that the terminal sends on
                    # its own, and S8C1T asks for one byte in front of
                    # it. xterm writes every one of them through
                    # `unparseputc1`, which is not a query only path.
                    self.screen.reply_csi(f"<{ev};{x + 1};{y + 1}{m}")

            elif self.screen.urxvt_mouse_support_enabled:
                # Urxvt mode: the shifted button as text, and always
                # "M". A release is button three, so the two are told
                # apart by the button and not by the final byte.
                try:
                    ev = _SHIFTED_BUTTONS[mouse_event.event_type]
                except KeyError:
                    pass
                else:
                    self.screen.reply_csi(f"{ev};{x + 1};{y + 1}M")

            elif self.screen.mouse_support_enabled:
                # X10: the same shifted button, written as one byte,
                # and the two coordinates after it.
                if x < _X10_LAST_COLUMN and y < _X10_LAST_COLUMN:
                    try:
                        ev = _SHIFTED_BUTTONS[mouse_event.event_type]
                    except KeyError:
                        pass
                    else:
                        self.screen.reply_csi(
                            "M%s%s%s"
                            % (
                                chr(ev),
                                chr(x + _COORDINATE_OFFSET),
                                chr(y + _COORDINATE_OFFSET),
                            )
                        )

    def is_focusable(self) -> bool:
        return not self.process.suspended


class _Window(Window):
    """ """

    def __init__(self, terminal_control: _TerminalControl, **kw) -> None:
        self.terminal_control = terminal_control
        kw.setdefault("style", self._pane_style)
        super().__init__(**kw)

    def _pane_style(self) -> str:
        """
        The style of the whole pane, blank cells included.

        DECSCNM ("CSI ? 5 h") reverses the screen, and the screen is
        more than the cells a program wrote: an empty row and the space
        after the last character both turn as well. prompt_toolkit fills
        the area of a window with the style of that window before it
        writes the content over it, so this is the one place that
        reaches every cell of the pane.

        `create_content` takes the reverse off a cell that already
        carries one, which is the other half. Lillecarl/pymux#95.
        """
        screen = self.terminal_control.screen
        if screen is not None and screen.has_reverse_video:
            return "reverse"
        return ""

    def write_to_screen(self, *a, **kw) -> None:
        # Make sure that the bottom of the terminal is always visible.
        screen = self.terminal_control.screen

        # NOTE: the +1 is required because max_y starts counting at 0, while
        #       lines counts the numbers of lines, starting at 1 for one line.
        self.vertical_scroll = screen.max_y - screen.lines + 1

        super().write_to_screen(*a, **kw)


def _in_the_child(
    before_exec_func: Callable[[], None] | None,
) -> Callable[[], None]:
    """
    What runs in the child, between the fork and the exec.

    The program runs on the screen of this widget and not in the
    terminal that the application itself runs in, so the environment
    has to say which one it is. Nothing else knows both: `pyte` has no
    child to set an environment for, and `ptyhost` runs a program and
    has no opinion on what parses the bytes. This widget owns a screen
    and a `Process`, so this is the layer. Lillecarl/pymux#125.

    The hook of the caller runs last, so an embedder can still say
    something different. pymux does: it has an option for the name.
    """

    def hook() -> None:
        prepare(os.environ)
        if before_exec_func is not None:
            before_exec_func()

    return hook


def create_backend(
    command: List[str], before_exec_func: Callable[[], None] | None
) -> Backend:
    if is_windows():
        from ptyhost.backends.win32 import Win32Backend

        return Win32Backend()
    else:
        from ptyhost.backends.posix import PosixBackend

        # The size of a cell goes into the size of the pty, so that a
        # program that draws images reads the same answer there as
        # "CSI 16 t" gives it.
        return PosixBackend.from_command(
            command,
            before_exec_func=_in_the_child(before_exec_func),
            cell=(ASSUMED_CELL_WIDTH, ASSUMED_CELL_HEIGHT),
        )


class Terminal:
    """
    Terminal widget for use in a prompt_toolkit layout.

    :param command: List of command line arguments.
        For instance: `['python', '-c', 'print("test")']`
    :param before_exec_func: Function which is called in the child process,
        right before calling `exec`. Useful for instance for changing the
        current working directory or setting environment variables.
    :param osc_func: Called with the code and the payload of an OSC
        sequence that only the terminal of the user can serve. (The
        clipboard, a notification, the shape of the pointer.)
    :param resize_func: Called with the lines and the columns that the
        program asks for, when it sends DECSLPP or a window resize.
        Either one is None when the program leaves that side alone. A
        pane cannot resize itself, so the embedder decides.
    :param may_resize: Returns whether the embedder would grant such an
        ask. The private modes that only exist where a program can have
        a different page go away when it says no, so a program learns at
        once instead of laying its output out for room it will not get.
    :param get_history_limit: Returns how many rows of scrollback this
        pane keeps. The default is two thousand, which is what tmux
        keeps. It is a function and not a number, so the option can
        change while the pane runs.
    """

    def __init__(
        self,
        command=["/bin/bash"],
        before_exec_func=None,
        backend: Backend | None = None,
        bell_func: Callable[[], None] | None = None,
        style: str = "",
        width: int | None = None,
        height: int | None = None,
        done_callback: Callable[[], None] | None = None,
        osc_func: Callable[[str, str], None] | None = None,
        resize_func: Callable[[int | None, int | None], None] | None = None,
        may_resize: Callable[[], bool] | None = None,
        get_history_limit: Callable[[], int] | None = None,
    ) -> None:
        if backend is None:
            backend = create_backend(command, before_exec_func)

        self.terminal_control = _TerminalControl(
            backend=backend,
            bell_func=bell_func,
            osc_func=osc_func,
            resize_func=resize_func,
            may_resize=may_resize,
            done_callback=done_callback,
            get_history_limit=get_history_limit,
        )

        self.terminal_window = _Window(
            terminal_control=self.terminal_control,
            content=self.terminal_control,
            wrap_lines=False,
        )

        # The keys of copy mode.
        #
        # **They live with the copy buffer**, because the copy buffer is
        # what they drive. pymux held four of them and read a flag that
        # nothing had set since copy mode moved here, so `q`, `escape`
        # and `v` did nothing at all and only ctrl-c left copy mode.
        # Lillecarl/pymux#133.
        kb = KeyBindings()

        @kb.add("c-c")
        @kb.add("q")
        @kb.add("escape")
        @kb.add("enter", filter=~has_selection)
        def _exit(event):
            "Leave copy mode. tmux leaves on all four of these."
            self.exit_copy_mode()

        @kb.add("space")
        def _reset_selection(event):
            "Reset selection."
            event.current_buffer.start_selection()

        @kb.add("enter", filter=has_selection)
        def _copy_selection(event):
            "Copy selection."
            data = event.current_buffer.copy_selection()
            event.app.clipboard.set_data(data)

        @kb.add("v", filter=has_selection)
        def _toggle_selection_type(event):
            "Swap between selecting characters and selecting lines."
            selection_state = event.current_buffer.selection_state
            if selection_state is None:
                return
            if selection_state.type == SelectionType.CHARACTERS:
                selection_state.type = SelectionType.LINES
            else:
                selection_state.type = SelectionType.CHARACTERS

        self.search_toolbar = SearchToolbar(
            forward_search_prompt="Search down: ", backward_search_prompt="Search up: "
        )

        self.copy_buffer = Buffer(read_only=True)
        self.copy_buffer_control = BufferControl(
            buffer=self.copy_buffer,
            search_buffer_control=self.search_toolbar.control,
            include_default_input_processors=False,
            input_processors=[
                _UseStyledTextProcessor(self),
                HighlightSelectionProcessor(),
                HighlightSearchProcessor(),
                HighlightIncrementalSearchProcessor(),
            ],
            preview_search=True,  # XXX: not sure why we need twice preview_search.
            key_bindings=kb,
        )

        #: Whether the pane was in reverse video when copy mode opened.
        #: `enter_copy_mode` reads it, because the process is suspended
        #: after that and the mode cannot change.
        self.copy_reverse_video = False

        # The document holds the lines a program wrote, so a line that
        # the pane wrapped is one line here. The window wraps it again
        # at the width it has, which is what the pane did, so a person
        # sees the same shape and the copy holds no break that the
        # program did not write. Lillecarl/pymux#135.
        self.copy_window = Window(
            content=self.copy_buffer_control,
            wrap_lines=True,
            style=self._copy_style,
        )

        self.is_copying = False

        #: The lines of the buffer that copy mode is showing, and the
        #: ones of them that have been styled. `styled_line` says why
        #: they are built one at a time.
        self._copy_lines: list[TextLine] = []
        self._styled_lines: dict[int, StyleAndTextTuples] = {}

        @Condition
        def is_copying() -> bool:
            return self.is_copying

        self.container = FloatContainer(
            content=HSplit(
                [
                    # Either show terminal window or copy buffer.
                    VSplit(
                        [  # XXX: this nested VSplit should not have been necessary,
                            # but the ConditionalContainer which width can become
                            # zero will collapse the other elements.
                            ConditionalContainer(
                                self.terminal_window, filter=~is_copying
                            ),
                            ConditionalContainer(self.copy_window, filter=is_copying),
                        ]
                    ),
                    ConditionalContainer(self.search_toolbar, filter=is_copying),
                ],
                style=style,
                width=width,
                height=height,
            ),
            floats=[
                Float(
                    top=0,
                    right=0,
                    height=1,
                    content=ConditionalContainer(
                        Window(
                            content=FormattedTextControl(
                                text=self._copy_position_formatted_text
                            ),
                            style="class:copy-mode-cursor-position",
                        ),
                        filter=is_copying,
                    ),
                )
            ],
        )

    def _copy_position_formatted_text(self) -> str:
        """
        Return the cursor position text to be displayed in copy mode.
        """
        render_info = self.copy_window.render_info
        if render_info:
            return f"[{render_info.cursor_position.y + 1}/{render_info.content_height}]"
        else:
            return "[0/0]"

    def _copy_style(self) -> str:
        "The style of the whole copy window, blank cells included."
        return "reverse" if self.copy_reverse_video else ""

    def _copy_cell_style(self, char) -> str:
        """
        The style of one cell of the copy buffer, with DECSCNM folded in.

        A blank that a program wrote carries `KeepWhitespace` here too.
        Copy mode shows the screen of the pane stopped, so it holds the
        same columns the pane holds.
        """
        style = style_of(char.appearance)
        if self.copy_reverse_video and char.appearance.rendition.reverse:
            style += " noreverse"
        if char.char == " " and isinstance(char, WrittenCell):
            style += " " + KeepWhitespace
        return style

    def enter_copy_mode(self) -> None:
        self.terminal_control.process.suspend()
        self.read_the_screen_into_the_copy_buffer()
        self.is_copying = True
        get_app().layout.focus(self.copy_window)

    def read_the_screen_into_the_copy_buffer(self) -> None:
        """
        Put the whole buffer, history and all, into the copy buffer.

        It is a method of its own because it is the work: entering copy
        mode is a suspend, this, and a focus, and this is the part that
        grows with the history. `tests/measure_instructions.py` measures
        it under "history <depth> (copy)". Lillecarl/pymux#131.

        **It reads lines and not rows.** A row is a line cut to fit the
        pane, and a person copying wants the line. So a search crosses
        a wrap, a selection of one line is one line, and the width the
        history was laid out at does not reach the document at all.
        Lillecarl/pymux#135.
        """
        screen = self.terminal_control.screen
        data_buffer = screen.page.data_buffer

        # DECSCNM reverses the whole screen, and copy mode shows the
        # same screen stopped. `_copy_style` paints the reverse over the
        # window, the way `_Window` does for the pane, and a cell that
        # "SGR 7" already reversed turns the other way here. The process
        # is suspended, so the mode cannot change while copy mode is
        # open and reading it once is enough. Lillecarl/pymux#96.
        self.copy_reverse_video = screen.has_reverse_video

        lines: list[TextLine] = []
        if data_buffer:
            lines = screen.page.text_lines(
                min(data_buffer), max(data_buffer)
            )

        text_str = "\n".join(line.text for line in lines)

        self.copy_buffer.set_document(
            Document(text=text_str, cursor_position=len(text_str)), bypass_readonly=True
        )

        self._copy_lines = lines
        self._styled_lines: dict[int, StyleAndTextTuples] = {}

    def styled_line(self, number: int) -> StyleAndTextTuples:
        """
        One line of the copy buffer, as the styles a person sees.

        **It is built when it is asked for, and not before.** A window
        shows a screenful, and the history behind it can be fifty
        thousand rows: styling all of them cost 22,924,756 bytecode
        instructions at that depth, and a person waited for it after
        pressing a key. Lillecarl/pymux#131.

        The answer is kept, because the process is suspended while copy
        mode is open, so no row of the screen can change under it.
        """
        line = self._styled_lines.get(number)
        if line is not None:
            return line

        line = []
        if 0 <= number < len(self._copy_lines):
            shown = self._copy_lines[number]
            # The rows of one line hold one line, so the answer does.
            lines, _ = self.terminal_control.screen.page.unwrap(
                shown.first, shown.last
            )
            for cell in lines[0].cells:
                line.append((self._copy_cell_style(cell), cell.char))
        self._styled_lines[number] = line
        return line

    def exit_copy_mode(self) -> None:
        # Resume process.
        self.terminal_control.process.resume()

        # The lines that were styled belong to the screen that copy mode
        # stopped. The process runs again from here, so they are wrong
        # the moment it writes.
        self._copy_lines = []
        self._styled_lines = {}

        # focus terminal again.
        self.is_copying = False
        get_app().layout.focus(self.terminal_window)

    def __pt_container__(self) -> FloatContainer:
        return self.container

    @property
    def process(self):
        return self.terminal_control.process

    @property
    def screen(self) -> Screen:
        "What the program in this pane has drawn."
        return self.terminal_control.screen


class _UseStyledTextProcessor(Processor):
    """
    In order to allow highlighting of the copy region, we use a preprocessed
    list of (style, text) tuples. This processor returns just that list for the
    given pane.

    This processor should go before all others, because it replaces the list of
    (style, text) tuples.
    """

    def __init__(self, terminal: Terminal) -> None:
        self.terminal = terminal

    def apply_transformation(self, transformation_input) -> Transformation:
        return Transformation(
            self.terminal.styled_line(transformation_input.lineno)
        )
