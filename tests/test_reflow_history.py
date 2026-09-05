"""
Widening a screen pulls history back onto it.

A wide screen needs fewer rows for the same text. The rows that come
free are filled from the history above, and the cursor stays on the row
it was on. That is what a user sees when they widen a window: the prompt
does not move, and more of what scrolled away comes back.

libvterm is the only oracle here. No judge on the panel can be resized,
so a reflow has no vote to read (Lillecarl/pymux#64).

libvterm agrees, but only when it has a history. Its `69screen_reflow`
test asks for `WANTSCREEN r`, which turns reflow on and leaves the
scrollback off, so `sb_popline` in `t/harness.c` returns 0 and
`src/screen.c` falls back to moving the text to the top. Give the same
harness `WANTSCREEN rb` and the same bytes, and it pops a line, fills
the top row and puts the cursor at `4,2`, which is what these tests
assert. Lillecarl/pymux#57.
"""
from ptterm.screen import BetterScreen, TerminalChar
from ptterm.stream import BetterStream

# The prompt of libvterm's "Shell wrapped prompt behaviour" case. On ten
# columns it takes seven rows, so two of them scroll off a five row
# screen. On sixteen columns it takes five.
PROMPT = "PROMPT GOES HERE\r\n> \r\n\r\nPROMPT GOES HERE\r\n> "


def _screen(rows=5, columns=10):
    screen = BetterScreen(rows, columns, write_process_input=lambda answer: None)
    BetterStream(screen).feed(PROMPT)
    return screen


def _row(screen, row: int) -> str:
    """
    What a program wrote on one row of the visible screen.

    The row can hold more than that: the cell the cursor stands on is in
    it too, and `_reflow` keeps that cell on purpose. So the read stops
    at the last cell a program wrote, which is the same `TerminalChar`
    test `_reflow` uses.

    The blank inside a row is content. The space after "> " is one, and
    a reflow that drops it is Lillecarl/pymux#56 again.
    """
    line = screen.pt_screen.data_buffer[screen.line_offset + row]
    text = [line[x] for x in range(0, max(line) + 1)]
    while text and not isinstance(text[-1], TerminalChar):
        text.pop()
    return "".join(cell.char for cell in text)


def _cursor(screen):
    "Where the cursor is on the visible screen, as row and column."
    return (
        screen.pt_cursor_position.y - screen.line_offset,
        screen.reported_column,
    )


def test_the_narrow_screen_wraps_the_prompt():
    screen = _screen()
    assert _row(screen, 2) == "PROMPT GOE"
    assert _row(screen, 3) == "S HERE"
    assert _cursor(screen) == (4, 2)


def test_widening_unwraps_the_prompt():
    screen = _screen()
    screen.resize(5, 16)
    assert _row(screen, 3) == "PROMPT GOES HERE"


def test_widening_pulls_the_history_back():
    "The row that comes free holds the line that had scrolled away."
    screen = _screen()
    screen.resize(5, 16)
    assert _row(screen, 0) == "PROMPT GOES HERE"


def test_widening_leaves_the_cursor_on_the_bottom_row():
    screen = _screen()
    screen.resize(5, 16)
    assert _cursor(screen) == (4, 2)


def test_the_history_is_wrapped_at_the_new_width():
    """
    ptterm wraps a line it pulls back, and libvterm does not.

    libvterm copies a popped line cell for cell, so an embedder with a
    history sees "S HERE" here. ptterm unwraps the history and wraps it
    again, which is what kitty and WezTerm do.
    """
    screen = _screen()
    screen.resize(5, 16)
    assert _row(screen, 0) != "S HERE"


def test_narrowing_keeps_the_cursor_on_the_bottom_row():
    "The other direction pushes rows away, and the prompt still stays."
    screen = _screen()
    screen.resize(5, 8)
    assert _row(screen, 4) == "> "
    assert _cursor(screen) == (4, 2)
