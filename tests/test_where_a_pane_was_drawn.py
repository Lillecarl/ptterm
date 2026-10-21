"""
Where a pane was drawn is a fact about each application that drew it.

pymux puts one terminal window in the layout of every client, and each
client draws it at its own place: one with the status bar on top, one
zoomed. URL mode and the link hints ask where a row of the page landed,
and they ask for the client in front of them. Lillecarl/pymux#713.
"""

from __future__ import annotations

from no_backend import NoBackend
from prompt_toolkit.application.current import set_app
from prompt_toolkit.application.dummy import DummyApplication
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen as PtScreen
from prompt_toolkit.layout.screen import WritePosition

from ptterm.terminal import Terminal

LINES = 6
COLUMNS = 20


def _an_application(terminal: Terminal) -> DummyApplication:
    app = DummyApplication()
    app.layout = Layout(terminal.container)
    return app


def _draw(terminal: Terminal, app: DummyApplication, xpos: int, ypos: int, height: int = LINES) -> None:
    with set_app(app):
        terminal.terminal_window.write_to_screen(
            PtScreen(),
            MouseHandlers(),
            WritePosition(xpos=xpos, ypos=ypos, width=COLUMNS, height=height),
            "",
            False,
            None,
        )


def a_terminal() -> Terminal:
    terminal = Terminal(backend=NoBackend())
    control = terminal.terminal_control
    control.create_content(COLUMNS, LINES)
    control.stream.feed("".join("row %d\r\n" % number for number in range(20)))
    return terminal


def test_each_application_reads_where_it_drew_the_pane():
    terminal = a_terminal()
    first, second = _an_application(terminal), _an_application(terminal)
    _draw(terminal, first, xpos=0, ypos=1)
    _draw(terminal, second, xpos=5, ypos=3, height=LINES - 2)
    bottom = terminal.terminal_control.screen.max_y

    with set_app(first):
        assert terminal.where_shown(bottom, 2) == (1 + LINES - 1, 2)
        assert terminal.shown_rows() == (bottom - LINES + 1, bottom)
    with set_app(second):
        top, last = terminal.shown_rows()
        assert last - top == LINES - 3
        assert terminal.where_shown(top, 2) == (3, 7)
        assert terminal.where_shown(top - 1, 2) is None


def test_an_application_that_never_drew_the_pane_knows_no_place():
    terminal = a_terminal()
    drew, never = _an_application(terminal), _an_application(terminal)
    _draw(terminal, drew, xpos=0, ypos=0)

    with set_app(never):
        assert terminal.shown_rows() is None
        assert terminal.where_shown(terminal.terminal_control.screen.max_y, 0) is None


def test_a_frame_drawn_again_from_the_cache_keeps_its_own_place():
    """
    A window that draws what it drew last writes the kept cells again,
    and the kept render info with them. The key holds the place, so a
    second application at another place draws afresh.
    """
    terminal = a_terminal()
    first, second = _an_application(terminal), _an_application(terminal)
    for _ in range(3):
        _draw(terminal, first, xpos=0, ypos=0)
        _draw(terminal, second, xpos=4, ypos=2)
    bottom = terminal.terminal_control.screen.max_y

    with set_app(first):
        assert terminal.where_shown(bottom, 0) == (LINES - 1, 0)
    with set_app(second):
        assert terminal.where_shown(bottom, 0) == (2 + LINES - 1, 4)
