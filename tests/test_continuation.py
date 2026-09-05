"""
The mark that says a line continues the one above it.

A line that a wrap started is a continuation. The mark decides what a
resize joins back together, so a mark that is wrong is a screen that is
wrong from the next resize onwards.

An erase that clears the end of a line ends the wrap out of it: nothing
wrapped away any more, so the line below is a line of its own.

libvterm's `32state_flow.test` is the only thing that asks. No judge on
the panel reports the mark, and it is visible from the outside only
through a resize. Lillecarl/pymux#58.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

COLUMNS = 8


def _screen(data, lines=4, columns=COLUMNS):
    screen = BetterScreen(lines, columns, write_process_input=lambda answer: None)
    BetterStream(screen).feed(data)
    return screen


def _continues(screen, row: int) -> bool:
    "Whether this row of the screen continues the one above it."
    return screen.line_offset + row in screen.wrapped_lines


def test_text_that_spills_over_marks_the_line_below():
    assert _continues(_screen("a" * 12), 1)


def test_a_line_feed_marks_nothing():
    screen = _screen("a" * 8 + "\r\n" + "b" * 4)
    assert not _continues(screen, 1)


def test_erasing_to_the_end_of_the_line_ends_the_wrap():
    "The text that wrapped away is gone, so nothing wrapped."
    screen = _screen("a" * 12 + "\x1b[1;5H\x1b[K")
    assert not _continues(screen, 1)


def test_erasing_the_whole_line_ends_the_wrap():
    screen = _screen("a" * 12 + "\x1b[1;5H\x1b[2K")
    assert not _continues(screen, 1)


def test_erasing_up_to_the_cursor_leaves_the_wrap():
    "Text is still there to have wrapped, so the mark stands."
    screen = _screen("a" * 12 + "\x1b[1;5H\x1b[1K")
    assert _continues(screen, 1)


def test_an_erase_on_another_line_leaves_the_wrap():
    screen = _screen("a" * 12 + "\x1b[2;3H\x1b[K")
    assert _continues(screen, 1)


def test_the_alternate_screen_gives_the_mark_back():
    """
    A visit to the other screen leaves the first one as it was.

    The marks belong to the lines of one screen, so they travel with
    the buffer. Without that, the first screen comes back with no mark
    on it, and the next resize joins two lines that nothing wrapped
    between.
    """
    screen = _screen("a" * 12 + "\x1b[?1049h\x1b[?1049l")
    assert _continues(screen, 1)


def test_the_alternate_screen_starts_with_no_mark():
    screen = _screen("a" * 12 + "\x1b[?1049h")
    assert screen.wrapped_lines == []
