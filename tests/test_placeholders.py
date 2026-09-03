"""
Tests for the unicode placeholders of the kitty graphics protocol.

A program transmits a virtual placement and then writes one character
per cell. The cells carry the image id in their foreground colour and
the row and the column in combining characters. The terminal reads the
screen back to find out what to draw.
"""
import base64

import pytest

from ptterm.placeholders import DIACRITICS, PLACEHOLDER, foreground_id
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def make_screen(lines=24, columns=80):
    responses = []
    screen = BetterScreen(lines, columns, write_process_input=responses.append)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream, responses


def mark(number):
    "The combining character that stands for a row or a column."
    return chr(DIACRITICS[number])


def cells(image_id, row, columns, marks=True):
    """
    The text of one row of placeholder cells, with the foreground
    colour that carries the id.
    """
    red, green, blue = (image_id >> 16) & 0xFF, (image_id >> 8) & 0xFF, image_id & 0xFF
    text = "\x1b[38;2;%i;%i;%im" % (red, green, blue)
    for column in range(columns):
        text += PLACEHOLDER
        if marks:
            text += mark(row) + mark(column)
    return text + "\x1b[0m"


def rgb_image(width, height):
    return bytes([(x * 7) % 256 for x in range(width * height * 3)])


def transmit_virtual(stream, image_id, width, height):
    "A virtual placement: it covers no cells of its own."
    data = base64.b64encode(rgb_image(width, height)).decode()
    stream.feed(
        "\x1b_Ga=T,U=1,f=24,s=%i,v=%i,i=%i;%s\x1b\\"
        % (width, height, image_id, data)
    )


# ----------------------------------------------------------------------
# Reading a cell.


def test_the_id_comes_from_the_foreground_colour():
    assert foreground_id("#010203") == 0x010203
    assert foreground_id("#010203 bg:#ffffff bold") == 0x010203
    assert foreground_id("bg:#ffffff") == 0
    assert foreground_id("") == 0


def test_the_first_diacritic_means_zero():
    assert DIACRITICS[0] == 0x305
    assert len(DIACRITICS) == 297


# ----------------------------------------------------------------------
# Finding the runs.


def test_a_row_of_cells_is_one_run():
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 40, 40)
    stream.feed(cells(5, 0, 4))
    runs = screen.placeholder_runs(0, 0)
    assert len(runs) == 1
    run = runs[0]
    assert (run.image_id, run.row, run.column, run.columns) == (5, 0, 0, 4)
    assert (run.image_row, run.image_column) == (0, 0)


def test_the_row_of_the_image_is_read():
    "The first mark says which row of the image a cell shows."
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 40, 60)
    stream.feed(cells(5, 2, 3))
    runs = screen.placeholder_runs(0, 0)
    assert [(run.row, run.image_row) for run in runs] == [(0, 2)]


def test_a_cell_without_marks_follows_the_one_to_its_left():
    "A program may write the marks on the first cell only."
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 40, 40)
    stream.feed("\x1b[38;2;0;0;5m" + PLACEHOLDER + mark(2) + mark(0))
    stream.feed(PLACEHOLDER + PLACEHOLDER + "\x1b[0m")
    runs = screen.placeholder_runs(0, 0)
    assert len(runs) == 1
    run = runs[0]
    assert (run.columns, run.image_row, run.image_column) == (3, 2, 0)


def test_text_between_two_images_breaks_the_run():
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 40, 40)
    transmit_virtual(stream, 6, 40, 40)
    stream.feed(cells(5, 0, 2) + "ab" + cells(6, 0, 2))
    runs = screen.placeholder_runs(0, 0)
    assert [(run.image_id, run.column, run.columns) for run in runs] == [
        (5, 0, 2),
        (6, 4, 2),
    ]


def test_a_gap_in_the_columns_breaks_the_run():
    "The columns of a run count up, one by one."
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 40, 40)
    stream.feed("\x1b[38;2;0;0;5m")
    stream.feed(PLACEHOLDER + mark(0) + mark(0))
    stream.feed(PLACEHOLDER + mark(0) + mark(5))
    stream.feed("\x1b[0m")
    runs = screen.placeholder_runs(0, 0)
    assert [(run.column, run.columns, run.image_column) for run in runs] == [
        (0, 1, 0),
        (1, 1, 5),
    ]


def test_the_third_mark_carries_the_top_of_the_id():
    screen, stream, _r = make_screen()
    image_id = (3 << 24) | 0x0405_06 % 0x1000000
    transmit_virtual(stream, image_id, 40, 40)
    text = "\x1b[38;2;%i;%i;%im" % (
        (image_id >> 16) & 0xFF,
        (image_id >> 8) & 0xFF,
        image_id & 0xFF,
    )
    text += PLACEHOLDER + mark(0) + mark(0) + mark(3)
    stream.feed(text + "\x1b[0m")
    runs = screen.placeholder_runs(0, 0)
    assert [run.image_id for run in runs] == [image_id]


def test_a_cell_without_a_colour_names_no_image():
    "An id of zero is not an image, so nothing is drawn."
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 40, 40)
    stream.feed(PLACEHOLDER + mark(0) + mark(0))
    assert screen.placeholder_runs(0, 0) == []


# ----------------------------------------------------------------------
# The cost of a pane that shows no image.


def test_a_pane_without_a_virtual_placement_is_not_scanned():
    screen, stream, _r = make_screen()
    stream.feed(cells(5, 0, 4))  # Placeholders, but no placement.
    assert screen.placeholder_runs(0, 23) == []


def test_a_plain_placement_does_not_turn_the_scan_on():
    screen, stream, _r = make_screen()
    data = base64.b64encode(rgb_image(40, 40)).decode()
    stream.feed("\x1b_Ga=T,f=24,s=40,v=40,i=7;%s\x1b\\" % data)
    assert not screen.graphics.has_virtual_placements
    assert screen.placeholder_runs(0, 23) == []


# ----------------------------------------------------------------------
# The placement that a run points at.


def test_the_run_finds_its_placement():
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 40, 40)
    placement = screen.graphics.virtual_placement(5)
    assert placement is not None
    assert placement.virtual
    # 40 pixels is four columns and two rows of the assumed cell.
    assert (placement.columns, placement.rows) == (4, 2)


def test_a_run_of_an_unknown_image_finds_no_placement():
    screen, _stream, _r = make_screen()
    assert screen.graphics.virtual_placement(99) is None


def test_a_virtual_placement_covers_no_cells():
    "The text stays: the placeholders are the text."
    screen, stream, _r = make_screen()
    stream.feed("abcd")
    transmit_virtual(stream, 5, 40, 40)
    line = screen.pt_screen.data_buffer[0]
    assert "".join(line[x].char for x in range(4)) == "abcd"


# ----------------------------------------------------------------------
# Joining the lines of one image.


def test_the_lines_of_one_image_become_one_rectangle():
    "A screen full of one image costs one escape sequence, not one a line."
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 40, 60)
    for row in range(3):
        stream.feed(cells(5, row, 4) + "\r\n")
    runs = screen.placeholder_runs(0, 2)
    assert len(runs) == 1
    run = runs[0]
    assert (run.row, run.column, run.columns, run.rows) == (0, 0, 4, 3)
    assert (run.image_row, run.image_column) == (0, 0)


def test_lines_of_different_widths_stay_apart():
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 40, 60)
    stream.feed(cells(5, 0, 4) + "\r\n" + cells(5, 1, 2))
    runs = screen.placeholder_runs(0, 1)
    assert [(run.row, run.columns, run.rows) for run in runs] == [(0, 4, 1), (1, 2, 1)]


def test_a_line_of_another_image_stays_apart():
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 40, 60)
    transmit_virtual(stream, 6, 40, 60)
    stream.feed(cells(5, 0, 4) + "\r\n" + cells(6, 1, 4))
    runs = screen.placeholder_runs(0, 1)
    assert [(run.image_id, run.rows) for run in runs] == [(5, 1), (6, 1)]


def test_a_gap_between_the_lines_stays_apart():
    "The rows of an image follow each other, on screen and in the image."
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 40, 80)
    stream.feed(cells(5, 0, 4) + "\r\n" + cells(5, 2, 4))
    runs = screen.placeholder_runs(0, 1)
    assert [(run.image_row, run.rows) for run in runs] == [(0, 1), (2, 1)]


def test_two_images_side_by_side_each_join():
    screen, stream, _r = make_screen()
    transmit_virtual(stream, 5, 20, 60)
    transmit_virtual(stream, 6, 20, 60)
    for row in range(2):
        stream.feed(cells(5, row, 2) + cells(6, row, 2) + "\r\n")
    runs = screen.placeholder_runs(0, 1)
    assert [(run.image_id, run.column, run.rows) for run in runs] == [
        (5, 0, 2),
        (6, 2, 2),
    ]
