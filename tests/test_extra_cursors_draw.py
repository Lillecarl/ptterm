"""
kitty's extra cursors, as the widget draws them: styled cells, since
prompt_toolkit has one cursor. Lillecarl/pyterm#893.
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

LINES, COLUMNS = 6, 12
STYLE = Style([])


class Pane:
    def __init__(self) -> None:
        self.control = TerminalControl(backend=NoBackend())
        self.window = TerminalWindow(terminal_control=self.control, content=self.control, wrap_lines=False)
        self.control.create_content(COLUMNS, LINES)

    def feed(self, data: str) -> None:
        self.control.stream.feed(data)

    def drawn(self) -> Screen:
        screen = Screen(default_char=None, initial_width=COLUMNS, initial_height=LINES)
        with set_app(DummyApplication()):
            self.window.write_to_screen(
                screen, MouseHandlers(), WritePosition(xpos=0, ypos=0, width=COLUMNS, height=LINES), "", True, None
            )
        return screen

    def attrs(self, x: int, y: int):
        return STYLE.get_attrs_for_style_str(self.drawn().data_buffer[y][x].style)

    def reversed_cells(self) -> set[tuple[int, int]]:
        screen = self.drawn()
        return {
            (x, y)
            for y in range(LINES)
            for x in range(COLUMNS)
            if STYLE.get_attrs_for_style_str(screen.data_buffer[y][x].style).reverse
        }


def test_a_block_reverses_its_cell():
    pane = Pane()
    pane.feed("hello\x1b[>1;2:1:2;2:3:5 q")
    assert pane.reversed_cells() == {(1, 0), (4, 2)}
    assert pane.drawn().data_buffer[0][1].char == "e"


def test_a_cursor_that_goes_away_takes_its_style():
    pane = Pane()
    pane.feed("hello\x1b[>1;2:1:2 q")
    assert pane.reversed_cells() == {(1, 0)}
    pane.feed("\x1b[>0;4 q")
    assert pane.reversed_cells() == set()


def test_an_embedder_that_draws_them_elsewhere_gets_no_cells():
    pane = Pane()
    native = [False]
    pane.control.draws_extra_cursors = lambda: not native[0]
    pane.feed("hello\x1b[>1;2:1:2 q")
    assert pane.reversed_cells() == {(1, 0)}
    native[0] = True
    assert pane.reversed_cells() == set()


def test_a_reversed_cell_turns_back():
    pane = Pane()
    pane.feed("\x1b[7mhi\x1b[m\x1b[>1;2:1:1 q")
    assert pane.reversed_cells() == {(1, 0)}


def test_an_underline_cursor_underlines():
    pane = Pane()
    pane.feed("abc\x1b[>3;2:1:3 q")
    assert pane.attrs(2, 0).underline
    assert not pane.attrs(2, 0).reverse


def test_the_main_shape_follows_decscusr():
    pane = Pane()
    pane.feed("\x1b[3 q\x1b[>29;2:2:2 q")
    assert pane.attrs(1, 1).underline
    pane.feed("\x1b[1 q")
    assert pane.attrs(1, 1).reverse


def test_a_cursor_colour_paints_the_cell():
    pane = Pane()
    pane.feed("ab\x1b[>40;2:255:0:0 q\x1b[>30;5:4 q\x1b[>1;2:1:1 q")
    attrs = pane.attrs(0, 0)
    assert attrs.bgcolor == "ff0000"
    assert attrs.color == "ansiblue"
    assert not attrs.reverse


def test_a_scroll_leaves_the_cursor_where_it_stood():
    pane = Pane()
    pane.feed("\x1b[>1;2:2:1 q" + "".join("line%d\r\n" % n for n in range(LINES + 2)))
    assert pane.reversed_cells() == {(0, 1)}


def test_a_wide_character_under_a_cursor_turns_whole():
    pane = Pane()
    pane.feed("a中b\x1b[>1;2:1:3 q")
    screen = pane.drawn()
    assert STYLE.get_attrs_for_style_str(screen.data_buffer[0][1].style).reverse
    assert not STYLE.get_attrs_for_style_str(screen.data_buffer[0][3].style).reverse
