"""
Copy mode with Helix's keys, which an embedder asks for with
`helix_keys`. Lillecarl/pymux#749.

The copy is read-only, so Helix's moves, selections and search work and
every key that edits is refused. tmux's keys sit over Helix's: `y` and
Enter copy and leave, `q` and Escape leave.

Each test is a coroutine because prompt_toolkit's key processor wants a
running loop.
"""

from __future__ import annotations

import time

from no_backend import NoBackend
from prompt_toolkit.application.current import set_app
from prompt_toolkit.application.dummy import DummyApplication
from prompt_toolkit.key_binding.key_processor import KeyPress, _Flush
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.layout import Layout
from ptkhx import Mode

from ptterm.copy_mode import _helix
from ptterm.terminal import Terminal

LINES = 6
COLUMNS = 20


def a_terminal(data: str, takes_key_first=None) -> tuple[Terminal, list[str]]:
    "A widget with Helix copy keys, written to, and what it handed out."
    copied: list[str] = []
    terminal = Terminal(
        backend=NoBackend(),
        copy_func=copied.append,
        helix_keys=lambda: True,
        takes_key_first=takes_key_first,
    )
    control = terminal.terminal_control
    control.create_content(COLUMNS, LINES)
    control.stream.feed(data)
    return terminal, copied


def press(terminal: Terminal, *keys) -> DummyApplication:
    "Open copy mode and press these keys."
    app = DummyApplication()
    app.layout = Layout(terminal.container)
    with set_app(app):
        terminal.enter_copy_mode()
        press_more(app, *keys)
    return app


def press_more(app: DummyApplication, *keys) -> None:
    "Each key through the key processor, and the flush its timeout sends."
    processor = app.key_processor
    with set_app(app):
        for key in keys:
            processor.feed(KeyPress(key, key if len(key) == 1 else ""))
            processor.process_keys()
            processor.feed(_Flush)
            processor.process_keys()


def open_in(terminal: Terminal, app: DummyApplication) -> bool:
    return terminal.copy_views.of(app) is not None


def spans(terminal: Terminal, app: DummyApplication) -> list[str]:
    buffer = terminal.copy_views.of(app).buffer
    return [buffer.text[start:end] for start, end in _helix().selection_spans(buffer)]


async def test_y_copies_the_selection_and_leaves():
    terminal, copied = a_terminal("hello world")
    app = press(terminal, "g", "h", "w", "y")
    assert not open_in(terminal, app)
    assert copied == ["hello "]
    assert app.clipboard.get_data().text == "hello "


async def test_enter_copies_and_leaves():
    terminal, copied = a_terminal("hello world")
    app = press(terminal, "g", "h", "e", Keys.ControlM)
    assert not open_in(terminal, app)
    assert copied == ["hello"]


async def test_every_selection_is_copied_one_to_a_line():
    terminal, copied = a_terminal("a b a")
    press(terminal, "%", "s", "a", Keys.ControlM, "y")
    assert copied == ["a\na"]


async def test_escape_in_normal_mode_leaves():
    terminal, _ = a_terminal("hello")
    app = press(terminal, Keys.Escape)
    assert not open_in(terminal, app)


async def test_escape_in_select_mode_goes_back_to_normal_mode():
    terminal, _ = a_terminal("hello")
    app = press(terminal, "v", Keys.Escape)
    assert open_in(terminal, app)
    assert _helix().mode_of(terminal.copy_views.of(app).buffer) is Mode.NORMAL


async def test_q_leaves():
    terminal, _ = a_terminal("hello")
    app = press(terminal, "q")
    assert not open_in(terminal, app)


async def test_a_key_that_waits_for_another_takes_q():
    "`fq` goes to the next `q`, and does not leave."
    terminal, _ = a_terminal("aqb")
    app = press(terminal, "g", "h", "f", "q")
    assert open_in(terminal, app)
    assert spans(terminal, app) == ["aq"]


async def test_the_copy_can_be_edited_before_it_is_copied():
    "Lillecarl/pymux#751: delete what is not wanted, then copy the rest."
    terminal, copied = a_terminal("$ hello world")
    app = press(terminal, "g", "h", "w", "d")
    assert terminal.copy_views.of(app).buffer.text == "hello world"
    press_more(app, "%", "y")
    assert copied == ["hello world"]


async def test_insert_mode_types_what_would_copy_or_leave():
    "`q`, `y` and Enter are tmux's outside insert mode, and letters in it."
    terminal, _ = a_terminal("ab")
    app = press(terminal, "g", "h", "i", "q", "y", Keys.ControlM, Keys.Escape)
    assert open_in(terminal, app)
    assert terminal.copy_views.of(app).buffer.text == "qy\nab"


async def test_a_line_no_edit_touched_keeps_its_colours():
    terminal, _ = a_terminal("plain\r\n\x1b[31mred\x1b[0m")
    app = press(terminal)
    view = terminal.copy_views.of(app)
    red = view.styled_line(1)
    press_more(app, "g", "g", "x", "d")
    assert view.buffer.text == "red"
    assert view.styled_line(0) == red


async def test_a_line_an_edit_touched_is_plain_text():
    terminal, _ = a_terminal("\x1b[31mred\x1b[0m")
    app = press(terminal, "g", "h", "i", "x", Keys.Escape)
    view = terminal.copy_views.of(app)
    assert view.styled_line(0) == [("", "xred")]


def alt_r(app: DummyApplication) -> None:
    "Alt-r, as a terminal sends it: Escape and `r` in one read."
    with set_app(app):
        app.key_processor.feed_multiple([KeyPress(Keys.Escape, "\x1b"), KeyPress("r", "r")])
        app.key_processor.process_keys()


async def test_alt_r_takes_a_new_copy():
    terminal, _ = a_terminal("ab")
    app = press(terminal)
    terminal.terminal_control.stream.feed("c")
    alt_r(app)
    assert terminal.copy_views.of(app).buffer.text == "abc"


async def test_r_is_helix_s_replace():
    terminal, _ = a_terminal("ab")
    app = press(terminal, "g", "h", "r", "x")
    assert terminal.copy_views.of(app).buffer.text == "xb"


async def test_refresh_is_refused_over_edits():
    terminal, _ = a_terminal("ab")
    app = press(terminal, "g", "h", "d")
    alt_r(app)
    view = terminal.copy_views.of(app)
    assert view.buffer.text == "b"
    assert view.refresh_refused
    with set_app(app):
        assert view._position_formatted_text().endswith("edited: u or y first")


async def test_typing_in_a_deep_copy_answers_quickly():
    """
    Each key in insert mode compares the document with the one before:
    ptkhx a block at a time, and copy mode the lines from both ends.
    """
    terminal, _ = a_terminal("".join("line %d of the history\r\n" % number for number in range(20000)))
    app = press(terminal, "g", "g", "i")
    started = time.monotonic()
    press_more(app, *"typed")
    assert terminal.copy_views.of(app).buffer.text.startswith("typedline ")
    assert time.monotonic() - started < 0.5


async def test_undoing_every_edit_is_no_edit():
    terminal, _ = a_terminal("ab")
    app = press(terminal, "g", "h", "d", "u")
    view = terminal.copy_views.of(app)
    assert view.buffer.text == "ab"
    assert not view.edited


async def test_a_padded_row_ends_at_its_last_character():
    "Claude Code pads every row to the width; `gl` and `y` stop at the text."
    terminal, copied = a_terminal("  padded" + " " * 12)
    app = press(terminal, "g", "g", "g", "l")
    assert spans(terminal, app) == []
    assert terminal.copy_views.of(app).buffer.cursor_position == len("  padded") - 1
    press_more(app, "g", "s", "v", "g", "l", "y")
    assert copied == ["padded"]


async def test_search_selects_the_match():
    terminal, _ = a_terminal("first\r\nsecond\r\nthird")
    app = press(terminal, "g", "g", "/", "s", "e", "c", Keys.ControlM)
    assert spans(terminal, app) == ["sec"]


async def test_the_corner_says_the_mode_and_what_is_half_typed():
    terminal, _ = a_terminal("hello")
    app = press(terminal, "v")
    view = terminal.copy_views.of(app)
    with set_app(app):
        assert view._position_formatted_text().startswith("SEL [1/1]")
    press_more(app, "/", "h")
    with set_app(app):
        assert view._position_formatted_text().startswith("search:h [1/1]")


async def test_the_embedder_s_key_comes_first():
    "pymux after its prefix: the next key is the embedder's, and `q` is not copy mode's."
    terminal, _ = a_terminal("hello", takes_key_first=lambda: True)
    app = press(terminal, "q")
    assert open_in(terminal, app)


async def test_without_helix_keys_copy_mode_keeps_its_own():
    "Emacs keys: `C-Space` starts prompt_toolkit's selection, which Helix has no key for."
    terminal, _ = a_terminal("hello")
    terminal.helix_keys = lambda: False
    app = press(terminal, "g", "h", Keys.ControlSpace)
    assert terminal.copy_views.of(app).buffer.selection_state is not None
