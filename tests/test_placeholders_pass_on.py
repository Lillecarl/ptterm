"""
An embedder whose terminal reads kitty's unicode placeholders gets them.

A pane draws an image cell as a space, because a terminal that does not
know the character paints a box. One that does fits the image to its
own cells, and that is the picture the program meant. So an embedder
that names the id its terminal knows the image by gets the placeholder,
in that id's colour. Lillecarl/pymux#600.
"""

from __future__ import annotations

import base64

from no_backend import NoBackend
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input import DummyInput
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Screen, WritePosition
from prompt_toolkit.output import DummyOutput
from pyte.placeholders import DIACRITICS, PLACEHOLDER

from ptterm.control import TerminalControl
from ptterm.window import TerminalWindow

LINES = 4
COLUMNS = 12
IMAGE = 5
OUTER = 0x123456


def mark(number):
    return chr(DIACRITICS[number])


def program_output():
    "A 4x2 virtual placement, and its cells: the second row names only its first cell."
    data = base64.b64encode(bytes(40 * 40 * 3)).decode()
    text = "\x1b_Ga=T,U=1,f=24,s=40,v=40,i=%i,c=4,r=2;%s\x1b\\" % (IMAGE, data)
    text += "\x1b[38;2;0;0;%im" % IMAGE
    text += "".join(PLACEHOLDER + mark(0) + mark(column) for column in range(4))
    text += "\r\n" + PLACEHOLDER + mark(1) + mark(0) + PLACEHOLDER * 3
    return text + "\x1b[0m"


def drawn(placeholder_ids):
    control = TerminalControl(backend=NoBackend())
    control.placeholder_ids = placeholder_ids
    control.create_content(COLUMNS, LINES)
    control.feed_output(program_output())
    window = TerminalWindow(terminal_control=control, content=control, wrap_lines=False)
    app = Application(layout=Layout(window), input=DummyInput(), output=DummyOutput())
    app.layout.update_parents_relations()
    screen = Screen()
    with set_app(app):
        window.write_to_screen(screen, MouseHandlers(), WritePosition(0, 0, COLUMNS, LINES), "", False, None)
    return screen.data_buffer


def test_with_no_ids_an_image_cell_is_a_space():
    rows = drawn(None)
    assert [rows[0][x].char for x in range(4)] == [" "] * 4


def test_with_ids_every_cell_names_its_place_in_the_outer_id():
    rows = drawn(lambda image_id: OUTER if image_id == IMAGE else 0)

    for row in range(2):
        for column in range(4):
            cell = rows[row][column]
            assert cell.char == PLACEHOLDER + mark(row) + mark(column), (row, column)
            assert cell.style.endswith("fg:#123456")
            assert cell.width == 1
    # The text after the image stands where it did.
    assert rows[0][4].char == " "
