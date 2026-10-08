"""
A painted screen reaches the copy painted, in every cell.

`test_scroll_background` pins what one erased cell carries. This pins
what the copy draws from it: a background a program sets has to cover
every column of every row it paints, and a cell no program wrote still
has to draw -- with the default background, and not transparent. A
transparent cell shows whatever a layer below drew, and the layout
background is for the margins where no pane draws, not for the rows a
pane left empty.
"""

from __future__ import annotations

from no_backend import NoBackend
from prompt_toolkit.application.current import set_app
from prompt_toolkit.application.dummy import DummyApplication
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.styles import Style
from pyte import escape
from pyte.sequences import Csi, csi
from test_the_widget import rendered

from ptterm.terminal import _TerminalControl, _Window


def backgrounds(data: str, lines: int = 8, columns: int = 12) -> list[list[bool]]:
    "Whether each cell of the copy carries a background colour."
    screen = rendered(data, lines, columns)
    style = Style([])
    return [
        [bool(style.get_attrs_for_style_str(screen.data_buffer[y][x].style).bgcolor) for x in range(columns)]
        for y in range(lines)
    ]


def test_an_erase_with_a_background_paints_every_cell():
    painted = backgrounds(csi(escape.CUP, 1, 1) + csi(escape.SGR, 41) + csi(escape.ED, 2))
    assert all(all(row) for row in painted)


def test_a_scrolled_line_paints_every_cell():
    "Only the line the scroll brings in takes the background."
    painted = backgrounds(csi(escape.SGR, 42) + csi(Csi.SU, 1))
    assert painted[-1] == [True] * 12
    assert all(not any(row) for row in painted[:-1])


def test_a_scroll_keeps_the_paint_of_the_lines_it_moves():
    "Paint the screen, write on every line, scroll: all eight stay painted."
    painted = backgrounds(
        csi(escape.SGR, 42)
        + csi(escape.ED, 2)
        + "".join(csi(escape.CUP, row, 1) + f"line{row}" for row in range(1, 9))
        + csi(Csi.SU, 1)
    )
    assert all(all(row) for row in painted)


def test_a_line_a_shell_clears_keeps_its_background():
    "Text, then back to its start and erase the line: the row stays painted."
    painted = backgrounds(csi(escape.SGR, 42) + "hi" + csi(escape.CUP, 1, 1) + csi(escape.EL, 0))
    assert painted[0] == [True] * 12


def painted_frames(*parts: str, lines: int = 8, columns: int = 12) -> list[list[list[bool]]]:
    "What each frame of one control draws, so a redraw answers for itself."
    control = _TerminalControl(backend=NoBackend())
    window = _Window(terminal_control=control, content=control, wrap_lines=False)
    control.create_content(columns, lines)
    style = Style([])
    frames = []
    for part in parts:
        control.stream.feed(part)
        screen = Screen(default_char=None, initial_width=columns, initial_height=lines)
        with set_app(DummyApplication()):
            window.write_to_screen(
                screen,
                MouseHandlers(),
                WritePosition(xpos=0, ypos=0, width=columns, height=lines),
                "",
                False,
                None,
            )
        frames.append(
            [
                [bool(style.get_attrs_for_style_str(screen.data_buffer[y][x].style).bgcolor) for x in range(columns)]
                for y in range(lines)
            ]
        )
    return frames


def test_a_redrawn_line_keeps_its_background():
    "A prompt frame, then the shell clears it: the second frame stays painted."
    _, cleared = painted_frames(csi(escape.SGR, 42) + "hi", csi(escape.CUP, 1, 1) + csi(escape.EL, 0))
    assert cleared[0] == [True] * 12


def opacities(data: str, lines: int = 8, columns: int = 12) -> list[list[bool]]:
    "Whether each cell of the copy is drawn, and not left transparent."
    screen = rendered(data, lines, columns)
    return [[screen.data_buffer[y][x].style != "[transparent]" for x in range(columns)] for y in range(lines)]


def test_a_shell_leaves_no_cell_transparent():
    "A prompt and its output cover three lines, and all eight still draw."
    opaque = opacities("prompt> output here" + csi(escape.CUP, 2, 1) + "second line")
    assert all(all(row) for row in opaque)
