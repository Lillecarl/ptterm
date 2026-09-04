"""
Characters that a cell has to keep as they are.

A widget of prompt_toolkit shows some characters as something else, so
that a reader can see them: a no-break space becomes a space that is
underlined in yellow. A pane is not a widget. What a program wrote is
what the cell holds, and every emulator agrees.
"""
import pytest

from kitty_oracle import differences, kitty_is_available, ptterm_cells
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

NBSP = "\xa0"


def test_a_no_break_space_stays_a_no_break_space():
    "'tree' draws its indentation with them."
    cells = ptterm_cells("a" + NBSP + NBSP + "b", 2, 6)
    assert [cell.char for cell in cells[0][:4]] == ["a", NBSP, NBSP, "b"]


def test_a_no_break_space_carries_no_style_of_its_own():
    "The class of the widget would underline it in yellow."
    screen = BetterScreen(2, 6, write_process_input=lambda answer: None)
    stream = BetterStream(screen)
    stream.attach(screen)
    stream.feed("\x1b[31m" + NBSP)
    cell = screen.pt_screen.data_buffer[screen.line_offset][0]
    assert cell.char == NBSP
    assert "nbsp" not in cell.style


@pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)
def test_kitty_keeps_it_as_well():
    assert not differences("a" + NBSP + "b", lines=3, columns=8)
    assert not differences("│" + NBSP + NBSP + " x", lines=3, columns=8)
