"""
An erased cell takes the background that is set now.

A terminal that does not do this loses the colour bar that a program
draws with "CSI K", which is how htop paints the header of its table.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def _screen(lines=5, columns=20):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream


def _row(screen, y):
    return screen.pt_screen.data_buffer[y]


def test_erase_in_line_keeps_a_background():
    screen, stream = _screen()
    stream.feed("\x1b[42mhi\x1b[K")
    row = _row(screen, 0)
    assert row[0].char == "h"
    for column in range(2, 20):
        assert row[column].char == " "
        assert "bg:" in row[column].style


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
        assert "bg:" in row[column].style


def test_erase_the_whole_line_keeps_a_background():
    screen, stream = _screen()
    stream.feed("\x1b[41mhello\x1b[2K")
    row = _row(screen, 0)
    for column in range(0, 20):
        assert row[column].char == " "
        assert "bg:" in row[column].style


def test_reverse_video_paints_with_the_foreground():
    screen, stream = _screen()
    stream.feed("\x1b[31m\x1b[7mhi\x1b[K")
    row = _row(screen, 0)
    assert "reverse" in row[5].style
    assert "ansired" in row[5].style


def test_erase_in_display_keeps_a_background():
    screen, stream = _screen()
    stream.feed("hello\x1b[42m\x1b[2J")
    for y in range(5):
        row = _row(screen, y)
        for column in range(20):
            assert "bg:" in row[column].style


def test_erase_in_display_reaches_a_screen_that_holds_nothing():
    screen, stream = _screen()
    # No cell has been written yet, so there is nothing to take away.
    # The background still has to cover the screen.
    stream.feed("\x1b[42m\x1b[J")
    for y in range(5):
        row = _row(screen, y)
        for column in range(20):
            assert "bg:" in row[column].style


def test_erase_characters_takes_the_background_of_now():
    screen, stream = _screen()
    stream.feed("hello\x1b[1;1H\x1b[43m\x1b[3X")
    row = _row(screen, 0)
    for column in range(3):
        assert row[column].char == " "
        assert "bg:" in row[column].style
    assert row[3].char == "l"


def test_an_underline_reaches_the_erased_cells():
    screen, stream = _screen()
    # An underline shows on a blank, so it carries over the same way a
    # background does.
    stream.feed("\x1b[4mhi\x1b[K")
    row = _row(screen, 0)
    for column in range(2, 20):
        assert row[column].char == " "
        assert "underline" in row[column].style
