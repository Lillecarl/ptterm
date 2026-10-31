"""
A pane tells its followers everything that changes its screen, and a
mirrored pane fed only that keeps the same screen. Lillecarl/pymux#759.

pyte proves a copy converges from reads, sizes and surroundings
(`pyte/tests/test_mirroring.py`). This proves a pane hands a follower
all three, in order, and that a mirror is a pane a follower can follow,
which is what a chain of servers is.
"""

from __future__ import annotations

import json

from no_backend import NoBackend
from pyte.freeze import Freezer, Frozen, freeze, freeze_value, thaw_value

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


def drawn(control: TerminalControl) -> list[str]:
    "What the control draws for each row, through its own cache of rows."
    content = control.create_content(control.screen.columns, control.screen.lines)
    return ["".join(text for _style, text, *_ in content.get_line(y)) for y in range(content.line_count)]


def test_a_paused_mirror_catches_up_and_draws_what_changed():
    original = TerminalControl(backend=NoBackend())
    original.create_content(COLUMNS, LINES)
    original.process.receive("before\r\n")

    freezer = Freezer()
    mirror = TerminalControl(backend=NoBackend())
    mirror.mirrored = True
    mirror.catch_up(*_wire(freezer.freeze(original.screen), freeze(original.stream), original.screen.surroundings))
    copy = Copy(mirror)
    original.followers.append(copy)
    original.process.receive("live\r\n")
    assert drawn(mirror) == drawn(original)

    # Nobody watches: the follower goes, and the freezer counts from here.
    original.followers.remove(copy)
    freezer.caught_up(original.screen)
    original.process.receive("\x1b[2J\x1b[Hwhile away\x1b[3;1Hthird")
    original.screen.set_cell_size(7, 15)

    mirror.catch_up(*_wire(freezer.freeze(original.screen), freeze(original.stream), original.screen.surroundings))
    original.followers.append(copy)
    original.process.receive(" and back")
    assert drawn(mirror) == drawn(original)
    assert picture(mirror) == picture(original)


def _wire(screen, stream, surroundings):
    "The three as the far side reads them, after JSON."
    return (
        Frozen(*json.loads(json.dumps(screen))),
        Frozen(*json.loads(json.dumps(stream))),
        thaw_value(json.loads(json.dumps(freeze_value(surroundings)))),
    )


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
