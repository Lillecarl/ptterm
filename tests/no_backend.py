"""
A backend that starts no program.

`Process` needs one to build a screen. A test and a measurement both
want the screen and the widget around it, and neither wants a child on
a pty: nothing forks, so nothing has to be waited for or cleaned up.
"""

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

    def write_text(self, text: str) -> None:
        self.written.append(text)

    def add_input_ready_callback(self, callback) -> None:
        pass

    def set_size(self, width: int, height: int) -> None:
        self.sizes.append((width, height))

    def start(self) -> None:
        pass

    def connect_reader(self) -> None:
        pass

    def disconnect_reader(self) -> None:
        "Copy mode suspends the process, which stops the reader."
