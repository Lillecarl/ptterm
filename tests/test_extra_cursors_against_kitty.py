"""
kitty's multiple cursors: the extra cursors and colours pyte holds,
against what kitty's own screen holds after the same bytes. Both are
read through the queries, "CSI > 100 SP q" and "CSI > 101 SP q".
kitty lists cursors in the order of a hash table, so the cursors
compare as sets. Lillecarl/pymux#891.

A resize is left out: kitty keeps a cursor as an index into the cells,
so a new width moves it to another cell, and pyte keeps the cell.
"""

from __future__ import annotations

import pytest
from kitty_oracle import kitty_is_available
from pyte.screen import Screen
from pyte.sequences.reports import ExtraCursorColorsReport, ExtraCursorsReport
from pyte.streams import Stream

pytestmark = pytest.mark.skipif(not kitty_is_available(), reason="the kitty python package is not there")

LINES, COLUMNS = 6, 10


def mc(payload: str) -> str:
    return "\x1b[>%s q" % payload


SCRIPTS = {
    "points of every shape": mc("1;2:1:1") + mc("2;2:2:3;2:6:10") + mc("3;2:4:4") + mc("29;2:5:5"),
    "points off the screen": mc("1;2:7:1;2:1:11;2:0:3;2:3:0"),
    "an odd coordinate": mc("1;2:2:2:3"),
    "the main cursor": "\x1b[4;7H" + mc("2;0") + "\x1b[1;1H" + mc("3;0"),
    "a cursor waiting to wrap": "x" * COLUMNS + mc("1;0"),
    "rectangles cut to the screen": mc("1;4:5:8:20:30") + mc("2;4:1:1:2:2;4:3:3:3:4"),
    "a rectangle from zero": mc("1;4:0:1:2:2") + mc("1;4:1:0:2:2") + mc("3;4:2:2:0:0"),
    "the whole screen": mc("29;4"),
    "too few for a rectangle": mc("1;2:1:1") + mc("2;4:1:1:2"),
    "clear by points": mc("1;4:1:1:3:3") + mc("0;2:2:2;2:9:9"),
    "clear by rectangle": mc("1;4:1:1:3:3") + mc("0;4:2:2:3:3"),
    "clear all": mc("1;4:1:1:3:3") + mc("0;4"),
    "a shape over another": mc("1;2:1:1") + mc("3;2:1:1"),
    "ed 0 and 1 keep them": mc("1;2:2:2") + "\x1b[3;3H\x1b[J\x1b[1J",
    "ed 2": mc("1;2:2:2") + "\x1b[2J",
    "ed 3": mc("1;2:2:2") + "\x1b[3J",
    "ed 22": mc("1;2:2:2") + "\x1b[22J",
    "the alternate screen": mc("1;2:2:2") + "\x1b[?1049h" + mc("2;2:3:3") + "\x1b[?1049l" + mc("3;2:4:4"),
    "ris": mc("1;2:2:2") + mc("40;5:3") + "\x1bc",
    "decstr": mc("1;2:2:2") + mc("30;2:1:2:3") + "\x1b[!p",
    "a scroll": mc("1;2:6:1") + "\x1b[6;1H\n\n\x1bD\x1b[1;1H\x1bM",
    "colours": mc("40;2:300:2:3") + mc("30;5:260"),
    "special colours": mc("40;1") + mc("30;1"),
    "a colour that names nothing": mc("40;5:3") + mc("40;2:1:2") + mc("40;9:1"),
    "a colour unset": mc("30;5:3") + mc("30;0"),
    "an unknown shape": mc("7;2:1:1") + mc("1;2:2:2"),
    "a query among commands": mc("1;2:1:1") + mc("100") + mc("2;2:1:2"),
}


class _Callbacks:
    def __init__(self) -> None:
        self.written = b""

    def write(self, data) -> None:
        self.written += bytes(data)

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def kitty_written(*parts: str) -> str:
    "What kitty writes to the program for the last of `parts`."
    from kitty.fast_data_types import Screen as KittyScreen

    callbacks = _Callbacks()
    screen = KittyScreen(callbacks, LINES, COLUMNS, 5, 10, 20, 0, callbacks)
    for part in parts:
        callbacks.written = b""
        raw = memoryview(part.encode("utf-8"))
        while raw:
            buffer = screen.test_create_write_buffer()
            raw = raw[screen.test_commit_write_buffer(raw, buffer) :]
            screen.test_parse_written_data()
    return callbacks.written.decode()


def kitty_answers(data: str) -> tuple[str, str]:
    return kitty_written(data, mc("100")), kitty_written(data, mc("101"))


def pyte_answers(data: str) -> tuple[str, str]:
    replies: list[str] = []
    screen = Screen(LINES, COLUMNS, write_process_input=replies.append)
    stream = Stream(screen)
    stream.feed(data)
    replies.clear()
    stream.feed(mc("100"))
    stream.feed(mc("101"))
    return replies[0], replies[1]


@pytest.mark.parametrize("name", SCRIPTS)
def test_pyte_holds_what_kitty_holds(name):
    data = SCRIPTS[name]
    kitty_cursors, kitty_colors = kitty_answers(data)
    pyte_cursors, pyte_colors = pyte_answers(data)
    theirs = ExtraCursorsReport.parse(kitty_cursors)
    ours = ExtraCursorsReport.parse(pyte_cursors)
    assert theirs is not None, kitty_cursors
    assert ours is not None, pyte_cursors
    assert set(ours.cursors) == set(theirs.cursors)
    assert ExtraCursorColorsReport.parse(pyte_colors) == ExtraCursorColorsReport.parse(kitty_colors)
    assert pyte_colors == kitty_colors


def test_both_say_what_they_read():
    replies: list[str] = []
    Stream(Screen(LINES, COLUMNS, write_process_input=replies.append)).feed(mc(""))
    assert replies == [kitty_written(mc(""))]
