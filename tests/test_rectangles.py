"""
The four commands that take a rectangle of the screen.

DECFRA ("CSI Pch ; Pt ; Pl ; Pb ; Pr $ x") fills one with a character.
DECERA ("CSI Pt ; Pl ; Pb ; Pr $ z") erases one. DECSERA ("$ {") erases
one and leaves a cell that DECSCA marked alone. DECCRA ("$ v") copies
one to another place.

All four read the corners the same way. The numbers count from one,
origin mode counts them from the margins, and a margin does not hold
the rectangle in. None of the four moves the cursor.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

#: The screen that esctest draws before it takes a rectangle.
DATA = [
    "abcdefgh",
    "ijklmnop",
    "qrstuvwx",
    "yz012345",
    "ABCDEFGH",
    "IJKLMNOP",
    "QRSTUVWX",
    "YZ6789!@",
]


def _screen(lines=8, columns=8):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream


def _line(screen, row):
    buffer = screen.data_buffer[row + screen.line_offset]
    return "".join(
        (buffer[column].char or " ") if column in buffer else " "
        for column in range(screen.columns)
    )


def _lines(screen):
    return [_line(screen, row) for row in range(screen.lines)]


def _prepare(stream):
    # The last line carries no newline: one more would scroll the
    # screen and take the first line away.
    stream.feed("\x1b[1;1H" + "\r\n".join(DATA))


# ----------------------------------------------------------------------
# DECFRA.


def test_a_fill_takes_the_rectangle_it_names():
    screen, stream = _screen()
    _prepare(stream)
    stream.feed("\x1b[37;5;5;7;7$x")
    assert _lines(screen) == [
        "abcdefgh",
        "ijklmnop",
        "qrstuvwx",
        "yz012345",
        "ABCD%%%H",
        "IJKL%%%P",
        "QRST%%%X",
        "YZ6789!@",
    ]


def test_a_fill_of_a_rectangle_that_ends_before_it_starts_does_nothing():
    screen, stream = _screen()
    _prepare(stream)
    stream.feed("\x1b[37;5;5;4;4$x")
    assert _lines(screen) == DATA


def test_a_fill_with_no_corners_takes_the_whole_screen():
    screen, stream = _screen()
    _prepare(stream)
    stream.feed("\x1b[37$x")
    assert _lines(screen) == ["%" * 8] * 8


def test_a_fill_counts_the_corners_from_the_margins_in_origin_mode():
    screen, stream = _screen()
    _prepare(stream)
    stream.feed("\x1b[?69h\x1b[2;9s\x1b[2;9r\x1b[?6h")
    stream.feed("\x1b[37;1;1;3;3$x")
    stream.feed("\x1b[?69l\x1b[r\x1b[?6l")
    assert _lines(screen) == [
        "abcdefgh",
        "i%%%mnop",
        "q%%%uvwx",
        "y%%%2345",
        "ABCDEFGH",
        "IJKLMNOP",
        "QRSTUVWX",
        "YZ6789!@",
    ]


def test_a_fill_stops_at_the_edge_of_the_screen():
    screen, stream = _screen()
    _prepare(stream)
    stream.feed("\x1b[37;8;8;18;18$x")
    assert _line(screen, 7) == "YZ6789!%"


def test_a_fill_does_not_move_the_cursor():
    screen, stream = _screen()
    _prepare(stream)
    stream.feed("\x1b[4;3H")
    stream.feed("\x1b[37;2;2;4;4$x")
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (2, 3)


def test_a_fill_reaches_past_a_margin():
    screen, stream = _screen()
    _prepare(stream)
    stream.feed("\x1b[?69h\x1b[3;6s\x1b[3;6r")
    stream.feed("\x1b[37;5;5;7;7$x")
    stream.feed("\x1b[?69l\x1b[r")
    assert _lines(screen) == [
        "abcdefgh",
        "ijklmnop",
        "qrstuvwx",
        "yz012345",
        "ABCD%%%H",
        "IJKL%%%P",
        "QRST%%%X",
        "YZ6789!@",
    ]


def test_a_fill_drops_a_character_that_a_latin_1_terminal_has_no_cell_for():
    screen, stream = _screen()
    _prepare(stream)
    stream.feed("\x1b[7;5;5;7;7$x")
    assert _lines(screen) == DATA


def test_a_filled_cell_takes_the_rendition_that_is_set_now():
    screen, stream = _screen()
    stream.feed("\x1b[42m\x1b[37;1;1;1;2$x")
    row = screen.pt_screen.data_buffer[0]
    assert row[0].char == "%"
    assert "bg:" in row[0].style
    assert "bg:" in row[1].style


def test_a_filled_cell_carries_the_mark_of_decsca():
    screen, stream = _screen()
    stream.feed('\x1b[1"q\x1b[37;1;1;1;3$x\x1b[0"q')
    stream.feed("\x1b[1;1H\x1b[?2K")
    assert _line(screen, 0).rstrip() == "%%%"
