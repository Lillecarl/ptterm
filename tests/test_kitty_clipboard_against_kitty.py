"""
kitty's clipboard protocol (OSC 5522): the writes pyte assembles and
the answers it gives, against kitty's own `ClipboardRequestManager`
fed the same packets. kitty's shipped settings allow a write, so the
embedder here allows every one. Lillecarl/pymux#893.
"""

from __future__ import annotations

import base64

import pytest
from kitty_oracle import kitty_is_available
from pyte.kitty_clipboard import ClipboardRequest, ClipboardWrite, answer_to
from pyte.screen import Screen
from pyte.sequences.kitty_clipboard import Status
from pyte.streams import Stream

pytestmark = pytest.mark.skipif(not kitty_is_available(), reason="the kitty python package is not there")


def b64(data: str | bytes) -> str:
    return base64.b64encode(data.encode() if isinstance(data, str) else data).decode()


TEXT = "mime=" + b64("text/plain")
HTML = "mime=" + b64("text/html")
SOME = b64("some data")

SCRIPTS: dict[str, list[str]] = {
    "one type": ["type=write:id=a", "type=wdata:%s;%s" % (TEXT, b64("hello")), "type=wdata"],
    "padded chunks": [
        "type=write",
        "type=wdata:%s;%s" % (TEXT, b64("one")),
        "type=wdata:%s;%s" % (TEXT, b64("two")),
        "type=wdata",
    ],
    "split groups": ["type=write"]
    + ["type=wdata:%s;%s" % (TEXT, SOME[i : i + 3]) for i in range(0, len(SOME), 3)]
    + ["type=wdata"],
    "two types and an alias": [
        "type=write:id=w-1",
        "type=wdata:%s;%s" % (TEXT, b64("plain")),
        "type=walias:%s;%s" % (TEXT, b64("text/x-a UTF8_STRING")),
        "type=wdata:%s;%s" % (HTML, b64("<b>bold</b>")),
        "type=wdata",
    ],
    "a type sent twice": [
        "type=write",
        "type=wdata:%s;%s" % (TEXT, b64("first")),
        "type=wdata:%s;%s" % (HTML, b64("<i>")),
        "type=wdata:%s;%s" % (TEXT, b64("second")),
        "type=wdata",
    ],
    "an empty type": ["type=write", "type=wdata:%s" % TEXT, "type=wdata"],
    "a character outside base64": ["type=write:id=x", "type=wdata:%s;SGVs!!!bG8=" % TEXT, "type=wdata"],
    "no padding": ["type=write:id=x", "type=wdata:%s;SGVsbG8" % TEXT, "type=wdata"],
    "no padding before another type": [
        "type=write",
        "type=wdata:%s;SGVsbG8" % TEXT,
        "type=wdata:%s;%s" % (HTML, b64("x")),
        "type=wdata",
    ],
    "data after padding": ["type=write", "type=wdata:%s;aGk=aGk=" % TEXT, "type=wdata"],
    "an alias with no type": [
        "type=write:id=w1",
        "type=wdata:%s;%s" % (TEXT, b64("x")),
        "type=walias;%s" % b64("text/rtf"),
    ],
    "an alias that is not base64": ["type=write:id=w1", "type=walias:%s;AAA" % TEXT, "type=wdata"],
    "a mime that is not base64": ["type=write:id=w1", "type=wdata:mime=AAA;%s" % b64("x"), "type=wdata"],
    "after an abort": ["type=write", "type=wdata:%s;!!!!" % TEXT, "type=wdata:%s;%s" % (TEXT, b64("x")), "type=wdata"],
    "data with no write": ["type=wdata:%s;%s" % (TEXT, b64("x")), "type=wdata"],
    "a bad read leaves the write": [
        "type=write:id=w2",
        "type=read:id=r1;AAA",
        "type=wdata:%s;%s" % (TEXT, b64("x")),
        "type=wdata",
    ],
    "an id kitty cleans": ["type=write:id=a b/c+d.e_f-g", "type=wdata"],
    "the primary selection": ["type=write:loc=primary", "type=wdata:%s;%s" % (TEXT, b64("p")), "type=wdata"],
}


def pyte_does(packets: list[str]) -> tuple[list[dict[str, bytes]], list[bytes]]:
    replies: list[str] = []
    written: list[dict[str, bytes]] = []
    screen = Screen(5, 20, write_process_input=replies.append)

    def serve(request: ClipboardRequest) -> None:
        assert isinstance(request, ClipboardWrite)
        written.append(request.types())
        screen.reply(answer_to(request, Status.DONE))

    screen.clipboard_func = serve
    stream = Stream(screen)
    for packet in packets:
        stream.feed("\x1b]5522;%s\x1b\\" % packet)
    return written, [reply.encode() for reply in replies]


def kitty_does(packets: list[str]) -> tuple[list[dict[str, bytes]], list[bytes]]:
    from kitty.clipboard import ClipboardRequestManager, ClipboardType
    from kitty.fast_data_types import set_boss

    written: list[dict[str, bytes]] = []
    replies: list[bytes] = []

    class Clipboard:
        enabled = True

        def __init__(self, kind: ClipboardType) -> None:
            self.kind = kind

        def set_mime(self, data) -> None:
            found = {}
            for mime, creator in data.items():
                chunker = creator()
                found[mime] = b"".join(iter(chunker, b""))
            written.append(found)

    class ChildScreen:
        def send_escape_code_to_child(self, code: int, data: bytes) -> None:
            replies.append(b"\x1b]" + bytes(data) + b"\x1b\\")

    class Window:
        id = 1
        screen = ChildScreen()

    class Boss:
        clipboard = Clipboard(ClipboardType.clipboard)
        primary_selection = Clipboard(ClipboardType.primary_selection)
        window_id_map = {1: Window()}

    set_boss(Boss())
    try:
        manager = ClipboardRequestManager(1)
        for packet in packets:
            manager.parse_osc_5522(memoryview(packet.encode()))
    finally:
        set_boss(None)
    return written, replies


@pytest.mark.parametrize("name", SCRIPTS)
def test_pyte_assembles_what_kitty_assembles(name: str):
    assert pyte_does(SCRIPTS[name]) == kitty_does(SCRIPTS[name])
