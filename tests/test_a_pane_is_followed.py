"""
A pane tells its followers everything that changes its screen, and a
mirrored pane fed only that keeps the same screen. Lillecarl/pymux#759.

pyte proves a copy converges from reads, sizes and surroundings
(`pyte/tests/test_mirroring.py`). This proves a pane hands a follower
all three, in order, and that a mirror is a pane a follower can follow,
which is what a chain of servers is.
"""

from __future__ import annotations

from no_backend import NoBackend

from ptterm.control import TerminalControl

LINES = 6
COLUMNS = 30


class Copy:
    "A follower that feeds a mirrored pane, as a link between servers would."

    def __init__(self, mirror: TerminalControl) -> None:
        self.mirror = mirror

    def read(self, data, expired) -> None:
        self.mirror.feed_read(data, expired)

    def resized(self, lines, columns) -> None:
        self.mirror.resize_screen(lines, columns)

    def surrounded(self, surroundings) -> None:
        self.mirror.screen.surround(surroundings)


def a_mirror_of(original: TerminalControl) -> TerminalControl:
    mirror = TerminalControl(backend=NoBackend())
    mirror.mirrored = True
    original.followers.append(Copy(mirror))
    return mirror


def picture(control: TerminalControl):
    screen = control.screen
    rows = ["".join(screen.page.data_buffer[y][x].char for x in range(screen.columns)) for y in range(screen.lines)]
    cursor = screen.pt_cursor_position
    return rows, (cursor.x, cursor.y), screen.surroundings


def test_a_mirror_takes_the_reads_the_sizes_and_the_surroundings():
    original = TerminalControl(backend=NoBackend())
    mirror = a_mirror_of(original)
    original.create_content(COLUMNS, LINES)

    original.process.receive("hello\r\n\x1b[1;")
    original._ground_timer.since -= 5  # The open sequence timed out.
    original.process.receive("31mred\x1b[0m world")
    original.set_size(20, 4)
    original.screen.set_cell_size(7, 15)
    original.feed_output("\r\nfrom a job")

    assert mirror.screen.lines == 4
    assert picture(mirror) == picture(original)


def test_a_mirror_drops_its_replies_and_its_own_size():
    original = TerminalControl(backend=NoBackend())
    mirror = a_mirror_of(original)
    original.create_content(COLUMNS, LINES)

    original.process.receive("\x1b[c")  # Primary device attributes.
    assert original.process.backend.written
    assert mirror.process.backend.written == []

    mirror.set_size(10, 2)
    assert mirror.process.backend.sizes == [(10, 2)], "the size goes to the program, which asks for it"
    assert (mirror.screen.lines, mirror.screen.columns) == (LINES, COLUMNS)


def test_a_mirror_is_followed_too():
    "Three servers in a row: the middle one's pane is a mirror and has a follower."
    original = TerminalControl(backend=NoBackend())
    middle = a_mirror_of(original)
    last = a_mirror_of(middle)
    original.create_content(COLUMNS, LINES)

    original.process.receive("one\r\ntwo\x1b[2;")
    original._ground_timer.since -= 5
    original.process.receive("three")
    original.set_size(25, 5)
    original.screen.set_keyboard_source(31, False, True)

    assert picture(last) == picture(original)
