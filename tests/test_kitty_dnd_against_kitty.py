"""
kitty's drag and drop protocol (OSC 72): the metadata pyte reads, against
kitty's own `parse_dnd_code` fed the same packet. kitty reports the
packet it read, or an error and nothing. Lillecarl/pyterm#894.
"""

from __future__ import annotations

import pytest
from kitty_oracle import kitty_is_available
from pyte.sequences.kitty_dnd import DndPacket, Malformed

pytestmark = pytest.mark.skipif(not kitty_is_available(), reason="the kitty python package is not there")

PARAMS = [
    "t=a;text/plain text/uri-list",
    "t=A",
    "t=m:x=5:y=3:X=100:Y=60:o=3;text/plain ",
    "t=m:x=-1:y=-1",
    "t=r:x=2:y=7:Y=9",
    "t=R:x=1;ENOENT:no such file",
    "t=o:x=1;1:abcdef",
    "t=p:x=-2:y=100:X=16:Y=16:o=1024;aGk=",
    "t=e:y=0:m=1;aGk=",
    "t=q:i=42",
    "t=a:",
    ";payload with no metadata",
    "",
    "m=1",
    "m=0:i=3;more",
    "t=r:x=4294967295",
    "t=r:x=-2147483648",
    "t=r:x=2147483648",
    "t=r:x=-4294967295",
    "i=4294967295",
    # What kitty refuses.
    "t=z",
    "t=ab",
    "t=",
    "w=1",
    "t=a::x=1",
    "x",
    "x=",
    "x=1a",
    "x=-",
    "m=-1",
    "i=4294967296",
    "x=12345678901",
]


def kitty_reads(param: str) -> dict | None:
    from kitty.fast_data_types import Screen

    found: list[tuple] = []

    def dump(window_id, *args) -> None:
        if args and args[0] != "bytes":
            found.append(args)

    # kitty_tests.base.parse_bytes, which is not installed.
    screen = Screen(None, 5, 20)
    data = memoryview(b"\x1b]72;" + param.encode() + b"\x1b\\")
    while data:
        written = screen.test_commit_write_buffer(data, screen.test_create_write_buffer())
        data = data[written:]
        screen.test_parse_written_data(dump)
    commands = [args[1] for args in found if args[0] == "dnd_command"]
    if not commands:
        return None
    (read,) = commands
    payload = read.pop("")
    read["type"] = read["type"].decode().strip("\x00")
    read["payload"] = payload.decode() if isinstance(payload, bytes) else str(payload)
    return read


def pyte_reads(param: str) -> dict | None:
    try:
        packet = DndPacket.decode(param)
    except Malformed:
        return None
    return {
        "type": packet.type,
        "more": packet.more,
        "client_id": packet.client_id,
        "operation": packet.operation,
        "cell_x": packet.cell_x,
        "cell_y": packet.cell_y,
        "pixel_x": packet.pixel_x,
        "pixel_y": packet.pixel_y,
        "payload": packet.payload,
    }


@pytest.mark.parametrize("param", PARAMS)
def test_pyte_reads_what_kitty_reads(param: str):
    assert pyte_reads(param) == kitty_reads(param)
