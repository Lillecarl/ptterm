"""
An erased cell takes the background that is set now.

A terminal that does not do this loses the colour bar that a program
draws with "CSI K", which is how htop paints the header of its table.
"""
from pyte.colors import SgrColor
from pyte.screen import Screen, WrittenCell
from pyte.streams import Stream


def _screen(lines=5, columns=20):
    screen = Screen(lines, columns, write_process_input=lambda data: None)
    stream = Stream(screen)
    return screen, stream


def _row(screen, y):
    return screen.page.data_buffer[y]


def _rendition(row, column):
    "How one cell of a row asks to be drawn."
    return row[column].appearance.rendition


def test_an_erased_cell_and_a_written_blank_look_the_same():
    """
    A cell holds only what an erase can carry: the background, and the
    reverse with the foreground it paints. A program that writes a
    space under the same background asks for the same picture, so the
    two cells compare equal and a renderer draws no change between
    them.

    The class still tells them apart, and that is the difference that
    matters: a combining mark hangs on a written space and falls off an
    erased cell, and the renderer keeps a written blank at the end of a
    row. Lillecarl/pymux#56.
    """
    screen, stream = _screen()
    stream.feed("\x1b[42m \x1b[1;2H\x1b[K")
    row = _row(screen, 0)
    written, erased = row[0], row[1]
    assert written == erased
    assert isinstance(written, WrittenCell)
    assert not isinstance(erased, WrittenCell)


def test_erase_in_line_keeps_a_background():
    screen, stream = _screen()
    stream.feed("\x1b[42mhi\x1b[K")
    row = _row(screen, 0)
    assert row[0].char == "h"
    for column in range(2, 20):
        assert row[column].char == " "
        assert _rendition(row, column).bgcolor is not None


def test_erase_in_line_stays_sparse_without_a_background():
    screen, stream = _screen()
    stream.feed("hi\x1b[K")
    # "CSI K" erases from the cursor, so "hi" stays and nothing after
    # it takes a cell.
    assert set(_row(screen, 0)) == {0, 1}


def test_erase_in_line_to_the_left_keeps_a_background():
    screen, stream = _screen()
    stream.feed("\x1b[44mhello\x1b[1K")
    row = _row(screen, 0)
    for column in range(0, 6):
        assert row[column].char == " "
        assert _rendition(row, column).bgcolor is not None


def test_erase_the_whole_line_keeps_a_background():
    screen, stream = _screen()
    stream.feed("\x1b[41mhello\x1b[2K")
    row = _row(screen, 0)
    for column in range(0, 20):
        assert row[column].char == " "
        assert _rendition(row, column).bgcolor is not None


def test_reverse_video_paints_with_the_foreground():
    screen, stream = _screen()
    stream.feed("\x1b[31m\x1b[7mhi\x1b[K")
    row = _row(screen, 0)
    assert _rendition(row, 5).reverse
    assert _rendition(row, 5).color == SgrColor(index=1)


def test_erase_in_display_keeps_a_background():
    screen, stream = _screen()
    stream.feed("hello\x1b[42m\x1b[2J")
    for y in range(5):
        row = _row(screen, y)
        for column in range(20):
            assert _rendition(row, column).bgcolor is not None


def test_erase_in_display_reaches_a_screen_that_holds_nothing():
    screen, stream = _screen()
    # No cell has been written yet, so there is nothing to take away.
    # The background still has to cover the screen.
    stream.feed("\x1b[42m\x1b[J")
    for y in range(5):
        row = _row(screen, y)
        for column in range(20):
            assert _rendition(row, column).bgcolor is not None


def test_erase_characters_takes_the_background_of_now():
    screen, stream = _screen()
    stream.feed("hello\x1b[1;1H\x1b[43m\x1b[3X")
    row = _row(screen, 0)
    for column in range(3):
        assert row[column].char == " "
        assert _rendition(row, column).bgcolor is not None
    assert row[3].char == "l"


def test_an_underline_reaches_no_erased_cell():
    """
    An underline does not carry over, and a background does.

    ptterm carried it, on the reading that a reader sees a line on a
    blank. Five judges say no and only kitty says yes, for both ED and
    EL, and `test_the_panel.py` holds that tally. A shell that leaves
    the underline on and clears the screen underlined every blank cell
    of it. Lillecarl/pymux#67.
    """
    screen, stream = _screen()
    stream.feed("\x1b[4mhi\x1b[K")
    row = _row(screen, 0)
    for column in range(2, 20):
        assert not _rendition(row, column).underline


def test_a_background_still_reaches_the_erased_cells():
    "The other half of the same question, and the panel is five to one."
    screen, stream = _screen()
    stream.feed("\x1b[41mhi\x1b[K")
    row = _row(screen, 0)
    for column in range(2, 20):
        assert row[column].char == " "
        assert _rendition(row, column).bgcolor is not None


# ----------------------------------------------------------------------
# "CSI 3 J" takes the history, and leaves the screen as it is.


def _line(screen, y):
    row = screen.data_buffer[y + screen.line_offset]
    return "".join(
        (row[column].char or " ") if column in row else " "
        for column in range(screen.columns)
    ).rstrip()


def test_erasing_the_history_leaves_the_screen():
    screen, stream = _screen(lines=3)
    stream.feed("one\r\ntwo\r\nthree\r\nfour")
    stream.feed("\x1b[3J")
    assert [_line(screen, row) for row in range(3)] == ["two", "three", "four"]


def test_erasing_the_history_takes_the_lines_above_the_screen():
    screen, stream = _screen(lines=3)
    stream.feed("one\r\ntwo\r\nthree\r\nfour")
    stream.feed("\x1b[3J")
    assert min(screen.data_buffer) >= screen.line_offset
