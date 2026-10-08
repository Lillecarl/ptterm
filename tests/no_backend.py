"""
A backend that starts no program.

`Process` needs one to build a screen. A test and a measurement both
want the screen and the widget around it, and neither wants a child on
a pty: nothing forks, so nothing has to be waited for or cleaned up.
"""

from __future__ import annotations

__all__ = ("NoBackend",)


class NoBackend:
    "The whole of the backend interface, doing nothing."

    def __init__(self) -> None:
        #: Every size the widget asked for, oldest first.
        self.sizes = []
        #: Every answer the screen sent back. A recording of a real
        #: program holds queries, and the screen replies to them, so a
        #: backend that cannot take an answer stops the run.
        self.written = []
        #: Whether there is anything more to read. Nothing here ever
        #: writes, so there never is and never was.
        self.closed = False
        #: The program ending. Nothing here ends, so there is none:
        #: `Process` waits on it for `done_callback`, and a backend
        #: with no end starts without a task group to watch it.
        self.ready_f = None

    def write_text(self, text: str) -> None:
        self.written.append(text)

    def add_input_ready_callback(self, callback) -> None:
        pass

    def set_size(self, width: int, height: int) -> None:
        self.sizes.append((width, height))

    async def start(self, task_group) -> None:
        pass

    def pause_reading(self) -> None:
        pass

    def resume_reading(self) -> None:
        "Copy mode suspends the process, which stops the reader."
