"""
Every mouse report in cells, against kitty's own encoder.

kitty exposes `encode_mouse_event_impl` as `test_encode_mouse`, so a
report here is compared byte for byte with what kitty writes for the
same button, action, modifiers and protocol. Pixels are not: that entry
takes cells only. Lillecarl/pymux#900.
"""

from __future__ import annotations

import itertools

import pytest
from kitty_oracle import kitty_is_available
from pyte.modes import PrivateMode
from pyte.mouse import MouseAction, MouseBits, MouseButton, MouseInput, mouse_report
from pyte.screen import Screen
from pyte.sequences.csi import set_mode
from pyte.streams import Stream

pytestmark = pytest.mark.skipif(not kitty_is_available(), reason="the kitty python package is not there")

#: kitty's `MouseTrackingProtocol` for each mode pyte reads.
PROTOCOLS = {
    None: 0,
    PrivateMode.SGR_MOUSE: 2,
    PrivateMode.URXVT_MOUSE: 3,
}

#: GLFW's modifier bits, by the bit a report writes for each.
GLFW_MODIFIERS = {MouseBits.SHIFT: 1, MouseBits.ALT: 2, MouseBits.CONTROL: 4}

MODIFIER_SETS = [
    MouseBits(sum(chosen))
    for size in range(4)
    for chosen in itertools.combinations((MouseBits.SHIFT, MouseBits.ALT, MouseBits.CONTROL), size)
]

PRESSED = (MouseButton.LEFT, MouseButton.MIDDLE, MouseButton.RIGHT)

INPUTS = [
    *((MouseAction.PRESS, button) for button in PRESSED),
    *((MouseAction.RELEASE, button) for button in PRESSED),
    *((MouseAction.MOVE, button) for button in (*PRESSED, MouseButton.NONE)),
    (MouseAction.WHEEL_UP, MouseButton.NONE),
    (MouseAction.WHEEL_DOWN, MouseButton.NONE),
]


def kitty_says(protocol: int, action: MouseAction, button: MouseButton, modifiers: MouseBits, x: int, y: int) -> str:
    from kitty import fast_data_types as kitty

    if action is MouseAction.WHEEL_UP:
        number, what = 4, kitty.PRESS
    elif action is MouseAction.WHEEL_DOWN:
        number, what = 5, kitty.PRESS
    elif action is MouseAction.MOVE and button is MouseButton.NONE:
        number, what = 0, kitty.MOVE
    else:
        number = int(button) + 1
        what = {MouseAction.PRESS: kitty.PRESS, MouseAction.RELEASE: kitty.RELEASE, MouseAction.MOVE: kitty.DRAG}[
            action
        ]
    glfw = sum(value for bit, value in GLFW_MODIFIERS.items() if bit in modifiers)
    return kitty.test_encode_mouse(x, y, protocol, number, what, glfw)


@pytest.mark.parametrize("mode", list(PROTOCOLS), ids=lambda mode: "x10" if mode is None else mode.name)
@pytest.mark.parametrize(("action", "button"), INPUTS, ids=lambda value: value.name)
@pytest.mark.parametrize("modifiers", MODIFIER_SETS, ids=lambda bits: str(int(bits)))
def test_a_report_is_kittys(mode, action, button, modifiers):
    screen = Screen(24, 80, write_process_input=lambda data: None)
    stream = Stream(screen)
    stream.feed(set_mode(PrivateMode.ANY_EVENT_MOUSE))
    if mode is not None:
        stream.feed(set_mode(mode))
    report = mouse_report(screen, MouseInput(action, 6, 2, button, modifiers))
    assert report is not None
    if mode is PrivateMode.URXVT_MOUSE and action is MouseAction.RELEASE:
        # kitty writes the button: its check is "protocol < SGR_PROTOCOL",
        # and its enum puts urxvt after SGR. xterm writes 3 for every
        # release but SGR's (`button.c`, ButtonRelease), and so does urxvt.
        assert report.body() == "%d;7;3M" % (32 + 3 + int(modifiers))
        return
    assert report.body() == kitty_says(PROTOCOLS[mode], action, button, modifiers, 7, 3)


#: The modes that both kitty and pyte answer DECRQM for. kitty answers 0
#: for 1015, which it acts on. Lillecarl/pymux#901.
ASKED = (1000, 1002, 1003, 1006, 1016)

MODE_SEQUENCES = [
    "?1000h ?1003h",
    "?1000h ?1003h ?1003l",
    "?1000h ?1003h ?1000l",
    "?1002h ?1000;1003h",
    "?1000;1003h ?1003l",
    "?1006h ?1016h",
    "?1006h ?1016h ?1016l",
    "?1006h ?1016h ?1006l",
    "?1006h ?1015h",
    "?1003h ?1006h",
    "?1003h ?1006h ?1000l ?1016h",
]


def written(sequence: str) -> str:
    return "".join("\x1b[%s" % part for part in sequence.split())


def asked() -> str:
    return "".join("\x1b[?%d$p" % mode for mode in ASKED)


def kitty_answers(data: str) -> str:
    from kitty.fast_data_types import Screen as KittyScreen

    class Child:
        said = b""

        def write(self, data: bytes) -> None:
            self.said += bytes(data)

        def __getattr__(self, name: str):
            return lambda *args, **kwargs: None

    child = Child()
    screen = KittyScreen(child, 24, 80, 0, 10, 20, 0, child)
    for part in (data, asked()):
        screen.test_commit_write_buffer(part.encode(), screen.test_create_write_buffer())
        screen.test_parse_written_data()
        if part is data:
            child.said = b""
    return child.said.decode()


@pytest.mark.parametrize("sequence", MODE_SEQUENCES)
def test_a_mode_query_answers_what_kitty_answers(sequence):
    "One value per group: a set takes the place of the rest, a reset turns them all off."
    replies: list[str] = []
    stream = Stream(Screen(24, 80, write_process_input=replies.append))
    stream.feed(written(sequence))
    replies.clear()
    stream.feed(asked())
    assert "".join(replies) == kitty_answers(written(sequence))
