"""
The commands that move the columns of the scrolling region.

DECIC and DECDC insert and delete columns. DECBI and DECFI move the
cursor one column, and move the region when the cursor stands on a
margin. All four carry a rectangle: every row of the region moves, and
the cells outside the margins stay where they are.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def _screen(lines=5, columns=10):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream


def _line(screen, row):
    buffer = screen.data_buffer[row + screen.line_offset]
    return "".join(
        (buffer[column].char or " ") if column in buffer else " "
        for column in range(screen.columns)
    ).rstrip()


def _lines(screen):
    return [_line(screen, row) for row in range(screen.lines)]


#: Five rows of five letters each, in the first five columns.
GRID = ["abcde", "fghij", "klmno", "pqrst", "uvwxy"]


def _grid(stream, rows=GRID):
    for number, text in enumerate(rows, start=1):
        stream.feed("\x1b[%i;1H%s" % (number, text))


# ----------------------------------------------------------------------
# DECIC and DECDC.


def test_an_insert_of_columns_moves_every_row():
    screen, stream = _screen()
    _grid(stream)
    stream.feed("\x1b[1;2H\x1b['}")
    assert _lines(screen) == ["a bcde", "f ghij", "k lmno", "p qrst", "u vwxy"]


def test_an_insert_of_columns_takes_a_count():
    screen, stream = _screen()
    _grid(stream)
    stream.feed("\x1b[1;2H\x1b[2'}")
    assert _lines(screen) == ["a  bcde", "f  ghij", "k  lmno", "p  qrst",
                              "u  vwxy"]


def test_an_insert_of_columns_holds_to_the_rows_of_the_region():
    screen, stream = _screen()
    _grid(stream)
    stream.feed("\x1b[2;4r\x1b[2;2H\x1b['}")
    assert _lines(screen) == ["abcde", "f ghij", "k lmno", "p qrst", "uvwxy"]


def test_an_insert_of_columns_stops_at_the_right_margin():
    screen, stream = _screen()
    _grid(stream)
    stream.feed("\x1b[?69h\x1b[2;5s\x1b[1;3H\x1b['}")
    assert _lines(screen) == ["ab cd", "fg hi", "kl mn", "pq rs", "uv wx"]


def test_an_insert_of_columns_outside_the_margins_does_nothing():
    screen, stream = _screen()
    _grid(stream)
    stream.feed("\x1b[?69h\x1b[2;5s\x1b[1;1H\x1b[10'}")
    assert _lines(screen) == GRID


def test_a_delete_of_columns_moves_every_row():
    screen, stream = _screen()
    _grid(stream)
    stream.feed("\x1b[1;2H\x1b['~")
    assert _lines(screen) == ["acde", "fhij", "kmno", "prst", "uwxy"]


def test_a_delete_of_columns_takes_a_count():
    screen, stream = _screen()
    _grid(stream)
    stream.feed("\x1b[1;2H\x1b[2'~")
    assert _lines(screen) == ["ade", "fij", "kno", "pst", "uxy"]


def test_a_delete_of_columns_stops_at_the_right_margin():
    screen, stream = _screen()
    _grid(stream)
    stream.feed("\x1b[?69h\x1b[2;5s\x1b[1;3H\x1b['~")
    assert _lines(screen) == ["abde", "fgij", "klno", "pqst", "uvxy"]


def test_a_delete_of_columns_outside_the_margins_does_nothing():
    screen, stream = _screen()
    _grid(stream)
    stream.feed("\x1b[?69h\x1b[2;5s\x1b[1;1H\x1b[10'~")
    assert _lines(screen) == GRID


# ----------------------------------------------------------------------
# DECBI and DECFI.


def test_a_forward_index_moves_the_cursor_right():
    screen, stream = _screen()
    stream.feed("\x1b[2;5H\x1b9")
    assert screen.pt_cursor_position.x == 5


def test_a_back_index_moves_the_cursor_left():
    screen, stream = _screen()
    stream.feed("\x1b[2;5H\x1b6")
    assert screen.pt_cursor_position.x == 3


def test_a_forward_index_at_the_right_margin_moves_the_region():
    screen, stream = _screen()
    _grid(stream)
    stream.feed("\x1b[?69h\x1b[2;4s\x1b[2;4r\x1b[3;4H\x1b9")
    assert _lines(screen) == ["abcde", "fhi j", "kmn o", "prs t", "uvwxy"]
    assert screen.pt_cursor_position.x == 3


def test_a_back_index_at_the_left_margin_moves_the_region():
    screen, stream = _screen()
    _grid(stream)
    stream.feed("\x1b[?69h\x1b[2;4s\x1b[2;4r\x1b[3;2H\x1b6")
    assert _lines(screen) == ["abcde", "f ghj", "k lmo", "p qrt", "uvwxy"]
    assert screen.pt_cursor_position.x == 1


def test_a_forward_index_at_the_last_column_moves_the_screen():
    "Without margins the last column is the right margin."
    screen, stream = _screen()
    stream.feed("\x1b[1;10Hx\x1b[1;10H\x1b9")
    assert _line(screen, 0) == "        x"


def test_a_back_index_at_the_first_column_moves_the_screen():
    screen, stream = _screen()
    stream.feed("\x1b[1;1Hx\x1b[1;1H\x1b6")
    assert _line(screen, 0) == " x"


def test_a_forward_index_right_of_the_margin_moves_the_cursor():
    "DEC STD 070 lets the cursor move while it stands outside."
    screen, stream = _screen()
    stream.feed("\x1b[?69h\x1b[3;5s\x1b[1;6H\x1b9")
    assert screen.pt_cursor_position.x == 6


def test_a_back_index_left_of_the_margin_moves_the_cursor():
    screen, stream = _screen()
    stream.feed("\x1b[?69h\x1b[3;5s\x1b[1;2H\x1b6")
    assert screen.pt_cursor_position.x == 0
