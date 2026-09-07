"""
The layout engine. This builds the prompt_toolkit layout.
"""
from typing import Callable, Iterable, List

from prompt_toolkit.application.current import get_app, get_app_or_none
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, FilterOrBool, has_selection, to_filter
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
from prompt_toolkit.line_attributes import LineAttribute
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.token import KeepWhitespace
from prompt_toolkit.utils import Event, is_windows
from prompt_toolkit.widgets.toolbars import SearchToolbar

from .backends import Backend
from .placeholders import PLACEHOLDER
from .process import Process
from .screen import BetterScreen, Cell, DoubleHeight, WrittenCell
from .stream import BetterStream
from .style import style_of

__all__ = ["Terminal"]

E = KeyPressEvent


#: How a DEC line attribute of the screen reads to prompt_toolkit.
#:
#: ptterm holds the two halves of the attribute apart, because a program
#: sets them with one sequence and they mean two things. The renderer
#: writes one sequence for a line, so it wants the four together.
#:
#: The half of the height is enough to tell them apart. A line that is
#: twice as high is twice as wide as well, and a line that carries
#: neither is not in the map of the screen at all.
_LINE_ATTRIBUTES = {
    DoubleHeight.NONE: LineAttribute.DOUBLE_WIDTH,
    DoubleHeight.TOP: LineAttribute.DOUBLE_HEIGHT_TOP,
    DoubleHeight.BOTTOM: LineAttribute.DOUBLE_HEIGHT_BOTTOM,
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
    def __init__(
        self,
        backend: Backend,
        done_callback: Callable[[], None] | None = None,
        bell_func: Callable[[], None] | None = None,
        osc_func: Callable[[str, str], None] | None = None,
        resize_func: Callable[[int | None, int | None], None] | None = None,
        may_resize: Callable[[], bool] | None = None,
        owns_whole_lines: FilterOrBool = False,
    ) -> None:
        self.owns_whole_lines = to_filter(owns_whole_lines)

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
        self.screen = BetterScreen(
            0,
            0,
            write_process_input=lambda data: self.process.write_input(data),
            bell_func=bell_func,
            osc_func=osc_func,
            resize_func=resize_func,
            may_resize=may_resize,
        )
        self.stream = BetterStream(self.screen)
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

        #: The DEC line attribute of each row, when this pane may ask for
        #: one. The attribute belongs to a line of the terminal, so a
        #: pane that shares its rows with another pane holds it and says
        #: nothing. `owns_whole_lines` is the embedder answering that.
        if self.owns_whole_lines():
            line_attributes = self.screen.line_attributes
        else:
            line_attributes = {}

        def get_line(number: int) -> StyleAndTextTuples:
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

        def get_line_attribute(number: int) -> LineAttribute | None:
            "How big the terminal draws this row, or None for a plain one."
            attribute = line_attributes.get(number)
            if attribute is None:
                return None
            return _LINE_ATTRIBUTES[attribute.double_height]

        if data_buffer:
            # The screen is the rows from `line_offset` to `max_y`, and
            # the buffer can end above `max_y`: an erase with no
            # background drops the row it clears, so "CSI 1000 M" at the
            # top of a full screen takes every row below it away.
            #
            # prompt_toolkit then reads a document shorter than the
            # window and scrolls back to the top, because it does not
            # scroll past the end. Lines that had left the screen come
            # back. So the count is what the screen occupies, and never
            # what is left in the buffer.
            line_count = max(max(data_buffer) + 1, self.screen.max_y + 1)
        else:
            line_count = 1

        return UIContent(
            get_line,
            get_line_attribute=get_line_attribute,
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
                # Xterm SGR mode.
                try:
                    ev, m = {
                        MouseEventType.MOUSE_DOWN: (0, "M"),
                        MouseEventType.MOUSE_UP: (0, "m"),
                        MouseEventType.SCROLL_UP: (64, "M"),
                        MouseEventType.SCROLL_DOWN: (65, "M"),
                    }[mouse_event.event_type]
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
                # Urxvt mode.
                try:
                    ev = {
                        MouseEventType.MOUSE_DOWN: 32,
                        MouseEventType.MOUSE_UP: 35,
                        MouseEventType.SCROLL_UP: 96,
                        MouseEventType.SCROLL_DOWN: 97,
                    }[mouse_event.event_type]
                except KeyError:
                    pass
                else:
                    self.screen.reply_csi(f"{ev};{x + 1};{y + 1}M")

            elif self.screen.mouse_support_enabled:
                # Fall back to old mode.
                if x < 96 and y < 96:
                    try:
                        ev = {
                            MouseEventType.MOUSE_DOWN: 32,
                            MouseEventType.MOUSE_UP: 35,
                            MouseEventType.SCROLL_UP: 96,
                            MouseEventType.SCROLL_DOWN: 97,
                        }[mouse_event.event_type]
                    except KeyError:
                        pass
                    else:
                        self.screen.reply_csi(
                            f"M{chr(ev)}{chr(x + 33)}{chr(y + 33)}"
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


def create_backend(
    command: List[str], before_exec_func: Callable[[], None] | None
) -> Backend:
    if is_windows():
        from .backends.win32 import Win32Backend

        return Win32Backend()
    else:
        from .backends.posix import PosixBackend

        return PosixBackend.from_command(command, before_exec_func=before_exec_func)


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
    :param owns_whole_lines: Whether every row this pane draws is a whole
        row of the terminal of the user. Only then may the pane put the
        DEC line attributes of the program on the wire: a line that is
        drawn twice as wide is a line of that terminal, and a pane beside
        another one holds half of it. It is a filter, because a layout
        changes while the pane runs.
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
        owns_whole_lines: FilterOrBool = False,
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
            owns_whole_lines=owns_whole_lines,
        )

        self.terminal_window = _Window(
            terminal_control=self.terminal_control,
            content=self.terminal_control,
            wrap_lines=False,
        )

        # Key bindigns for copy buffer.
        kb = KeyBindings()

        @kb.add("c-c")
        def _exit(event):
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

        self.copy_window = Window(
            content=self.copy_buffer_control,
            wrap_lines=False,
            style=self._copy_style,
        )

        self.is_copying = False

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
        # Suspend process.
        self.terminal_control.process.suspend()

        # Copy content into copy buffer.
        screen = self.terminal_control.screen
        data_buffer = screen.page.data_buffer

        # DECSCNM reverses the whole screen, and copy mode shows the
        # same screen stopped. `_copy_style` paints the reverse over the
        # window, the way `_Window` does for the pane, and a cell that
        # "SGR 7" already reversed turns the other way here. The process
        # is suspended, so the mode cannot change while copy mode is
        # open and reading it once is enough. Lillecarl/pymux#96.
        self.copy_reverse_video = screen.has_reverse_video

        text = []
        styled_lines = []

        if data_buffer:
            for line_index in range(min(data_buffer), max(data_buffer) + 1):
                line = data_buffer[line_index]
                styled_line = []

                if line:
                    for column_index in range(0, max(line) + 1):
                        char = line[column_index]
                        text.append(char.char)
                        styled_line.append((self._copy_cell_style(char), char.char))

                text.append("\n")
                styled_lines.append(styled_line)
            text.pop()  # Drop last line ending.

        text_str = "".join(text)

        self.copy_buffer.set_document(
            Document(text=text_str, cursor_position=len(text_str)), bypass_readonly=True
        )

        self.styled_lines = styled_lines

        # Enter copy mode.
        self.is_copying = True
        get_app().layout.focus(self.copy_window)

    def exit_copy_mode(self) -> None:
        # Resume process.
        self.terminal_control.process.resume()

        # focus terminal again.
        self.is_copying = False
        get_app().layout.focus(self.terminal_window)

    def __pt_container__(self) -> FloatContainer:
        return self.container

    @property
    def process(self):
        return self.terminal_control.process

    @property
    def screen(self) -> BetterScreen:
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
        try:
            line = self.terminal.styled_lines[transformation_input.lineno]
        except IndexError:
            line = []
        return Transformation(line)
