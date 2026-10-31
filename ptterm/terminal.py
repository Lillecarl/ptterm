"""
A terminal in a prompt_toolkit widget.

It runs a program on a pty, feeds what the program writes to a screen,
and draws that screen. Three packages do the work and this widget is
the joint between them: `ptyhost` owns the pty and the child process,
`pyte` parses the bytes and holds the cells, and prompt_toolkit draws.
`txterm/terminal.py` is the same joint for Textual.

Three classes carry it, one module each, and only the first is for
anybody outside:

    Terminal            the widget. A `FloatContainer` holding the
                        screen, the copy buffer that replaces it while
                        a person reads the history, and a search bar
    TerminalControl     the `UIControl` under it, in `control.py`: it
                        feeds the stream what the program wrote, and
                        turns the screen into the rows prompt_toolkit
                        asks for
    TerminalWindow      the `Window` it draws in, in `window.py`. It
                        keeps the bottom of the screen in view, from
                        the screen's own numbers rather than from a
                        prompt_toolkit cursor

**The screen is not this widget's to interpret.** A cell holds a
`pyte.cells.Appearance`, which is a model, and `ptterm/style.py`
spells one as a prompt_toolkit style string. That is the whole of what
this layer adds to a cell.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

import anyio
import anyio.abc
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.layout.containers import (
    AnyContainer,
    DynamicContainer,
    HSplit,
    Window,
)
from ptyhost.backends import Backend
from pyte.keep import Keep
from pyte.keys.events import KeyEvent, KeyProfile
from pyte.screen import Screen

from .control import TerminalControl
from .copy_mode import CopyView
from .per_application import PerApplication
from .program import create_backend
from .window import TerminalWindow

__all__ = ["Terminal"]


class Terminal:
    """
    Terminal widget for use in a prompt_toolkit layout.

    :param command: List of command line arguments.
        For instance: `['python', '-c', 'print("test")']`
    :param environment: Edits the program's environment, a copy of
        this process's, when the program starts.
    :param directory: Where the program starts.
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
    :param helix_keys: Returns whether copy mode takes Helix's keys,
        through ptkhx, in place of prompt_toolkit's vi or emacs ones.
        The option that says so is the embedder's: pymux's
        `mode-keys`.
    :param wheel_lines: Returns how many lines one notch of the wheel
        moves copy mode. None moves half a window, as tmux's half-up.
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
        "helix_keys": Keep.REBUILT,
        "wheel_lines": Keep.REBUILT,
        "on_copy_command": Keep.REBUILT,
        "container": Keep.REBUILT,
        "terminal_window": Keep.REBUILT,
    }

    def __init__(
        self,
        command=["/bin/bash"],
        environment: Callable[[dict[str, str]], None] | None = None,
        directory: str | None = None,
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
        unreadable_key_func: Callable[[KeyEvent, int, str], None] | None = None,
        takes_key_first: Callable[[], bool] | None = None,
        key_profile_func: Callable[[], KeyProfile] | None = None,
        helix_keys: Callable[[], bool] | None = None,
        wheel_lines: Callable[[], int] | None = None,
    ) -> None:
        if backend is None:
            backend = create_backend(command, environment, directory)

        self._copy_func = copy_func
        self.helix_keys = helix_keys
        self.wheel_lines = wheel_lines
        #: Told each command a person runs in copy mode with Helix's keys:
        #: an editor command's keys (`Editor.finished`), or the key that
        #: copies or leaves. Never what is typed into the copy.
        self.on_copy_command: Callable[[str], None] | None = None

        self.terminal_control = TerminalControl(
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

        self.terminal_window = TerminalWindow(
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
