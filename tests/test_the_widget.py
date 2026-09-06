"""
What the widget hands to prompt_toolkit, and what prompt_toolkit draws.

Every other suite here reads the screen. `panel.py` takes
`screen.line_offset` and walks `data_buffer` itself, and so does every
unit test. That is the model, and it is right; it is not what a person
sees.

Between the two sits a projection: `_TerminalControl.create_content`
turns a `BetterScreen` into a `UIContent`, and `_Window` picks the rows
of it that the pane shows. Nothing tested that, and a fault lived there.
An erase with no background drops the row it clears, so "CSI 1000 M"
near the top of a full screen took every row below it out of the
buffer. The widget reported the height of the buffer, prompt_toolkit
read a document shorter than the window, and it scrolled back to the
top. Lines that had left the screen came back.

Only Alacritty's reference tests found it, through pymux, at the far
end of a pty. This file asks the same questions here.

**These tests render.** They put the window on a real
`prompt_toolkit.layout.screen.Screen` and read the cells back, so the
answer is what prompt_toolkit draws and not what this file thinks it
would draw. A scroll that prompt_toolkit clamps is a scroll this file
sees clamped.

Lillecarl/pymux#84 asked for this.
"""
import asyncio

import pytest
from prompt_toolkit.application.current import set_app
from prompt_toolkit.application.dummy import DummyApplication
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.layout.screen import Char, Screen, WritePosition
from prompt_toolkit.styles import Style

from ptterm.terminal import _TerminalControl, _Window


class _NoBackend:
    """
    A backend that starts no program.

    `Process` needs one to build a screen, and these tests write to the
    screen themselves. Nothing here forks, so nothing here has to be
    waited for or cleaned up.
    """

    def __init__(self) -> None:
        self.sizes = []

    def add_input_ready_callback(self, callback) -> None:
        pass

    def set_size(self, width: int, height: int) -> None:
        self.sizes.append((width, height))

    def start(self) -> None:
        pass

    def connect_reader(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _a_loop():
    "`Process` reads the running event loop, and pytest starts none."
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    asyncio.set_event_loop(None)
    loop.close()


def rendered(data: str, lines: int = 8, columns: int = 12) -> Screen:
    "Put `data` through the widget and give back what prompt_toolkit drew."
    control = _TerminalControl(backend=_NoBackend())
    window = _Window(terminal_control=control, content=control, wrap_lines=False)

    # The size reaches the screen the way a render does, and then the
    # program writes. A write before the size lands on a screen of no
    # columns, which is not the question here.
    control.create_content(columns, lines)
    control.process.stream.feed(data)

    screen = Screen(default_char=None, initial_width=columns, initial_height=lines)
    with set_app(DummyApplication()):
        window.write_to_screen(
            screen,
            MouseHandlers(),
            WritePosition(xpos=0, ypos=0, width=columns, height=lines),
            "",
            True,
            None,
        )

    return screen


def drawn(data: str, lines: int = 8, columns: int = 12):
    """
    Put `data` through the widget and read back the rows that a person
    would see, top to bottom.
    """
    screen = rendered(data, lines, columns)
    rows = []
    for y in range(lines):
        row = screen.data_buffer[y]
        rows.append("".join(row[x].char for x in range(columns)).rstrip())
    return rows


def reversed_at(data: str, lines: int = 8, columns: int = 12):
    """
    Which cells prompt_toolkit draws reversed, as a row of booleans each.

    `drawn` reads the characters. This reads the style of the same
    cells, and it resolves the style the way a renderer does, so a
    "reverse" that a later "noreverse" cancels comes back false.
    """
    screen = rendered(data, lines, columns)
    style = Style([])
    return [
        [style.get_attrs_for_style_str(screen.data_buffer[y][x].style).reverse
         for x in range(columns)]
        for y in range(lines)
    ]


def test_reverse_video_turns_a_cell_that_a_program_wrote():
    "\"CSI ? 5 h\" is DECSCNM: the whole screen goes the other way."
    assert reversed_at("\x1b[?5hhi")[0][:2] == [True, True]


def test_reverse_video_turns_the_rest_of_the_row_as_well():
    """
    The screen is more than the cells a program wrote. A row that ends
    after two characters is reversed to the right edge of the pane.
    """
    assert reversed_at("\x1b[?5hhi")[0] == [True] * 12


def test_reverse_video_turns_a_row_that_holds_nothing():
    "An empty row is part of the screen, so it turns too."
    assert reversed_at("\x1b[?5hhi")[4] == [True] * 12


def test_reverse_video_cancels_a_reverse_that_a_program_set():
    """
    DECSCNM xors. A cell that "SGR 7" already reversed goes plain, and
    the cell beside it goes reversed. libvterm's `64screen_pen` asks
    this at lines 50 and 51.
    """
    assert reversed_at("\x1b[?5ha\x1b[7mb")[0][:2] == [True, False]


def test_a_cell_that_a_program_reversed_stays_reversed_without_the_mode():
    "The cancelling happens only while DECSCNM is on."
    assert reversed_at("a\x1b[7mb")[0][:2] == [False, True]


def test_reverse_video_goes_away_again():
    '"CSI ? 5 l" puts the screen back.'
    assert reversed_at("\x1b[?5hhi\x1b[?5l")[0] == [False] * 12


#: Twelve lines on a screen of eight, so four scroll away.
FILLED = "\r\n".join("line%d" % number for number in range(1, 13))


def test_the_widget_draws_the_screen():
    assert drawn("hello\r\nworld")[:2] == ["hello", "world"]


def test_the_widget_draws_the_bottom_of_a_screen_that_scrolled():
    "Four lines left the top, and they do not come back."
    assert drawn(FILLED) == [
        "line5",
        "line6",
        "line7",
        "line8",
        "line9",
        "line10",
        "line11",
        "line12",
    ]


def test_a_delete_of_every_line_below_the_cursor_keeps_the_history_away():
    """
    "CSI 1000 M" near the top of a full screen takes every row below it
    out of the buffer, because an erase with no background drops the
    row it clears.

    The screen still occupies those rows. Without this, prompt_toolkit
    reads a document shorter than the window, scrolls back to the top
    rather than past the end, and four lines that had left the screen
    come back.
    """
    rows = drawn(FILLED + "\x1b[3H\x1b[1000M")
    assert rows == ["line5", "line6", "", "", "", "", "", ""]


def test_an_erase_to_the_bottom_keeps_the_history_away():
    "\"CSI J\" drops the same rows, and the answer is the same."
    rows = drawn(FILLED + "\x1b[3H\x1b[J")
    assert rows == ["line5", "line6", "", "", "", "", "", ""]


def test_a_scroll_up_of_the_whole_screen_keeps_the_history_away():
    '"CSI 1000 S" empties the screen and leaves the history behind it.'
    assert drawn(FILLED + "\x1b[1000S") == [""] * 8


def test_the_line_count_covers_the_screen_and_not_the_buffer():
    """
    The count `create_content` reports is what the screen occupies.

    This is the contract that keeps prompt_toolkit from scrolling back:
    it does not scroll past the end of the document, so the document has
    to reach the bottom of the window.
    """
    control = _TerminalControl(backend=_NoBackend())
    control.create_content(12, 8)
    control.process.stream.feed(FILLED + "\x1b[3H\x1b[1000M")

    screen = control.process.screen
    content = control.create_content(12, 8)
    assert content.line_count >= screen.line_offset + screen.lines
    assert content.line_count == screen.max_y + 1


def test_the_cursor_is_drawn_where_a_program_is_told_it_stands():
    """
    prompt_toolkit places a cursor by the characters before it, and a
    double width character takes one cell of the document and two
    columns of the screen.
    """
    control = _TerminalControl(backend=_NoBackend())
    control.create_content(12, 8)
    control.process.stream.feed("中中x")
    content = control.create_content(12, 8)
    assert content.cursor_position.x == 3


def test_the_cursor_does_not_leave_the_line_while_it_waits_to_wrap():
    """
    A character in the last column leaves the cursor one column
    further, and that column is not on the line. prompt_toolkit answers
    a cursor outside the line by scrolling sideways, and then every row
    of the pane is drawn one column to the left.
    """
    control = _TerminalControl(backend=_NoBackend())
    control.create_content(4, 3)
    control.process.stream.feed("abcd")
    content = control.create_content(4, 3)
    assert content.cursor_position.x == 3


def test_a_placeholder_of_an_image_never_reaches_the_screen():
    """
    A unicode placeholder stands for a cell of an image, and the
    embedder draws the image. A terminal that does not know the
    character paints a box, and the marks that carry the row and the
    column pile up on it.
    """
    from ptterm.placeholders import PLACEHOLDER

    assert drawn(PLACEHOLDER + "x")[0] == " x"


def test_a_control_character_in_a_cell_is_drawn_as_a_blank():
    """
    The parser eats these, so one in a cell is a fault somewhere else.
    It must not reach the terminal of the user, which would read it as
    a control of its own.
    """
    control = _TerminalControl(backend=_NoBackend())
    control.create_content(6, 3)
    # prompt_toolkit's own `Char` swaps a control for "^A" as it is
    # built, so a cell can only hold one when that is turned off. This
    # is the cell the guard in `_visible_char` is there for.
    control.process.screen.pt_screen.data_buffer[0][0] = Char(
        "\x01", "", apply_display_mappings=False
    )
    content = control.create_content(6, 3)
    assert "".join(text for _, text in content.get_line(0))[0] == " "


def test_a_no_break_space_reaches_the_screen_as_it_stands():
    """
    prompt_toolkit draws a no-break space as an underlined yellow
    space, so that a reader of a widget can see one. A pane is not a
    widget: "tree" draws its indentation with them, and every emulator
    keeps them.
    """
    assert drawn("a\xa0b")[0] == "a\xa0b"


def test_the_first_render_sizes_the_pane_before_it_starts_the_program():
    """
    A render sets the size and then starts the program, so the child
    forks onto a pty of the size it will really have.

    `Process.start` put 120 by 24 on it first, and the pty resized one
    frame later. A program that drew before the resize reached it drew
    at the wrong width, and that is a race: the child writes as soon as
    it is forked.
    """
    backend = _NoBackend()
    control = _TerminalControl(backend=backend)
    control.create_content(12, 8)
    assert (control.process.screen.columns, control.process.screen.lines) == (12, 8)
    assert backend.sizes == [(12, 8)]
