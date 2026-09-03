"""
Saving and restoring the cursor.

A restore brings back the place that was saved. That place may sit
outside the margins that are set now, because "CSI r" homes the cursor
and a save from before it is usually above the top margin.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def _screen(lines=4, columns=8):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream


def _cursor(screen):
    return (screen.pt_cursor_position.y - screen.line_offset,
            screen.pt_cursor_position.x)


def test_a_restore_reaches_above_the_top_margin():
    screen, stream = _screen()
    # Save at the home position, then set margins that start below it.
    stream.feed("\x1b7\x1b[2;3r\x1b8")
    assert _cursor(screen) == (0, 0)


def test_a_restore_brings_back_the_column_as_well():
    screen, stream = _screen()
    stream.feed("\x1b[3;5H\x1b7\x1b[1;1H\x1b8")
    assert _cursor(screen) == (2, 4)


def test_a_restore_stays_on_the_screen():
    screen, stream = _screen()
    stream.feed("\x1b[4;8H\x1b7\x1b[1;1H\x1b8")
    assert _cursor(screen) == (3, 7)


def test_a_restore_without_a_save_goes_home():
    screen, stream = _screen()
    stream.feed("\x1b[3;5H\x1b8")
    assert _cursor(screen) == (0, 0)


def test_a_second_restore_gives_the_same_answer():
    "A terminal remembers one cursor, not a stack of them."
    screen, stream = _screen()
    stream.feed("\x1b[3;5H\x1b7\x1b[1;1H\x1b8")
    assert _cursor(screen) == (2, 4)
    stream.feed("\x1b[1;1H\x1b8")
    assert _cursor(screen) == (2, 4)


def test_a_second_save_replaces_the_first():
    screen, stream = _screen()
    stream.feed("\x1b[2;2H\x1b7\x1b[4;4H\x1b7\x1b[1;1H\x1b8")
    assert _cursor(screen) == (3, 3)
    stream.feed("\x1b[1;1H\x1b8")
    assert _cursor(screen) == (3, 3)


def test_a_restore_after_a_scroll_stays_on_the_screen():
    "A save remembers a place on the screen, not one in the history."
    screen, stream = _screen()
    stream.feed("\x1b[1;1HA\x1b7\x1b[4d\n\n\x1b8B")
    rows = [
        "".join(
            screen.pt_screen.data_buffer[y][x].char for x in range(screen.columns)
        ).rstrip()
        for y in range(screen.line_offset, screen.line_offset + screen.lines)
    ]
    # The "A" scrolled away, and the "B" landed where the save was.
    assert rows[0] == " B"


def test_a_restore_with_nothing_saved_brings_back_the_first_charset():
    # A terminal starts with the ASCII set. A restore that has nothing
    # to read brings back the state of the start, so "ESC ( 0" before
    # it is undone.
    screen, stream = _screen()
    stream.feed("\x1b(0\x1b8q")
    assert screen.pt_screen.data_buffer[0][0].char == "q"


def test_a_restore_brings_back_the_charset_that_was_saved():
    screen, stream = _screen()
    stream.feed("\x1b(0\x1b7\x1b(B\x1b8q")
    assert screen.pt_screen.data_buffer[0][0].char == "─"
