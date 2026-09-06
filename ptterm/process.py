"""
The child process.
"""
import logging
import time
from asyncio import get_event_loop
from typing import Callable

from .backends import Backend
from .kitty_keys import translate_key_data
from .screen import BetterScreen
from .stream import BetterStream

__all__ = ["Process"]

logger = logging.getLogger(__name__)

#: How long a pane that nobody is looking at may wait before its output
#: is parsed, in seconds. One second means that a saturated machine
#: still parses a thousand bytes a second for such a pane, which is
#: enough that the interface never feels stuck.
POSTPONE = 1.0


def _when_the_loop_is_free(work: Callable[[], None], deadline: float) -> None:
    """
    Run `work` when the event loop has nothing else to do, or at
    `deadline`, whichever comes first.

    asyncio runs what is scheduled in the order it arrives, and that is
    the wrong order here: parsing the output of a pane that nobody is
    looking at may wait, and drawing for the person who is looking may
    not. A deadline keeps the wait from becoming a starve.

    This was `prompt_toolkit.eventloop.call_soon_threadsafe` with a
    `max_postpone_time`. Nothing in it is a toolkit's: it reads
    asyncio's own queue. Lillecarl/pymux#85.
    """
    loop = get_event_loop()

    def again() -> None:
        # `_ready` is what asyncio has queued. uvloop has no such
        # attribute, and then there is nothing to wait for.
        if not getattr(loop, "_ready", []) or time.time() > deadline:
            work()
            return
        loop.call_soon_threadsafe(again)

    loop.call_soon_threadsafe(again)


class Process:
    """
    Child process.
    Functionality for parsing the vt100 output (the Pyte screen and stream), as
    well as sending input to the process.

    Usage:

        p = Process(loop, ...):
        p.start()

    :param invalidate: When the screen content changes, and the renderer needs
        to redraw the output, this callback is called.
    :param bell_func: Called when the process does a `bell`.
    :param osc_func: Called with the code and the payload of an OSC
        sequence that only the terminal of the user can serve. (The
        clipboard, a notification, the shape of the pointer.)
    :param resize_func: Called with the lines and the columns that the
        program asks for, when it sends DECSLPP or a window resize.
        Either one is None when the program leaves that side alone. A
        pane cannot resize itself, so the embedder decides.
    :param may_resize: Returns whether the embedder would grant such an
        ask. The modes that only exist where a program can have a
        different page go away when it says no, so a program learns at
        once instead of laying its output out for room it will not get.
    :param done_callback: Called when the process terminates.
    :param has_priority: Callable that returns True when this Process should
        get priority in the event loop. (When this pane has the focus.)
        Otherwise output can be delayed.
    """

    def __init__(
        self,
        invalidate: Callable[[], None],
        backend: Backend,
        bell_func: Callable[[], None] | None = None,
        done_callback: Callable[[], None] | None = None,
        has_priority: Callable[[], bool] | None = None,
        osc_func: Callable[[str, str], None] | None = None,
        resize_func: Callable[[int | None, int | None], None] | None = None,
        may_resize: Callable[[], bool] | None = None,
    ) -> None:
        self.loop = get_event_loop()
        self.invalidate = invalidate
        self.backend = backend
        self.done_callback = done_callback
        self.has_priority = has_priority or (lambda: True)

        self.suspended = False
        self._reader_connected = False

        # Create terminal interface.
        self.backend.add_input_ready_callback(self._read)

        if done_callback is not None:
            self.backend.ready_f.add_done_callback(lambda _: done_callback())

        # Create output stream and attach to screen
        self.sx = 0
        self.sy = 0

        self.screen = BetterScreen(
            self.sx,
            self.sy,
            write_process_input=self.write_input,
            bell_func=bell_func,
            osc_func=osc_func,
            resize_func=resize_func,
            may_resize=may_resize,
        )

        self.stream = BetterStream(self.screen)
        self.stream.attach(self.screen)

    def start(self) -> None:
        """
        Start the process: fork child.

        The size the pane already has wins. A render sets the size and
        then starts the program, so the child forks onto a pty of the
        size it will really have. Without this the child forked at 120
        by 24, the pty resized one frame later, and a program that drew
        before the resize reached it drew at the wrong width. That is a
        race: the child starts writing as soon as it is forked, and the
        next render is a turn of the event loop away.

        A size of nothing means nobody has said, which is an embedder
        that starts the program before it draws. It gets what it always
        got.
        """
        if (self.sx, self.sy) == (0, 0):
            self.set_size(120, 24)
        self.backend.start()
        self.backend.connect_reader()

    def set_size(self, width: int, height: int) -> None:
        """
        Set terminal size.
        """
        if (self.sx, self.sy) != (width, height):
            self.backend.set_size(width, height)
        self.screen.resize(lines=height, columns=width)

        self.screen.lines = height
        self.screen.columns = width

        self.sx = width
        self.sy = height

    def write_input(self, data: str, paste: bool = False) -> None:
        """
        Write user key strokes to the input.

        :param data: (text, not bytes.) The input.
        :param paste: When True, and the process running here understands
            bracketed paste. Send as pasted text.
        """
        # send as bracketed paste?
        if paste and self.screen.bracketed_paste_enabled:
            data = "\x1b[200~" + data + "\x1b[201~"

        self.backend.write_text(data)

    def write_key_data(self, data: str) -> None:
        """
        Write raw key data, encoding it for this pane's keyboard mode.
        (The pane can request the kitty keyboard protocol; see
        `BetterScreen.kitty_keyboard_flags`.)

        The flags of the encoding are the ones that this pane really
        gets, not the ones it asked for. One value answers the query of
        the pane and drives the encoding, so the answer holds.
        """
        self.write_input(
            translate_key_data(
                data,
                flags=self.screen.deliverable_kitty_keyboard_flags,
                application_mode=self.screen.in_application_mode,
                source_flags=self.screen.keyboard_source_flags,
                synthesize=self.screen.synthesize_key_events,
            )
        )

    def _read(self) -> None:
        """
        Read callback, called by the loop.
        """
        d = self.backend.read_text(4096)
        assert isinstance(d, str), "got %r" % type(d)
        # Make sure not to read too much at once. (Otherwise, this
        # could block the event loop.)

        if not self.backend.closed:

            def process() -> None:
                try:
                    self.stream.feed(d)
                except Exception:
                    # One sequence that the emulator cannot handle must
                    # not stop the pane: the program would then wait
                    # forever for a reply that never comes.
                    logger.exception("Feeding the terminal emulator failed.")
                self.invalidate()

            # Feed directly, if this process has priority. (That is when this
            # pane has the focus in any of the clients.)
            if self.has_priority():
                process()

            # Otherwise, postpone processing until we have CPU time available.
            else:
                self.backend.disconnect_reader()

                def do_asap():
                    "Process output and reconnect to event loop."
                    process()
                    if not self.suspended:
                        self.backend.connect_reader()

                _when_the_loop_is_free(do_asap, time.time() + POSTPONE)
        else:
            # End of stream. Remove child.
            self.backend.disconnect_reader()

    def suspend(self) -> None:
        """
        Suspend process. Stop reading stdout. (Called when going into copy mode.)
        """
        if not self.suspended:
            self.suspended = True
            self.backend.disconnect_reader()

    def resume(self) -> None:
        """
        Resume from 'suspend'.
        """
        if self.suspended:
            self.backend.connect_reader()
            self.suspended = False

    def get_cwd(self) -> str:
        """
        The current working directory for this process. (Or `None` when
        unknown.)
        """
        return self.backend.get_cwd()

    def get_name(self) -> str:
        """
        The name for this process. (Or `None` when unknown.)
        """
        # TODO: Maybe cache for short time.
        return self.backend.get_name()

    def kill(self) -> None:
        """
        Kill process.
        """
        self.backend.kill()

    @property
    def is_terminated(self) -> bool:
        return self.backend.closed
