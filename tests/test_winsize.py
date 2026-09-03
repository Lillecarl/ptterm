"""
Tests for the size that a pane pty reports.

A program that draws images asks the pty how big the terminal is in
pixels. A zero there says "I do not know", and leaves the program with
no size to draw with.
"""
import array
import fcntl
import os
import pty
import termios

import pytest

from ptterm.backends.posix_utils import MAX_WINSIZE_PIXELS, set_terminal_size
from ptterm.graphics import ASSUMED_CELL_HEIGHT, ASSUMED_CELL_WIDTH


@pytest.fixture
def pty_pair():
    master, slave = pty.openpty()
    yield master, slave
    os.close(master)
    os.close(slave)


def read_size(fileno):
    "The (rows, columns, width, height) that the pty reports."
    buf = array.array("h", [0, 0, 0, 0])
    fcntl.ioctl(fileno, termios.TIOCGWINSZ, buf, True)
    return tuple(buf)


def test_the_size_in_pixels_is_reported(pty_pair):
    master, slave = pty_pair
    set_terminal_size(master, 24, 80)
    assert read_size(slave) == (
        24,
        80,
        80 * ASSUMED_CELL_WIDTH,
        24 * ASSUMED_CELL_HEIGHT,
    )


def test_the_pixels_agree_with_the_window_report(pty_pair):
    """
    "CSI 14 t" reports the same size. Both sides count the same cell,
    so a program reads one answer whichever way it asks.
    """
    master, slave = pty_pair
    set_terminal_size(master, 10, 40)
    _rows, _columns, width, height = read_size(slave)
    assert (height, width) == (10 * ASSUMED_CELL_HEIGHT, 40 * ASSUMED_CELL_WIDTH)


def test_a_terminal_too_large_to_count_reports_no_pixels(pty_pair):
    "A wrong number is worse than none."
    master, slave = pty_pair
    columns = MAX_WINSIZE_PIXELS // ASSUMED_CELL_WIDTH + 1
    set_terminal_size(master, 24, columns)
    _rows, _columns, width, height = read_size(slave)
    assert width == 0
    assert height == 24 * ASSUMED_CELL_HEIGHT


def test_an_empty_terminal_reports_no_pixels(pty_pair):
    master, slave = pty_pair
    set_terminal_size(master, 0, 0)
    assert read_size(slave) == (0, 0, 0, 0)
