"""
A pane that draws with the palette its program set, for an embedder
that lets it (`allow-program-palette` in pymux). Lillecarl/pyterm#18.
"""

from __future__ import annotations

from no_backend import NoBackend
from prompt_toolkit.application.current import set_app
from prompt_toolkit.application.dummy import DummyApplication
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.styles import Style

from ptterm.control import TerminalControl
from ptterm.window import TerminalWindow

LINES, COLUMNS = 4, 12
STYLE = Style([])
PINK = "\x1b]4;1;rgb:ff/00/ff\x1b\\"


class Pane:
    def __init__(self) -> None:
        self.control = TerminalControl(backend=NoBackend())
        self.window = TerminalWindow(terminal_control=self.control, content=self.control, wrap_lines=False)
        self.control.create_content(COLUMNS, LINES)
        self.allowed = [False]
        self.control.draws_program_palette = lambda: self.allowed[0]

    def feed(self, data: str) -> None:
        self.control.stream.feed(data)

    def attrs(self, x: int, y: int):
        screen = Screen(default_char=None, initial_width=COLUMNS, initial_height=LINES)
        with set_app(DummyApplication()):
            self.window.write_to_screen(
                screen, MouseHandlers(), WritePosition(xpos=0, ypos=0, width=COLUMNS, height=LINES), "", True, None
            )
        return STYLE.get_attrs_for_style_str(screen.data_buffer[y][x].style)


def test_a_palette_colour_draws_as_its_number_by_default():
    pane = Pane()
    pane.feed(PINK + "\x1b[31mred")
    assert pane.attrs(0, 0).color == "ansired"


def test_an_allowed_pane_draws_what_its_program_set():
    pane = Pane()
    pane.allowed[0] = True
    pane.feed(PINK + "\x1b[31;41mred\x1b[m \x1b[32mgreen")
    attrs = pane.attrs(0, 0)
    assert (attrs.color, attrs.bgcolor) == ("ff00ff", "ff00ff")
    assert pane.attrs(4, 0).color == "ansigreen"


def test_a_kept_row_draws_again_when_the_palette_changes():
    pane = Pane()
    pane.allowed[0] = True
    pane.feed("\x1b[31mred")
    assert pane.attrs(0, 0).color == "ansired"
    pane.feed(PINK)
    assert pane.attrs(0, 0).color == "ff00ff"
    pane.feed("\x1b]104;1\x1b\\")
    assert pane.attrs(0, 0).color == "ansired"


def test_turning_it_off_gives_the_theme_back():
    pane = Pane()
    pane.allowed[0] = True
    pane.feed(PINK + "\x1b[31mred")
    assert pane.attrs(0, 0).color == "ff00ff"
    pane.allowed[0] = False
    assert pane.attrs(0, 0).color == "ansired"


def test_the_same_entries_give_the_same_palette():
    pane = Pane()
    pane.feed(PINK)
    colors = pane.control.screen.colors
    assert colors.program_palette() is colors.program_palette()
    pane.feed("\x1b]4;1;rgb:ff/00/ff\x1b\\")
    assert colors.program_palette() is colors.program_palette()
    pane.feed("\x1b]104\x1b\\")
    assert colors.program_palette() is None
