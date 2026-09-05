"""
The DEC line attributes: double width and double height lines.

"ESC # 3", "ESC # 4", "ESC # 5" and "ESC # 6" belong to the line the
cursor stands on, not to a cell. ptterm holds the attribute and draws
nothing with it: how wide a line looks is the renderer's decision, and a
pane is not a whole line of the terminal the user runs.

The line keeps every column it had. libvterm alone halves it, and the
other five judges keep it whole; `test_the_panel.py` holds that vote.
Lillecarl/pymux#55.
"""
from ptterm.screen import BetterScreen, DoubleHeight, LineAttribute
from ptterm.stream import BetterStream

LINES, COLUMNS = 5, 10

DOUBLE_WIDTH = LineAttribute(True, DoubleHeight.NONE)
TOP_HALF = LineAttribute(True, DoubleHeight.TOP)
BOTTOM_HALF = LineAttribute(True, DoubleHeight.BOTTOM)


def _screen(data, lines=LINES, columns=COLUMNS):
    screen = BetterScreen(lines, columns, write_process_input=lambda answer: None)
    BetterStream(screen).feed(data)
    return screen


def _attribute(screen, row: int):
    "The attribute of one row of the visible screen, or None."
    return screen.line_attributes.get(screen.line_offset + row)


def test_a_plain_line_carries_nothing():
    assert _attribute(_screen("abcde"), 0) is None


def test_double_width_marks_the_line():
    assert _attribute(_screen("\x1b#6abcde"), 0) == DOUBLE_WIDTH


def test_double_height_marks_both_halves():
    screen = _screen("\x1b#3abcde\r\n\x1b#4abcde")
    assert _attribute(screen, 0) == TOP_HALF
    assert _attribute(screen, 1) == BOTTOM_HALF


def test_single_width_takes_the_attribute_off():
    assert _attribute(_screen("\x1b#6abcde\x1b#5"), 0) is None


def test_the_attribute_can_come_after_the_text():
    "A program can mark a line it has already written."
    assert _attribute(_screen("abcde\x1b#6"), 0) == DOUBLE_WIDTH


def test_the_attribute_reaches_only_its_own_line():
    screen = _screen("\x1b#6abcde\r\nfghij")
    assert _attribute(screen, 0) == DOUBLE_WIDTH
    assert _attribute(screen, 1) is None


def test_a_double_width_line_still_holds_every_column():
    """
    The attribute does not narrow the line.

    libvterm gives a double width line `cols / 2` columns, so text
    wraps at half the width. Five judges keep the line whole and leave
    the width to the renderer, and ptterm is with the five.
    """
    screen = _screen("\x1b#6" + "a" * 8)
    assert screen.pt_cursor_position.y == screen.line_offset
    assert screen.reported_column == 8
    assert screen.wrapped_lines == []


def test_the_attribute_does_not_spill_over_on_a_scroll():
    """
    The text moves up and the attribute moves with it.

    libvterm's `67screen_dbl_wh.test` asks for this: the line that
    scrolls up keeps the mark, and the empty line that comes in below
    has none.
    """
    screen = _screen("\x1b[5H\x1b#6Final\r\n")
    assert _attribute(screen, 3) == DOUBLE_WIDTH
    assert _attribute(screen, 4) is None


def test_a_scrolling_region_carries_the_attribute():
    "SU inside a region moves the mark the way it moves the text."
    screen = _screen("\x1b[1;3r\x1b[2H\x1b#6bbb\x1b[S")
    assert _attribute(screen, 0) == DOUBLE_WIDTH
    assert _attribute(screen, 1) is None


def test_a_scroll_drops_the_attribute_that_leaves_the_region():
    screen = _screen("\x1b[1;3r\x1b[1H\x1b#6aaa\x1b[S")
    assert screen.line_attributes == {}


def test_inserting_a_line_pushes_the_attribute_down():
    "IL moves whole lines, so the mark goes with the text."
    screen = _screen("\x1b#6abc\x1b[1H\x1b[L")
    assert _attribute(screen, 0) is None
    assert _attribute(screen, 1) == DOUBLE_WIDTH


def test_deleting_a_line_pulls_the_attribute_up():
    screen = _screen("\r\n\x1b#6abc\x1b[1H\x1b[M")
    assert _attribute(screen, 0) == DOUBLE_WIDTH
    assert _attribute(screen, 1) is None


def test_the_alternate_screen_gives_the_attribute_back():
    "A visit to the other screen leaves the first one as it was."
    screen = _screen("\x1b#6abc\x1b[?1049h\x1b[?1049l")
    assert _attribute(screen, 0) == DOUBLE_WIDTH


def test_the_alternate_screen_starts_with_no_attribute():
    screen = _screen("\x1b#6abc\x1b[?1049h")
    assert screen.line_attributes == {}


def test_erasing_the_screen_takes_every_attribute_off():
    assert _screen("\x1b#6abcde\x1b[2J").line_attributes == {}


def test_erasing_below_leaves_the_line_of_the_cursor():
    "ED 0 takes only a part of the row the cursor is on."
    screen = _screen("\x1b#6abc\r\n\x1b#6def\x1b[1;2H\x1b[0J")
    assert _attribute(screen, 0) == DOUBLE_WIDTH
    assert _attribute(screen, 1) is None


def test_erasing_above_leaves_the_line_of_the_cursor():
    screen = _screen("\x1b#6abc\r\n\x1b#6def\x1b[2;2H\x1b[1J")
    assert _attribute(screen, 0) is None
    assert _attribute(screen, 1) == DOUBLE_WIDTH


def test_left_and_right_margins_take_every_attribute_off():
    """
    A margin cuts a line in two, and half a double width line is not a
    thing a terminal can draw. libvterm clears them on DECLRMM too.
    """
    assert _screen("\x1b#6abcde\x1b[?69h").line_attributes == {}


def test_a_resize_carries_the_attribute():
    screen = _screen("\x1b#6abcde")
    screen.resize(LINES, 20)
    assert _attribute(screen, 0) == DOUBLE_WIDTH


def test_a_resize_carries_the_attribute_onto_every_row_it_wraps_to():
    "The attribute belongs to the line, so it follows all of it."
    screen = _screen("\x1b#6" + "a" * 10)
    screen.resize(LINES, 5)
    assert _attribute(screen, 0) == DOUBLE_WIDTH
    assert _attribute(screen, 1) == DOUBLE_WIDTH


def test_a_reset_takes_every_attribute_off():
    assert _screen("\x1b#6abcde\x1bc").line_attributes == {}
