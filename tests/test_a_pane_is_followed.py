"""
A pane tells its followers each time its picture changes, and a
mirrored pane fed the frames of that picture shows the same page.
Lillecarl/pyterm#761.

pyte proves a page converges from frames (`pyte/tests/test_grid.py`).
This proves a pane tells a follower when to take one, that a mirror
sends a person's input to its owner to encode, and that a mirror is a
pane a follower can follow, which is what a chain of servers is.
"""

from __future__ import annotations

import json

from no_backend import NoBackend
from pyte.grid import GridWriter
from pyte.keys.events import DEFAULT_KEY_PROFILE
from pyte.mouse import MouseAction, MouseInput

from ptterm.control import TerminalControl
from ptterm.terminal import Terminal

LINES = 6
COLUMNS = 30


class Copy:
    "A follower that sends frames to a mirrored pane, as a link between servers would."

    def __init__(self, original: TerminalControl, mirror: TerminalControl) -> None:
        self.original = original
        self.mirror = mirror
        self.writer = GridWriter()

    def changed(self) -> None:
        frame = self.writer.frame(self.original.screen)
        if frame is not None:
            self.mirror.put_frame(json.loads(json.dumps(frame)))


class Owner:
    "What a mirror sends a person's input to."

    def __init__(self) -> None:
        self.heard: list[tuple] = []

    def key(self, data, profile) -> None:
        self.heard.append(("key", data, profile))

    def paste(self, text) -> None:
        self.heard.append(("paste", text))

    def mouse(self, mouse) -> None:
        self.heard.append(("mouse", mouse))

    def copy_mode(self, at=None) -> None:
        self.heard.append(("copy mode",))

    copying = None


def a_mirror_of(original: TerminalControl, **kwargs) -> TerminalControl:
    mirror = TerminalControl(backend=NoBackend(), **kwargs)
    mirror.mirror = Owner()
    original.followers.append(Copy(original, mirror))
    return mirror


def picture(control: TerminalControl):
    screen = control.screen
    top = screen.line_offset
    rows = [
        "".join(screen.page.data_buffer[top + y][x].char for x in range(screen.columns)) for y in range(screen.lines)
    ]
    cursor = screen.pt_cursor_position
    return rows, (cursor.x, cursor.y - top)


def test_a_mirror_shows_the_page_through_output_and_a_resize():
    original = TerminalControl(backend=NoBackend())
    mirror = a_mirror_of(original)
    original.create_content(COLUMNS, LINES)

    original.feed_output("hello\r\n\x1b[1;31mred\x1b[0m world")
    original.set_size(20, 4)
    original.feed_output("\r\nfrom a job\r\nand\r\nmore")

    assert mirror.screen.lines == 4
    assert picture(mirror) == picture(original)


def test_a_half_drawn_frame_is_not_sent():
    "A program that draws a frame (?2026) is shown when it ends it, here and at the peer."
    original = TerminalControl(backend=NoBackend())
    mirror = a_mirror_of(original)
    original.create_content(COLUMNS, LINES)
    original.feed_output("\x1b[?2026hhalf")
    assert "half" not in picture(mirror)[0][0]
    original.feed_output(" whole\x1b[?2026l")
    assert picture(mirror) == picture(original)


def test_a_mirror_takes_its_size_from_the_owner_and_answers_nothing():
    asked = []
    original = TerminalControl(backend=NoBackend())
    mirror = a_mirror_of(original, resize_func=lambda *size: asked.append(size), may_resize=lambda: True)
    original.create_content(COLUMNS, LINES)
    original.feed_output("\x1b[c\x1b[8;3;40t")
    mirror.set_size(10, 2)
    assert mirror.process.backend.sizes == [(10, 2)], "the size goes to the program, which asks for it"
    assert (mirror.screen.lines, mirror.screen.columns) == (LINES, COLUMNS)
    assert mirror.process.backend.written == []
    assert asked == []


def test_the_owner_encodes_for_the_modes_the_program_set():
    "Cursor keys in application mode, a bracketed paste and an SGR mouse report."
    original = TerminalControl(backend=NoBackend())
    original.create_content(COLUMNS, LINES)
    original.feed_output("\x1b[?1h\x1b[?2004h\x1b[?1000;1006h")
    original.type_key("\x1b[A", DEFAULT_KEY_PROFILE)
    original.paste("pasted")
    assert original.use_mouse(MouseInput(MouseAction.PRESS, 3, 1))
    assert original.process.backend.written == ["\x1bOA", "\x1b[200~pasted\x1b[201~", "\x1b[<0;4;2M"]


def test_a_mirror_is_followed_too():
    "Three servers in a row: the middle one's pane is a mirror and has a follower."
    original = TerminalControl(backend=NoBackend())
    middle = a_mirror_of(original)
    last = a_mirror_of(middle)
    original.create_content(COLUMNS, LINES)

    original.feed_output("one\r\ntwo\x1b[2;")
    original.feed_output("1Hthree")
    original.set_size(25, 5)
    original.feed_output("\r\nfour")

    assert picture(last) == picture(original)


def test_a_mirror_sends_input_on_as_it_came():
    "The middle of a chain: its screen holds none of the program's modes, so it encodes nothing."
    middle = a_mirror_of(TerminalControl(backend=NoBackend()))
    middle.feed_output("\x1b[?1h")
    middle.type_key("\x1b[A", DEFAULT_KEY_PROFILE)
    middle.paste("pasted")
    assert middle.use_mouse(MouseInput(MouseAction.WHEEL_UP, 3, 1))
    assert middle.mirror.heard == [  # type: ignore[union-attr]
        ("key", "\x1b[A", DEFAULT_KEY_PROFILE),
        ("paste", "pasted"),
        ("mouse", MouseInput(MouseAction.WHEEL_UP, 3, 1)),
    ]
    assert middle.process.backend.written == []


def test_copy_mode_of_a_mirror_opens_on_the_owner():
    "The owner holds the history, so a mirror opens no copy of its own."
    terminal = Terminal(backend=NoBackend())
    owner = terminal.terminal_control.mirror = Owner()
    assert terminal.enter_copy_mode() is None
    assert owner.heard == [("copy mode",)]
    assert not terminal.is_copying
