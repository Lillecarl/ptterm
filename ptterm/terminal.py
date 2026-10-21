"""
A terminal in a prompt_toolkit widget.

It runs a program on a pty, feeds what the program writes to a screen,
and draws that screen. Three packages do the work and this file is the
joint between them: `ptyhost` owns the pty and the child process,
`pyte` parses the bytes and holds the cells, and prompt_toolkit draws.
`txterm/terminal.py` is the same joint for Textual.

Three classes carry it, and only the first is for anybody outside:

    Terminal            the widget. A `FloatContainer` holding the
                        screen, the copy buffer that replaces it while
                        a person reads the history, and a search bar
    _TerminalControl    the `UIControl` under it: it feeds the stream
                        what the program wrote, and turns the screen
                        into the rows prompt_toolkit asks for
    _Window             a `Window` that keeps the bottom of the screen
                        in view, from the screen's own numbers rather
                        than from a prompt_toolkit cursor

**The screen is not this widget's to interpret.** A cell holds a
`pyte.cells.Appearance`, which is a model, and `ptterm/style.py`
spells one as a prompt_toolkit style string. That is the whole of what
this layer adds to a cell.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable, Iterable
from typing import ClassVar, NamedTuple, Protocol

import anyio
import anyio.abc
import pyte.runs
from prompt_toolkit.application.current import get_app, get_app_or_none
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import (
    AnyContainer,
    DynamicContainer,
    HSplit,
    Window,
    WindowRenderInfo,
)
from prompt_toolkit.layout.controls import (
    UIContent,
    UIControl,
)
from prompt_toolkit.layout.screen import Point
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.utils import Event
from ptyhost import Process
from ptyhost.backends import Backend
from ptyhost.backends.posix import spawn_of
from ptyhost.held import Holding, backend_of
from pyte.environment import preparing
from pyte.images import ASSUMED_CELL_HEIGHT, ASSUMED_CELL_WIDTH
from pyte.keep import Keep
from pyte.keys import DEFAULT_KEY_PROFILE, KeyProfile
from pyte.placeholders import PLACEHOLDER
from pyte.screen import RegionCounts, Screen
from pyte.streams import GroundTimer, Stream

from .copy_mode import CopyView
from .per_application import PerApplication
from .style import fragments_of_runs, placeholder_cells, visible_char

__all__ = ["Machinery", "Program", "Terminal"]

E = KeyPressEvent


class Machinery(Protocol):
    "What a reader may ask of the machinery under a program."

    @property
    def pid(self) -> int | None: ...


class Program(Protocol):
    """
    What a terminal and its embedder ask of whatever runs behind it.

    A `ptyhost.Process` is one. An embedder may put something else in
    its place, which writes to the screen through `feed_output`: pymux
    shows a job that way, with no pty behind the pane.

    The data members are read-only here, so each implementation keeps
    its own attribute type.
    """

    @property
    def suspended(self) -> bool: ...

    @property
    def sx(self) -> int: ...

    @property
    def sy(self) -> int: ...

    @property
    def backend(self) -> Machinery: ...

    async def start(self, task_group: anyio.abc.TaskGroup) -> None: ...

    def get_name(self) -> str: ...

    def get_cwd(self) -> str | None: ...

    def kill(self) -> None: ...

    def hang_up(self) -> None: ...

    @property
    def is_terminated(self) -> bool: ...

    def set_size(self, width: int, height: int) -> None: ...

    def write_input(self, data: str) -> None: ...

    def suspend(self) -> None: ...

    def resume(self) -> None: ...


#: How long a sequence may stay open in a pane before the next bytes
#: drop it and return the parser to plain text. A program that writes a
#: partial escape and stops would otherwise leave the pane parsing
#: through the wrong state. Lillecarl/pymux#390.
_GROUND_TIMEOUT = 5

#: How long a pane shows its last picture while its program draws a
#: frame ("?2026"). A program that set the mode and died would
#: otherwise freeze the pane. tmux waits the same second
#: (`screen_write_start_sync`). Lillecarl/pymux#567.
_FRAME_HELD_AT_MOST = 1.0


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

#: How far to the right and how far down an X10 report reaches.
#:
#: This is X10's own limit. A coordinate byte holds `223 + 32` and no
#: more, and kitty writes the same bound as
#: "if (x > 223 || y > 223) return 0", counting from one. A press
#: further out sends nothing, which is what kitty does with it.
#:
#: It was 96, which is narrower than a great many panes: a press past
#: column 96 went nowhere. Lillecarl/pymux#139.
_X10_COLUMNS = 223

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


#: The key a wheel step is on the alternate screen, before the keyboard
#: mode of the pane spells it.
_WHEEL_ARROWS = {
    MouseEventType.SCROLL_UP: "\x1b[A",
    MouseEventType.SCROLL_DOWN: "\x1b[B",
}

#: What xterm (`scroll-back(5,line)`) and kitty (`wheel_scroll_multiplier`)
#: send by default. The outer terminal reports one event per notch
#: while pymux holds the mouse, so this is the whole step.
_ARROWS_PER_WHEEL_STEP = 5


def _one_byte(value: int) -> str:
    """
    One byte of an X10 mouse report, as a character the backend writes
    as that byte and nothing else.

    A value above 127 is a byte and not a character, so UTF-8 has no
    one byte spelling for it: `chr(128)` went out as two, and the
    program read the first as the column and the second as the row.

    It travels as a surrogate instead, which is Python's channel for a
    byte that is not a character, and `ptyhost/backends/posix.py`
    encodes it back with "surrogateescape". `Screen._control` spells the
    eight bit C1 controls the same way. Lillecarl/pymux#139.
    """
    if value < 0x80:
        return chr(value)
    return chr(0xDC00 + value)


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

    **The count is of what the line draws, not of what the cells hold.**
    A kitty placeholder cell holds U+10EEEE and its diacritics and draws
    one space (`style.visible_char`). Counting what it holds put a cursor
    right of an image dozens of places past the edge, and the pane
    scrolled sideways. Lillecarl/pymux#602.
    """
    row = screen.page.data_buffer[screen.pt_cursor_position.y]
    chars = [row[x].char for x in range(screen.reported_column)]
    text = "".join(chars)
    if PLACEHOLDER in text:
        text = "".join(map(visible_char, chars))
    return len(text)


class _Drawn(NamedTuple):
    """
    What a control built for one row: the line, the write count of the
    screen it was built at, and an image of the row's cells then, so a
    row that moved can find it again. Lillecarl/pymux#570.
    """

    line: StyleAndTextTuples
    at: int
    image: object


#: Builds a `_Drawn` without the `__new__` that `NamedTuple` writes in
#: Python, which a frame pays for every row it builds.
_new_drawn = tuple.__new__


#: How many rows a repaint has to have moved before it counts as a
#: shift. Fewer is a coincidence of equal lines, such as two blank ones.
_ROWS_THAT_MAKE_A_SHIFT = 3


class _TerminalControl(UIControl):
    #: What a hot upgrade does with each attribute; `pyte.keep` says.
    #: Everything a frame remembers is rebuilt by the first frame after
    #: a load. Lillecarl/pymux#399.
    KEEP: ClassVar[dict[str, Keep]] = {
        "screen": Keep.SAVED,
        "stream": Keep.SAVED,
        "process": Keep.SAVED,
        "terminal": Keep.REBUILT,
        "keep_rows": Keep.REBUILT,
        "may_type": Keep.REBUILT,
        "takes_key_first": Keep.REBUILT,
        "unreadable_key_func": Keep.REBUILT,
        "key_profile_func": Keep.REBUILT,
        "on_content_changed": Keep.REBUILT,
        "on_mouse_focus": Keep.REBUILT,
        "placeholder_ids": Keep.REBUILT,
        "_ground_timer": Keep.REBUILT,
        "_running": Keep.REBUILT,
        "_drawn": Keep.REBUILT,
        "_report": Keep.DROPPED,
        "_report_seq": Keep.DROPPED,
        "_scanned_at": Keep.DROPPED,
        "_drawn_reversed": Keep.REBUILT,
        "_scroll_mark": Keep.DROPPED,
        "_held_since": Keep.DROPPED,
        "_held_too_long": Keep.DROPPED,
        "_held_from": Keep.DROPPED,
        "_shown": Keep.DROPPED,
        "_shown_count": Keep.DROPPED,
        "_let_go": Keep.DROPPED,
        "_task_group": Keep.REBUILT,
    }

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
        may_type: Callable[[], bool] | None = None,
        get_history_limit: Callable[[], int] | None = None,
        unreadable_key_func: Callable[[object, int, str], None] | None = None,
        takes_key_first: Callable[[], bool] | None = None,
        key_profile_func: Callable[[], KeyProfile] | None = None,
    ) -> None:
        # Called for a key this pane reads as something else, or not at
        # all. What a person presses still degrades on the way in, the
        # way a keyboard does; this is how anything finds out.
        # Lillecarl/pymux#238.
        self.unreadable_key_func = unreadable_key_func

        #: Whose answer a legacy program gets where the terminals split,
        #: asked once per key: the person pressing it may sit at any of
        #: them. Lillecarl/pymux#706.
        self.key_profile_func = key_profile_func

        #: Whether the person at this keyboard may drive the pane.
        #: Asked once per key, so an embedder that has more than one
        #: person answers for whichever of them this key came from.
        self.may_type = may_type

        #: Whether the embedder takes the next key before the pane does.
        #: prompt_toolkit gives the focused control's bindings priority
        #: over the application's, so the pane's any-key binding beats
        #: the embedder's own: pymux's "a key after the prefix that the
        #: prefix does not bind ends the prefix" never ran, and the key
        #: went to the program. Lillecarl/pymux#540.
        self.takes_key_first = takes_key_first

        #: Called when the mouse focused this pane: a click in it while
        #: another control had the focus. The widget moves the layout
        #: focus itself; the embedder follows with whatever selecting
        #: means where this pane sits. None (a standalone widget, or
        #: an embedder with one pane) does nothing.
        self.on_mouse_focus: Callable[[], None] | None = None

        #: The id an outer terminal knows a pane image by, for an
        #: embedder that passes the image cells on as unicode
        #: placeholders. It must be one answer for every client, because
        #: a built row is shared by all of them. None draws a space in
        #: each image cell. Lillecarl/pymux#600.
        self.placeholder_ids: Callable[[int], int] | None = None

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
        self._ground_timer = GroundTimer(self.stream, _GROUND_TIMEOUT, time.monotonic)

        self.process: Program = Process(
            backend=backend,
            receive=self._ground_timer.feed,
            invalidate=lambda: self._after_a_feed(),
            done_callback=done_callback,
            has_priority=has_priority,
        )

        self.on_content_changed = Event(self)
        self._running = False
        self._task_group: anyio.abc.TaskGroup | None = None

        # While the program draws a frame, when it started to, and what
        # the last frame showed, which draws until the frame ends.
        # `_let_go` ends a hold that the program never ends.
        self._held_since: float | None = None
        self._held_too_long = False
        self._held_from = 0
        self._shown: tuple[UIContent, list[StyleAndTextTuples], int, int] | None = None
        self._shown_count = 0
        self._let_go: anyio.CancelScope | None = None

        #: The `Terminal` this control is the screen of, set by it when
        #: it builds this control. The wheel that enters copy mode goes
        #: through it, because copy mode and its buffer live there.
        self.terminal: Terminal = None

        # What this control drew for each row, and the write count of
        # the screen that it drew it at. A row whose count has not
        # moved is a row it does not build again. The state is here and
        # not on the screen, because a screen has more than one reader
        # and no way to know how many. Lillecarl/pymux#126.
        self._drawn: dict[int, _Drawn] = {}

        # The scrolls this control hands a window, with a sequence of its
        # own: the screen's logged scrolls, and the shifts a repaint made
        # that it found by the images of the rows. Lillecarl/pymux#570.
        self._report: list[tuple[int, int, int, object, int]] = []
        self._report_seq = 0
        # The screen's write count the last scan for a shift read.
        self._scanned_at = -1
        self._drawn_reversed = False

        # The sequence of the screen's scroll report consumed through.
        # None is a control that never drew: it adopts the count and
        # rotates nothing, because it remembers nothing.
        # Lillecarl/pymux#516.
        self._scroll_mark: int | None = None

        #: Whether a frame reuses what earlier frames built: the rows
        #: drawn before, moved along with a scroll, and the stable lines
        #: and scroll report that let a window keep what it copied. Off,
        #: every frame builds every row from the screen and the window
        #: copies all of it, which is the slow answer the fast one is
        #: held against.
        self.keep_rows = True

    def set_size(self, width: int, height: int) -> None:
        "Tell the pty and the screen how big the pane is."
        self.process.set_size(width, height)
        self.screen.resize(lines=height, columns=width)
        self.screen.lines = height
        self.screen.columns = width

    def feed_output(self, data: str) -> None:
        """
        Feed output from something that is not the process, and say
        the screen may have changed.

        A job viewer feeds the tail of a job this way: the same
        stream the program writes to, with the same ground timer, but
        no pty behind it. What the screen cannot take is the caller's
        to survive, the way the process read survives it.
        """
        self._ground_timer.feed(data)
        self._after_a_feed()

    def _after_a_feed(self) -> None:
        """
        Say the screen changed, unless the program is drawing a frame.

        A redraw then would show the frame half drawn. The picture is
        held until the program ends the frame, or for
        `_FRAME_HELD_AT_MOST`, whichever comes first. A frame that took
        too long draws as it comes until the program ends it, the way
        tmux drops the mode when its timer runs out.

        A feed can end one frame and begin the next. It then ends with
        the mode set, and only the screen's count of frames says a
        frame ended in it, so that frame draws.
        """
        screen = self.screen
        if not screen.draws_a_frame:
            self._held_too_long = False
        elif self._held_since is not None and screen.frames_drawn != self._held_from:
            pass
        elif not self._held_too_long:
            if self._held_since is None:
                self._held_since = time.monotonic()
                self._held_from = screen.frames_drawn
                if self._task_group is not None:
                    # Made here and not in the task, so that a frame
                    # that ends before the task first runs cancels it.
                    self._let_go = anyio.CancelScope()
                    self._task_group.start_soon(self._end_the_hold_later, self._let_go)
            if self._holds_the_frame():
                return
            self._held_too_long = True
        self._end_the_hold()
        self.on_content_changed.fire()

    def _holds_the_frame(self) -> bool:
        return (
            self._held_since is not None
            and self.screen.draws_a_frame
            and self.screen.frames_drawn == self._held_from
            and time.monotonic() - self._held_since < _FRAME_HELD_AT_MOST
        )

    def _end_the_hold(self) -> None:
        self._held_since = None
        if self._let_go is not None:
            self._let_go.cancel()
            self._let_go = None

    async def _end_the_hold_later(self, scope: anyio.CancelScope) -> None:
        with scope:
            await anyio.sleep(_FRAME_HELD_AT_MOST)
            self._let_go = None
            self._held_since = None
            self._held_too_long = True
            self.on_content_changed.fire()

    async def start(self, task_group: anyio.abc.TaskGroup) -> None:
        """
        Start the program on the pty, watched by `task_group`.

        Starting is the embedder's to do, from an async scope: the
        render path is synchronous and cannot await it. A control that
        was never started renders an empty screen.
        """
        if not self._running:
            self._task_group = task_group
            await self.process.start(task_group)
            self._running = True

    def create_content(self, width: int, height: int) -> UIContent:
        # Report dimensions to the process.
        self.set_size(width, height)

        if not self.screen:
            return UIContent()

        shown = self._shown
        if shown is not None and shown[2:] == (width, height) and self._holds_the_frame():
            return self._held_picture(*shown)

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
            self._drawn_reversed = reverse_video

        # The history grows and the rows that leave it never come back,
        # so what is remembered of them is dead weight. Emptying the
        # whole of it costs one frame, and a frame is what this saves
        # thousands of.
        if len(self._drawn) > self._REMEMBER_AT_MOST:
            self._drawn.clear()

        written_at = self.screen.written_at
        # A row with no count of its own carries the one that
        # `touch_everything` last set, so a reset or a page swap moves
        # every row at once and costs nothing to say.
        everything_at = self.screen.everything_at
        drawn = self._drawn

        def rotate(top: int, bottom: int, distance: int, counts: RegionCounts) -> None:
            """
            Move what was drawn for scrolled rows along with them.

            The rows already stand in order; a scroll only moves them,
            so rebuilding every one is the cost this skips.

            **Only a line that still shows its row moves**, which is a
            line drawn at the count the row held just before the
            scroll. A row written between the draw and the scroll
            holds something the line does not, and the scroll's own
            writes would hide that from any later count. A program
            that writes the bottom row of a region and then scrolls,
            in one frame, does exactly that.

            A moved line takes the count its new row has once the
            scroll is done, so a write after the scroll still rebuilds
            it. What the scroll uncovered, and what did not move, has
            no line and builds.
            """
            before, after = counts
            kept: dict[int, _Drawn] = {}
            for row, entry in drawn.items():
                if not (top <= row <= bottom):
                    kept[row] = entry
                elif entry.at == before[row - top]:
                    dest = row - distance
                    if top <= dest <= bottom:
                        kept[dest] = entry._replace(at=after[dest - top])
            drawn.clear()
            drawn.update(kept)

        # The scrolls since this drew last, oldest first. What they
        # moved is rotated above; what they uncovered, and every row
        # when a scroll went unreported, rebuilds below as before.
        # The mark is per reader: two windows draw one screen, and
        # each rotates for itself.
        mark = self._scroll_mark
        logged = self.screen.scrolls
        logged_seq = self.screen.scroll_seq
        report = self._report
        if not self.keep_rows:
            drawn.clear()
            self._scroll_mark = logged_seq
        elif mark is None:
            self._scroll_mark = logged_seq
        else:
            new = [s for s in logged if s[4] > mark]
            if new and new[0][4] == mark + 1:
                for top, bottom, distance, counts, _seq in new:
                    rotate(top, bottom, distance, counts)
                    self._report_seq += 1
                    report.append((top, bottom, distance, counts, self._report_seq))
                self._scroll_mark = new[-1][4]
            elif logged_seq != mark:
                drawn.clear()
                self._scroll_mark = logged_seq
                # A gap in the sequence: a window that reads it forgets
                # what it stored, as this control just did.
                self._report_seq += 2
        # The images of the rows this frame rewrote, when it wrote enough
        # for a shift to be worth finding; a frame of a few writes takes
        # none, which keeps a keystroke as cheap as it was.
        images = self._find_a_shift(data_buffer, written_at, everything_at, cursor_y) if self.keep_rows else None
        del report[:-32]
        placeholder_ids = self.placeholder_ids
        columns = self.screen.columns

        def build(number: int) -> StyleAndTextTuples:
            row = data_buffer[number]
            if not row and number != cursor_y:
                return [("", " ")]
            # Through the module, so that a kernel installed after this
            # file was imported is the one that runs.
            runs = pyte.runs.runs_of(row)
            if not runs and number != cursor_y:
                return [("", " ")]

            # The columns the runs cover, and the furthest one drawn:
            # the runs carry their positions because a row is sparse,
            # and the cursor pads its row out to where it stands.
            end = runs[-1].end if runs else 0
            if number == cursor_y:
                end = max(end, cursor_x + 1)

            if placeholder_ids is None:
                return fragments_of_runs(runs, end, reverse_video)
            return fragments_of_runs(
                runs,
                end,
                reverse_video,
                lambda: placeholder_cells(row, columns, number, placeholder_ids),
            )

        cursor_line: list[StyleAndTextTuples] = []

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
                cursor_line[:] = [build(number)]
                return cursor_line[0]

            version = written_at.get(number, everything_at)
            entry = drawn.get(number)
            if entry is None or entry.at != version:
                image = None
                if images is not None:
                    image = images.get(number) or data_buffer[number].image()
                entry = drawn[number] = _new_drawn(_Drawn, (build(number), version, image))
            return entry.line

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

        content = UIContent(
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
        # The lines above are the same objects while their rows stand
        # still -- `get_line` says so -- so a window may store what it
        # drew for them instead of looking every cell up again.
        content.stable_lines = self.keep_rows
        # This control's scroll report and sequence: a window that stores
        # what it drew rotates those rows the same way, with its own
        # mark. Lillecarl/pymux#516.
        if self.keep_rows:
            content.scrolled = (self._report, self._report_seq)
        self._shown = (content, cursor_line, width, height)
        self._shown_count += 1
        return content

    def content_version(self, width: int, height: int) -> Hashable | None:
        """
        What `create_content` draws from, so that a window which sees it
        unchanged writes the cells it wrote before. Lillecarl/pymux#577.

        A held frame draws only what was shown, so it answers which frame
        that was. Not that frame's version: keeping it would cost every
        frame that changes a second `_version`.
        """
        if not self.screen or not self.keep_rows:
            return None
        shown = self._shown
        if shown is not None and shown[2:] == (width, height) and self._holds_the_frame():
            return (self._shown_count,)
        return self._version(width, height)

    def _version(self, width: int, height: int) -> Hashable:
        # The screen counts every write to a row, and a page swap or a
        # reset moves `everything_at`. The cursor moves without a write,
        # and the scroll report is this control's own count.
        screen = self.screen
        page = screen.page
        return (
            width,
            height,
            screen,
            page,
            screen.writes,
            screen.everything_at,
            screen.scroll_seq,
            self._report_seq,
            screen.pt_cursor_position.y,
            cursor_offset(screen),
            page.show_cursor,
            screen.has_reverse_video,
            screen.highest_row(),
        )

    def _find_a_shift(self, data_buffer, written_at, everything_at: int, cursor_y: int) -> dict | None:
        """
        Find rows a repaint moved, and keep what was drawn for them.

        A program that scrolls by drawing its whole screen again -- fzf,
        and vim for most scrolls -- writes every row, so every count
        moves and every line would be built and copied again. When
        enough of the rewritten rows hold exactly what other rows held
        when they were drawn, by one distance, the screen shifted: each
        of those rows takes the line that was drawn for its old place,
        and the shift goes into the report, so a window moves what it
        stored and the renderer may send a scroll instead of repainting.
        The renderer proves every claimed shift before it uses one.
        Lillecarl/pymux#570.
        """
        # The screen counts a write per row it writes, so fewer writes
        # since the last scan than a shift needs rows cannot be one. That
        # is a keystroke, and nearly every frame of a pane at rest, and it
        # costs one subtraction. A frame of many writes takes images of
        # what it builds even when nothing shifted, so the next repaint
        # can find those rows.
        writes = self.screen.writes
        since = writes - self._scanned_at
        self._scanned_at = writes
        if since < _ROWS_THAT_MAKE_A_SHIFT:
            return None
        drawn = self._drawn
        # Only the rows on the screen: a repaint moves nothing else, and
        # what is remembered of the history can be thousands of rows.
        first = self.screen.line_offset
        shown = {row: drawn[row] for row in range(first, first + self.screen.lines) if row in drawn}
        changed = [
            row
            for row, entry in shown.items()
            if row != cursor_y and entry.at != written_at.get(row, everything_at) and row in data_buffer
        ]
        if len(changed) < _ROWS_THAT_MAKE_A_SHIFT:
            return {}
        where = {entry.image: row for row, entry in shown.items() if entry.image is not None}
        images = {row: data_buffer[row].image() for row in changed}
        votes: dict[int, int] = {}
        for row, image in images.items():
            source = where.get(image)
            if source is not None and source != row:
                votes[source - row] = votes.get(source - row, 0) + 1
        if not votes:
            return images
        distance, count = max(votes.items(), key=lambda vote: vote[1])
        if count < _ROWS_THAT_MAKE_A_SHIFT:
            return images
        moved = [row for row, image in images.items() if where.get(image) == row + distance]
        old = {row: drawn[row + distance] for row in moved}
        for row in moved:
            drawn[row] = _Drawn(old[row].line, written_at.get(row, everything_at), images[row])
        top = min(moved) + min(0, distance)
        bottom = max(moved) + max(0, distance)
        self._report_seq += 1
        self._report.append((top, bottom, distance, None, self._report_seq))
        return images

    def _held_picture(
        self,
        content: UIContent,
        cursor_line: list[StyleAndTextTuples],
        width: int,
        height: int,
    ) -> UIContent:
        """
        What `content` showed, read again without the screen.

        The rows come from `_drawn`, which holds the line built for each
        row that frame asked for, and which only a frame that reads the
        screen changes. The cursor row is never kept there, so the frame
        kept it in `cursor_line`. The scroll report is empty at the
        sequence that frame consumed, so a window rotates nothing.
        """
        drawn = self._drawn
        cursor_y = content.cursor_position.y
        blank: StyleAndTextTuples = [("", " ")]

        def get_line(number: int) -> StyleAndTextTuples:
            if number == cursor_y:
                return cursor_line[0] if cursor_line else blank
            entry = drawn.get(number)
            return blank if entry is None else entry.line

        held = UIContent(
            get_line,
            line_count=content.line_count,
            show_cursor=content.show_cursor,
            cursor_position=content.cursor_position,
            apply_display_mappings=False,
        )
        held.stable_lines = content.stable_lines
        scrolled = getattr(content, "scrolled", None)
        if scrolled is not None:
            held.scrolled = ((), scrolled[1])
        return held

    def may_be_driven(self) -> bool:
        """
        Whether what a person just did reaches the program in the pane.

        Everything a person sends goes through here: the keys, a paste
        and the mouse. The screen's own answers do not -- a reply to a
        cursor query is the program asking itself, and an embedder that
        refused it would hang the program rather than protect anything.
        """
        return self.may_type is None or self.may_type()

    def key_profile(self) -> KeyProfile:
        "The `KeyProfile` of the person pressing a key now."
        return DEFAULT_KEY_PROFILE if self.key_profile_func is None else self.key_profile_func()

    def get_key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @Condition
        def the_pane_takes_it() -> bool:
            return self.takes_key_first is None or not self.takes_key_first()

        @bindings.add(Keys.Any, filter=the_pane_takes_it)
        def handle_key(event):
            """
            Handle any key binding -> write it to the stdin of this terminal.
            """
            if not self.may_be_driven():
                return NotImplemented
            # `NotImplemented` is prompt_toolkit's own answer for "the
            # handler changed nothing of the application's, so do not
            # invalidate". A key that reaches this was forwarded and
            # nothing else: the frame that shows its effect is drawn
            # when the program answers, so the key's own invalidate
            # could only ever redraw nothing -- and on a loaded machine
            # it is a whole redraw that draws nothing.
            # Lillecarl/pymux#246.
            key_press = event.key_sequence[0]
            if key_press.data:
                # Forward the raw data. It preserves modifiers that
                # prompt_toolkit splits into multiple keys (like
                # alt+char), so that they can be re-encoded for the
                # keyboard mode of this pane. (The empty-data presses
                # are the remainders of such split sequences.)
                self.process.write_input(
                    self.screen.encode_key(key_press.data, report=self.unreadable_key_func, profile=self.key_profile())
                )
            return NotImplemented

        @bindings.add(Keys.BracketedPaste)
        def _(event):
            if not self.may_be_driven():
                return NotImplemented
            self.process.write_input(self.screen.wrap_paste(event.data))
            # A paste reaches a program as well, and the answer is the
            # redraw. Same answer as a key. Lillecarl/pymux#246.
            return NotImplemented

        return bindings

    def get_invalidate_events(self) -> Iterable[Event]:
        yield self.on_content_changed

    def mouse_handler(self, mouse_event) -> None:
        """
        Handle mouse events in a pane. A click in a non-active pane will select
        it. A click in active pane will send the mouse event to the application
        running inside it.

        **When `may_type` says no, the wheel that opens copy mode is all
        that is left**, and not the report alone goes. The other branches
        are the person driving this pane: two of them write to the
        program, and one moves the focus. Copy mode reads a copy for this
        application alone, so it drives nothing. Lillecarl/pymux#470.
        """
        if not self.may_be_driven():
            # Over the focused pane alone, as for a person who types: a
            # wheel over another pane does nothing, and opening copy
            # mode there would move the focus behind the embedder.
            if get_app().layout.has_focus(self) and self._the_wheel_reads_the_history(mouse_event):
                self._read_the_history()
            return

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
                if self.on_mouse_focus is not None:
                    self.on_mouse_focus()
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
                if x < _X10_COLUMNS and y < _X10_COLUMNS:
                    try:
                        ev = _SHIFTED_BUTTONS[mouse_event.event_type]
                    except KeyError:
                        pass
                    else:
                        self.screen.reply_csi(
                            "M%s%s%s"
                            % (
                                chr(ev),
                                _one_byte(x + _COORDINATE_OFFSET),
                                _one_byte(y + _COORDINATE_OFFSET),
                            )
                        )
            elif mouse_event.event_type in _WHEEL_ARROWS and self.screen.wheel_sends_arrows:
                # The alternate screen has no history, so copy mode
                # would show the first screen's instead. Lillecarl/pymux#422.
                arrow = self.screen.encode_key(_WHEEL_ARROWS[mouse_event.event_type])
                self.process.write_input(arrow * _ARROWS_PER_WHEEL_STEP)
            elif self._the_wheel_reads_the_history(mouse_event):
                self._read_the_history()

    def _the_wheel_reads_the_history(self, mouse_event) -> bool:
        "Is this the wheel up, over a program that wants no mouse and no arrows?"
        screen = self.screen
        return (
            mouse_event.event_type == MouseEventType.SCROLL_UP
            and not screen.sgr_mouse_support_enabled
            and not screen.urxvt_mouse_support_enabled
            and not screen.mouse_support_enabled
            and not screen.wheel_sends_arrows
        )

    def _read_the_history(self) -> None:
        """
        Open copy mode, half a window up.

        The program asked for no mouse at all, and the wheel belongs to
        the person. The live screen does not hold the history of this
        pane, so the wheel up opens copy mode over it -- the rule tmux
        runs: a wheel over a pane whose program wants no mouse is copy
        mode. The way back down is the same wheel in copy mode, which
        ends at the bottom. Lillecarl/pymux#422.
        """
        view = self.terminal.enter_copy_mode()
        view.scroll(-view.half_window())

    def is_focusable(self) -> bool:
        return not self.process.suspended


class _DrawnAt(NamedTuple):
    info: WindowRenderInfo
    horizontal_scroll: int


class _Window(Window):
    """ """

    def __init__(self, terminal_control: _TerminalControl, **kw) -> None:
        self.terminal_control = terminal_control
        # pymux puts this one window in the layout of every client, so
        # `render_info` is whichever drew last. Lillecarl/pymux#713.
        self.drawn_at: PerApplication[_DrawnAt] = PerApplication()
        kw.setdefault("style", self._pane_style)
        # A pane owns every cell of its rectangle: a program left the
        # ones it never wrote at the default background, and the
        # terminal draws those. The fill writes them before the
        # content lands over them, so what shows is the default and
        # not whatever a layer below drew -- the layout background,
        # which is for the margins where no pane draws.
        kw.setdefault("char", " ")
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

    def _write_to_screen_at_index(self, screen, mouse_handlers, write_position, parent_style, erase_bg) -> None:
        """
        A click goes to the control at the cell it was on.

        prompt_toolkit's `Window` maps a click through the lines the
        content holds and clamps one below them to the last: on a screen
        with text on its first two rows, every click came to the cursor's
        row, at the first column. A terminal reports cells, so the cell
        is the answer. Lillecarl/pymux#654.
        """
        super()._write_to_screen_at_index(screen, mouse_handlers, write_position, parent_style, erase_bg)
        if write_position.width > 0 and write_position.height > 0 and self.render_info is not None:
            self.drawn_at.set(_DrawnAt(self.render_info, self.horizontal_scroll))
        else:
            self.drawn_at.pop()
        control = self.terminal_control
        left, top, scroll = write_position.xpos, write_position.ypos, self.vertical_scroll

        def handler(mouse_event: MouseEvent):
            return control.mouse_handler(
                MouseEvent(
                    position=Point(x=mouse_event.position.x - left, y=mouse_event.position.y - top + scroll),
                    event_type=mouse_event.event_type,
                    button=mouse_event.button,
                    modifiers=mouse_event.modifiers,
                )
            )

        mouse_handlers.set_mouse_handler_for_range(
            x_min=left,
            x_max=left + write_position.width,
            y_min=top,
            y_max=top + write_position.height,
            handler=handler,
        )


def create_backend(
    command: list[str],
    environment: Callable[[dict[str, str]], None] | None = None,
    directory: str | None = None,
    holding: Holding | None = None,
) -> Backend:
    """
    A pty for `command`, which runs on this widget's screen.

    The program draws on this screen and not on the terminal the
    application runs in, so its environment has to say which one it is
    (`pyte.environment.preparing`). Nothing else knows both: `pyte` has
    no child, and `ptyhost` has no opinion on what parses the bytes.
    Lillecarl/pymux#125. With `holding`, the holder forks the program
    and keeps it for the next server. Lillecarl/pymux#553.
    """
    # The size of a cell goes into the size of the pty, so that a
    # program that draws images reads the same answer there as
    # "CSI 16 t" gives it.
    spawn = spawn_of(command, preparing(environment), directory)
    return backend_of(spawn, (ASSUMED_CELL_WIDTH, ASSUMED_CELL_HEIGHT), holding)


class Terminal:
    """
    Terminal widget for use in a prompt_toolkit layout.

    :param command: List of command line arguments.
        For instance: `['python', '-c', 'print("test")']`
    :param environment: Edits the program's environment, a copy of
        this process's, when the program starts.
    :param directory: Where the program starts.
    :param holding: The holder that forks the program and keeps it
        for the next server. None forks here.
    :param osc_func: Called with the code and the payload of an OSC
        sequence that only the terminal of the user can serve. (The
        clipboard, a notification, the shape of the pointer.)
    :param copy_func: Called with what a person copied in copy mode.
        The clipboard of the user belongs to the terminal, and this
        widget does not own one, so the embedder decides whether the
        copy reaches it. A pane asking for the clipboard is a
        different question with a different answer, and that one is
        `osc_func`.
    :param resize_func: Called with the lines and the columns that the
        program asks for, when it sends DECSLPP or a window resize.
        Either one is None when the program leaves that side alone. A
        pane cannot resize itself, so the embedder decides.
    :param may_resize: Returns whether the embedder would grant such an
        ask. The private modes that only exist where a program can have
        a different page go away when it says no, so a program learns at
        once instead of laying its output out for room it will not get.
    :param may_type: Returns whether the person at the keyboard may
        drive this pane at all. False drops the keys, a paste and the
        mouse, and leaves everything the pane draws and the wheel into
        copy mode, which reads a copy and drives nothing. The embedder
        decides because only it knows who is watching: pymux answers
        for a client that attached with `attach-session -r`.
    :param takes_key_first: Returns whether the embedder wants the next
        key before this pane. Yes takes the pane's key binding out of
        the way, so the embedder's own catch-all binding answers: the
        focused pane's would otherwise win. pymux answers for a client
        that holds its prefix.
    :param get_history_limit: Returns how many rows of scrollback this
        pane keeps. The default is two thousand, which is what tmux
        keeps. It is a function and not a number, so the option can
        change while the pane runs.
    """

    #: What a hot upgrade does with each attribute; `pyte.keep` says.
    #: Copy mode belongs to an application, and a hot upgrade builds
    #: every application again, so the embedder saves each copy mode
    #: with what it serves. pymux saves it with the client.
    #: Lillecarl/pymux#399, Lillecarl/pymux#470.
    KEEP: ClassVar[dict[str, Keep]] = {
        "terminal_control": Keep.SAVED,
        "copy_views": Keep.DROPPED,
        "_copy_func": Keep.REBUILT,
        "container": Keep.REBUILT,
        "terminal_window": Keep.REBUILT,
    }

    def __init__(
        self,
        command=["/bin/bash"],
        environment: Callable[[dict[str, str]], None] | None = None,
        directory: str | None = None,
        holding: Holding | None = None,
        backend: Backend | None = None,
        bell_func: Callable[[], None] | None = None,
        style: str = "",
        width: int | None = None,
        height: int | None = None,
        done_callback: Callable[[], None] | None = None,
        osc_func: Callable[[str, str], None] | None = None,
        copy_func: Callable[[str], None] | None = None,
        resize_func: Callable[[int | None, int | None], None] | None = None,
        may_resize: Callable[[], bool] | None = None,
        may_type: Callable[[], bool] | None = None,
        get_history_limit: Callable[[], int] | None = None,
        unreadable_key_func: Callable[[object, int, str], None] | None = None,
        takes_key_first: Callable[[], bool] | None = None,
        key_profile_func: Callable[[], KeyProfile] | None = None,
    ) -> None:
        if backend is None:
            backend = create_backend(command, environment, directory, holding)

        self._copy_func = copy_func

        self.terminal_control = _TerminalControl(
            backend=backend,
            bell_func=bell_func,
            osc_func=osc_func,
            resize_func=resize_func,
            may_resize=may_resize,
            may_type=may_type,
            done_callback=done_callback,
            get_history_limit=get_history_limit,
            unreadable_key_func=unreadable_key_func,
            takes_key_first=takes_key_first,
            key_profile_func=key_profile_func,
        )
        # The wheel over a pane whose program wants no mouse enters
        # copy mode, and the control is what the wheel arrives at.
        # Lillecarl/pymux#422.
        self.terminal_control.terminal = self

        self.terminal_window = _Window(
            terminal_control=self.terminal_control,
            content=self.terminal_control,
            wrap_lines=False,
        )

        #: Copy mode, for each application that has it open.
        self.copy_views: PerApplication[CopyView] = PerApplication()

        def the_window_that_is_shown() -> AnyContainer:
            """
            The screen, or the copy mode of the application that draws.

            **One of them is laid out and the other is not.** This was
            two `ConditionalContainer`s side by side, and they needed a
            `VSplit` around them because a conditional container whose
            width becomes zero collapses the element beside it. So
            every frame of every pane divided the widths of a split
            that only ever had one child to give them to, and a profile
            of eight panes found roughly a tenth of a frame in there.

            A container that answers with the window to draw never lays
            the other one out, so there is nothing to collapse and no
            widths to divide. Lillecarl/pymux#221.

            `enter_copy_mode` keeps the view before it focuses, so the
            window it focuses is in the tree by the time it asks for it.
            """
            view = self.copy_views.get()
            return view.container if view is not None else self.terminal_window

        self.container = HSplit(
            [DynamicContainer(the_window_that_is_shown)],
            style=style,
            width=width,
            height=height,
        )

    async def start(self, task_group: anyio.abc.TaskGroup) -> None:
        """
        Start the program on the pty, watched by `task_group`.

        Starting is the embedder's to do, from an async scope. The
        widget renders an empty screen until it is started.
        """
        await self.terminal_control.start(task_group)

    @property
    def copy_view(self) -> CopyView | None:
        "The copy mode of the application that runs now, or None."
        return self.copy_views.get()

    @property
    def is_copying(self) -> bool:
        "Is the application that runs now reading the history?"
        return self.copy_views.get() is not None

    def enter_copy_mode(self) -> CopyView:
        """
        Open copy mode for the application that runs now, over the
        buffer as it stands, and give it the keyboard.

        **The program goes on running.** Copy mode reads a copy, so a
        person reading the history stops nothing for anybody else who
        watches the pane. A copy mode that is open already stays where
        it is, as tmux's does.
        """
        view = self.copy_views.get()
        if view is None:
            view = CopyView(self)
            view.freeze()
            self.copy_views.set(view)
        self._focus(view.window)
        return view

    @staticmethod
    def _focus(window: Window) -> None:
        """
        Give `window` the keyboard of the application that runs now, when
        that application shows it.

        One that does not show this terminal -- a pane on another window
        of the session, or no application at all -- keeps its keyboard.
        An embedder focuses the terminal when it shows it, and the focus
        goes to the copy window then.
        """
        app = get_app_or_none()
        if app is not None and window in app.layout.find_all_windows():
            app.layout.focus(window)

    def shown_rows(self) -> tuple[int, int] | None:
        """
        The first and the last row of the page this pane shows, live or
        in copy mode, as of the last frame. None before one is drawn.
        """
        view = self.copy_views.get()
        if view is not None:
            return view.shown_rows()
        drawn = self.terminal_window.drawn_at.get()
        if drawn is None:
            return None
        info = drawn.info
        return info.vertical_scroll, info.vertical_scroll + info.window_height - 1

    def where_shown(self, row: int, column: int) -> tuple[int, int] | None:
        """
        The cell of the application's screen, as (y, x), that a cell of
        the page was drawn at in the last frame, or None when it was not.

        Live, a row of the page is a line of the window. In copy mode
        the view says.
        """
        view = self.copy_views.get()
        if view is not None:
            return view.where_shown(row, column)
        drawn = self.terminal_window.drawn_at.get()
        if drawn is None:
            return None
        info = drawn.info
        y = row - info.vertical_scroll
        x = column - drawn.horizontal_scroll
        if not (0 <= y < info.window_height and 0 <= x < info.window_width):
            return None
        return info._y_offset + y, info._x_offset + x

    def exit_copy_mode(self) -> None:
        "Close the copy mode of the application that runs now."
        if self.copy_views.pop() is not None:
            self._focus(self.terminal_window)

    def set_size(self, width: int, height: int) -> None:
        """
        Tell this terminal how big it is, in cells.

        **A widget that is drawn is told by the drawing**, because
        prompt_toolkit gives the size to `create_content`. This is the
        door for a caller that knows the size without drawing: pymux
        lays its panes out itself, and a pane it does not draw -- one
        scrolled out of the view, or behind another in a stack -- still
        has a program in it that needs the size it will be shown at.
        Lillecarl/pymux#224.

        Nothing happens when the size has not changed: the process
        signals only a real change, and `Screen.resize` returns at
        once for the size it already is.
        """
        self.terminal_control.set_size(width, height)

    def __pt_container__(self) -> HSplit:
        return self.container

    @property
    def process(self):
        return self.terminal_control.process

    @property
    def screen(self) -> Screen:
        "What the program in this pane has drawn."
        return self.terminal_control.screen
