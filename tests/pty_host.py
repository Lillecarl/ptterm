"""
A terminal with no widget around it: a screen, and a program on a pty
that draws on it.

A `Process` runs a program and pumps its bytes; it parses nothing, so
whoever builds one decides what the bytes mean (Lillecarl/pymux#85).
A front end pairs it with a screen, and so does every suite here that
drives a real program: `drive_with_esctest.py` and
`drive_with_vttest.py` both want the pair and neither wants a widget.

This host owns its pty, so it answers a resize itself. A pane cannot:
it would be taking room from the panes beside it, so ptterm hands the
ask to the embedder instead.
"""
from ptterm.graphics import ASSUMED_CELL_HEIGHT, ASSUMED_CELL_WIDTH
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream
from ptyhost import Process
from ptyhost.backends.posix import PosixBackend

__all__ = ("Host",)


class Host:
    """
    The pair, and the resize policy that goes with owning the pty.

    :param command: the program to run, as a list.
    :param columns, lines: the size the child forks onto. The size goes
        first on purpose: the child reads it before it writes anything,
        and `Process.start` would otherwise pick 120 by 24.
    :param smallest, largest: what a program may ask to be resized to.
        A trial that asks for a million rows gets a refusal, the way a
        real terminal refuses.
    :param done_callback: called when the program ends.
    :param prepare: called with the backend before the child forks, for
        a suite that wants to change the pty or watch the bytes.
    """

    def __init__(
        self,
        command,
        columns: int,
        lines: int,
        smallest: int = 1,
        largest: int = 500,
        done_callback=None,
        prepare=None,
    ) -> None:
        self.smallest = smallest
        self.largest = largest

        self.backend = PosixBackend.from_command(
            command, cell=(ASSUMED_CELL_WIDTH, ASSUMED_CELL_HEIGHT)
        )
        if prepare is not None:
            prepare(self.backend)

        self.screen = BetterScreen(
            lines,
            columns,
            write_process_input=lambda data: self.process.write_input(data),
            resize_func=self.resize,
        )
        self.stream = BetterStream(self.screen)
        self.stream.attach(self.screen)

        self.process = Process(
            backend=self.backend,
            receive=self.stream.feed,
            done_callback=done_callback,
        )
        self.set_size(columns, lines)

    def set_size(self, columns: int, lines: int) -> None:
        "Tell the pty and the screen how big they are."
        self.process.set_size(columns, lines)
        self.screen.resize(lines=lines, columns=columns)
        self.screen.lines = lines
        self.screen.columns = columns

    def resize(self, lines, columns) -> None:
        """
        Take the size the program asks for.

        A side the program leaves alone arrives as `None` and keeps the
        size it has.
        """
        width = self.process.sx if columns is None else columns
        height = self.process.sy if lines is None else lines
        if not self.smallest <= width <= self.largest:
            return
        if not self.smallest <= height <= self.largest:
            return
        self.set_size(width, height)

    def start(self) -> None:
        "Fork the child onto the pty, and start reading it."
        self.backend.start()
        self.backend.connect_reader()

    def write(self, text: str) -> None:
        "Send text to the program, as it stands."
        self.process.write_input(text)

    def kill(self) -> None:
        self.backend.kill()
