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
