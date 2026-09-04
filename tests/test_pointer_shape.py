"""
The shape of the pointer (OSC 22).

A terminal keeps a stack of shapes, and the top of it is the shape now.
A pane has no pointer of its own, so the screen remembers what the
program asked for and the embedder puts it on the pointer of the user.

The stack of kitty is driveable from python, so these compare against
it directly.
"""
import os
import sys

import pytest

from ptterm.osc import (
    MAX_POINTER_SHAPES,
    POINTER_SHAPES,
    POINTER_SHAPE_ALIASES,
    pointer_shape_name,
)
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

from kitty_oracle import kitty_is_available


def _screen(lines=4, columns=8):
    answers = []
    screen = BetterScreen(lines, columns, write_process_input=answers.append)
    stream = BetterStream(screen)
    return screen, stream, answers


def feed(steps):
    "Run a list of OSC 22 payloads and give back the screen and the answers."
    screen, stream, answers = _screen()
    for payload in steps:
        stream.feed("\x1b]22;%s\x1b\\" % payload)
    return screen, answers


def kitty_shape(steps):
    "The same payloads, through the stack that kitty carries."
    sys.path.insert(0, os.environ["PTTERM_KITTY"])
    from kitty.fast_data_types import Screen

    screen = Screen(None, 4, 8, 100, 10, 20, 0, None)
    for value in steps:
        operation = "="
        if value and value[0] in "><=?":
            operation, value = value[0], value[1:]
        if operation in "=>":
            for name in value.split(","):
                if name or operation == "=":
                    try:
                        screen.change_pointer_shape(operation, name)
                    except KeyError:
                        pass
        elif operation == "<":
            screen.change_pointer_shape("<", "")
    return screen.current_pointer_shape()


# ----------------------------------------------------------------------
# The names.


def test_a_css_name_is_itself():
    assert pointer_shape_name("pointer") == "pointer"


def test_a_name_of_xterm_becomes_the_css_one():
    assert pointer_shape_name("hand2") == "pointer"
    assert pointer_shape_name("watch") == "wait"


def test_a_name_that_nobody_knows_is_none():
    assert pointer_shape_name("nonsense") is None


def test_an_empty_name_is_no_shape():
    assert pointer_shape_name("") == ""


def test_every_alias_names_a_shape():
    for name in POINTER_SHAPE_ALIASES.values():
        assert name in POINTER_SHAPES


# ----------------------------------------------------------------------
# The stack.


def test_a_bare_name_sets_the_shape():
    screen, _ = feed(["pointer"])
    assert screen.pointer_shape == "pointer"


def test_an_empty_payload_takes_the_shape_away():
    screen, _ = feed(["pointer", ""])
    assert screen.pointer_shape == ""


def test_a_push_and_a_pop():
    screen, _ = feed(["pointer", ">wait"])
    assert screen.pointer_shape == "wait"
    screen, _ = feed(["pointer", ">wait", "<"])
    assert screen.pointer_shape == "pointer"


def test_a_pop_of_an_empty_stack_does_nothing():
    screen, _ = feed(["<", "<"])
    assert screen.pointer_shape == ""


def test_a_push_of_several_names():
    screen, _ = feed([">wait,pointer"])
    assert screen.pointer_shape == "pointer"


def test_a_set_replaces_the_top_and_does_not_push():
    screen, _ = feed([">wait", "=pointer", "<"])
    assert screen.pointer_shape == ""


def test_a_name_that_nobody_knows_changes_nothing():
    screen, _ = feed(["pointer", "nonsense"])
    assert screen.pointer_shape == "pointer"


def test_a_full_stack_drops_the_oldest():
    screen, _ = feed([">pointer"] + [">wait"] * MAX_POINTER_SHAPES)
    assert len(screen.pointer_shapes) == MAX_POINTER_SHAPES
    assert screen.pointer_shapes[0] == "wait"


def test_each_screen_keeps_its_own_stack():
    screen, stream, _ = _screen()
    stream.feed("\x1b]22;pointer\x1b\\")
    stream.feed("\x1b[?1049h")
    assert screen.pointer_shape == ""
    stream.feed("\x1b]22;wait\x1b\\")
    assert screen.pointer_shape == "wait"
    stream.feed("\x1b[?1049l")
    assert screen.pointer_shape == "pointer"


#: Sequences of payloads that the comparison against kitty runs.
CASES = [
    ["pointer"],
    ["=pointer"],
    ["pointer", ""],
    [">wait"],
    [">wait", "<"],
    ["<"],
    ["pointer", ">wait", "<"],
    [">a,b,c"],
    [">wait,pointer"],
    [">wait,pointer", "<", "<"],
    ["hand2"],
    ["beam"],
    ["nonsense"],
    ["pointer", "nonsense"],
    [">wait", "=pointer", "<"],
    [">wait"] * 20 + ["<"] * 19,
]


@pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)
@pytest.mark.parametrize("steps", CASES, ids=range(len(CASES)))
def test_the_stack_of_kitty_agrees(steps):
    screen, _ = feed(steps)
    assert (screen.pointer_shape or "0") == kitty_shape(steps)


# ----------------------------------------------------------------------
# The query.


def answer(payload):
    _screen_, answers = feed(["?" + payload])
    assert len(answers) == 1
    assert answers[0].startswith("\x1b]22;")
    return answers[0][len("\x1b]22;") : -len("\x1b\\")]


def test_a_query_of_a_name_that_the_screen_takes():
    assert answer("pointer") == "1"
    assert answer("hand2") == "1"


def test_a_query_of_a_name_that_nobody_knows():
    assert answer("no-such-name") == "0"


def test_a_query_of_several_names():
    assert answer("pointer,crosshair,no-such-name,wait") == "1,1,0,1"


def test_a_query_of_the_shape_now():
    _screen_, answers = feed(["pointer", "?__current__"])
    assert answers[-1] == "\x1b]22;pointer\x1b\\"


def test_a_query_of_the_shape_now_with_none_set():
    assert answer("__current__") == "0"


def test_a_query_of_the_default_and_the_grabbed_shape():
    assert answer("__default__") == "default"
    assert answer("__grabbed__") == "default"


def test_a_query_changes_no_shape():
    screen, _ = feed(["pointer", "?wait"])
    assert screen.pointer_shape == "pointer"


# ----------------------------------------------------------------------
# What reaches the embedder.


def _forwarded(steps):
    forwarded = []
    screen = BetterScreen(
        4,
        8,
        write_process_input=lambda data: None,
        osc_func=lambda code, param: forwarded.append((code, param)),
    )
    stream = BetterStream(screen)
    for payload in steps:
        stream.feed("\x1b]22;%s\x1b\\" % payload)
    return forwarded


def test_a_change_reaches_the_embedder():
    assert _forwarded(["pointer"]) == [("22", "pointer")]


def test_a_query_does_not_reach_the_embedder():
    "The screen answers it, so the embedder has nothing to do."
    assert _forwarded(["?pointer"]) == []


def test_a_name_that_changes_nothing_does_not_reach_the_embedder():
    assert _forwarded(["nonsense"]) == []
    assert _forwarded(["<"]) == []
