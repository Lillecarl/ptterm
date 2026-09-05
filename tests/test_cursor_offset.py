"""
Where a pane tells prompt_toolkit its cursor is.

prompt_toolkit places a cursor by the number of characters before it on
the line, not by the column, because a double width character takes two
columns and one place.

The number it gets has to name a place **on** the line. A cursor outside
the line makes prompt_toolkit scroll the window sideways to bring it into
view, and then every row of the pane is drawn one column to the left for
as long as the scroll lasts. One character reaching the right edge moves
the whole pane.

`checks.pymux-vterm` is what found it: the pane's own screen was right,
and only a terminal reading what pymux emitted disagreed.
Lillecarl/pymux#62.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream
from ptterm.terminal import cursor_offset

COLUMNS = 8


def _screen(data, lines=4, columns=COLUMNS):
    screen = BetterScreen(lines, columns, write_process_input=lambda answer: None)
    BetterStream(screen).feed(data)
    return screen


def test_a_cursor_in_the_middle_of_a_line():
    assert cursor_offset(_screen("abc")) == 3


def test_a_cursor_that_waits_to_wrap_stands_on_the_last_column():
    """
    Eight characters fill the line. The cursor waits one column further,
    and the place it is drawn in is the last one on the line.
    """
    screen = _screen("abcdefgh")
    assert screen.pt_cursor_position.x == COLUMNS
    assert cursor_offset(screen) == COLUMNS - 1


def test_a_move_back_from_the_wait_counts_from_the_line():
    assert cursor_offset(_screen("abcdefgh\b")) == COLUMNS - 2


def test_the_offset_never_leaves_the_line():
    "Whatever a program does, the answer names a place on the line."
    for data in ["abcdefgh", "abcdefgh\t", "\x1b[8Gx", "abcdefghi"]:
        assert cursor_offset(_screen(data)) < COLUMNS


def test_a_double_width_character_takes_one_place_and_two_columns():
    """
    The cursor stands on column two and there is one character before
    it, which is the reason this counts rather than reads the column.
    """
    screen = _screen("你")
    assert screen.pt_cursor_position.x == 2
    assert cursor_offset(screen) == 1


def test_a_wait_after_a_double_width_character():
    "The last cell of the line is the second half of the character."
    screen = _screen("abcdef你")
    assert screen.pt_cursor_position.x == COLUMNS
    # Six narrow characters and one wide one, and the wide one counts
    # once. The cursor folds back onto the last column, which is the
    # half that holds no character of its own.
    assert cursor_offset(screen) == 7
