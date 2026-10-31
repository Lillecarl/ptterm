"""
A pane that drew every frame shows what a pane drawing once shows.

`create_content` keeps the line it built for each row, and the window
keeps what it wrote for each line and rotates it on a scroll. So the
same bytes, drawn after every write or once at the end, have to give
the same cells, styles included.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from no_backend import NoBackend
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input import DummyInput
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.output import DummyOutput

from ptterm.control import TerminalControl
from ptterm.window import TerminalWindow

LINES = 6
COLUMNS = 24
CLEAR = "\x1b[2J\x1b[3J\x1b[H"


class Pane:
    def __init__(self) -> None:
        self.control = TerminalControl(backend=NoBackend())
        self.control.create_content(COLUMNS, LINES)
        self.window = TerminalWindow(terminal_control=self.control, content=self.control, wrap_lines=False)
        self.app = Application(layout=Layout(self.window), input=DummyInput(), output=DummyOutput())
        self.app.layout.update_parents_relations()

    def draw(self) -> list:
        screen = Screen()
        position = WritePosition(xpos=0, ypos=0, width=COLUMNS, height=LINES)
        with set_app(self.app):
            self.window.write_to_screen(screen, MouseHandlers(), position, "", False, None)
        rows = screen.data_buffer
        return [[(rows[y][x].char, rows[y][x].style) for x in range(COLUMNS)] for y in range(LINES)]


def drawn_every_write(chunks: list[str], frames: list[bool] | None = None) -> list:
    "With `frames`, a frame follows only the writes it marks, as a busy loop coalesces them."
    pane = Pane()
    pane.draw()
    for number, chunk in enumerate(chunks):
        pane.control.feed_output(chunk)
        if frames is None or frames[number % len(frames)]:
            pane.draw()
    return pane.draw()


def drawn_once(chunks: list[str]) -> list:
    pane = Pane()
    pane.control.feed_output("".join(chunks))
    return pane.draw()


def coloured(n: int) -> str:
    return f"\x1b[48;5;{n}mline {n}\x1b[K\x1b[0m\r\n"


def test_a_clear_after_a_coloured_history():
    "Claude Code's /clear: erase the screen, then the history."
    chunks = [coloured(n) for n in range(1, 15)]
    chunks.append(CLEAR)
    chunks.append("\x1b[48;5;236mprompt\x1b[K\x1b[0m\r\n")
    assert drawn_every_write(chunks) == drawn_once(chunks)


SEQUENCES = st.sampled_from(
    [
        "text",
        "\r\n",
        "\x1b[48;5;52m",
        "\x1b[48;5;236m",
        "\x1b[41m",
        "\x1b[7m",
        "\x1b[0m",
        "\x1b[K",
        "\x1b[1K",
        "\x1b[2K",
        "\x1b[J",
        "\x1b[1J",
        "\x1b[2J",
        "\x1b[3J",
        CLEAR,
        "\x1b[H",
        "\x1b[3;1H",
        "\x1b[6;1H",
        "\x1b[A",
        "\x1b[1B",
        "\x1b[2;5r",
        "\x1b[r",
        "\x1b[S",
        "\x1b[T",
        "\x1b[L",
        "\x1b[M",
        "\x1b[2X",
        "\x1b[P",
        "\x1b[@",
        "\x1bM",
        "\x1bD",
        "\x1b[?1049h",
        "\x1b[?1049l",
        "\x1b[?5h",
        "\x1b[?5l",
        "\x1bc",
    ]
)


@given(
    st.lists(st.lists(SEQUENCES, min_size=1, max_size=6).map("".join), max_size=25),
    st.lists(st.booleans(), min_size=1, max_size=8),
)
@settings(max_examples=3000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_any_bytes_draw_the_same_cells(chunks, frames):
    assert drawn_every_write(chunks, frames) == drawn_once(chunks)
