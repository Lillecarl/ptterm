"""
Tests for kitty's unscroll ("CSI Ps SP D").

A shell uses it when a full-screen program ends: instead of leaving
blank space under the prompt, the lines that the program covered come
back from the scroll buffer.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

LINES = 5


def make_screen(lines=LINES, columns=20):
    screen = BetterScreen(lines, columns, write_process_input=lambda d: None)
    stream = BetterStream(screen)
    return screen, stream


def fill(stream, count):
    "Write `count` numbered lines."
    for number in range(count):
        stream.feed("line%i\r\n" % number)


def visible(screen):
    "The text of the visible rows."
    offset = screen.line_offset
    rows = []
    for y in range(offset, offset + screen.lines):
        row = screen.pt_screen.data_buffer.get(y, {})
        text = "".join(
            row[x].char if x in row else " " for x in range(screen.columns)
        )
        rows.append(text.rstrip())
    return rows


def test_the_screen_scrolls_before_anything_is_unscrolled():
    screen, stream = make_screen()
    fill(stream, 10)
    assert screen.line_offset == 6
    assert visible(screen)[0] == "line6"


def test_unscroll_brings_a_line_back():
    screen, stream = make_screen()
    fill(stream, 10)
    stream.feed("\x1b[1 D")
    assert screen.line_offset == 5
    assert visible(screen)[0] == "line5"


def test_unscroll_takes_a_count():
    screen, stream = make_screen()
    fill(stream, 10)
    stream.feed("\x1b[3 D")
    assert screen.line_offset == 3
    assert visible(screen)[0] == "line3"


def test_unscroll_without_a_count_means_one():
    screen, stream = make_screen()
    fill(stream, 10)
    stream.feed("\x1b[ D")
    assert screen.line_offset == 5


def test_the_cursor_keeps_its_place_on_the_screen():
    screen, stream = make_screen()
    fill(stream, 10)
    row_on_screen = screen.pt_cursor_position.y - screen.line_offset
    stream.feed("\x1b[2 D")
    assert screen.pt_cursor_position.y - screen.line_offset == row_on_screen


def test_the_lines_that_leave_the_bottom_are_dropped():
    screen, stream = make_screen()
    fill(stream, 10)
    stream.feed("\x1b[2 D")
    # "line9" sat on the last row before the unscroll.
    assert "line9" not in "\n".join(visible(screen))
    assert 10 not in screen.pt_screen.data_buffer


def test_unscroll_stops_at_the_top_of_the_history():
    screen, stream = make_screen()
    fill(stream, 7)
    assert screen.line_offset == 3
    stream.feed("\x1b[99 D")
    assert screen.line_offset == 0
    assert visible(screen)[0] == "line0"


def test_unscroll_does_nothing_without_history():
    screen, stream = make_screen()
    fill(stream, 2)
    assert screen.line_offset == 0
    before = visible(screen)
    stream.feed("\x1b[3 D")
    assert screen.line_offset == 0
    assert visible(screen) == before


def test_the_plain_sequence_is_still_cursor_back():
    "Without the intermediate space it is CUB, not unscroll."
    screen, stream = make_screen()
    fill(stream, 10)
    stream.feed("abcde")
    offset_before = screen.line_offset
    stream.feed("\x1b[3D")
    assert screen.line_offset == offset_before
    assert screen.pt_cursor_position.x == 2


def test_a_placement_that_falls_off_the_bottom_goes_away():
    screen, stream = make_screen(lines=5)
    fill(stream, 10)
    # Place an image on the last row of the screen.
    stream.feed("\x1b[5;1H")
    stream.feed("\x1b_Ga=T,f=24,s=1,v=1,c=1,r=1,C=1,i=1;AAAA\x1b\\")
    assert len(screen.graphics.placements) == 1

    stream.feed("\x1b[3 D")
    assert screen.graphics.placements == []


def test_a_placement_above_the_screen_stays():
    screen, stream = make_screen(lines=5)
    fill(stream, 10)
    stream.feed("\x1b[1;1H")
    stream.feed("\x1b_Ga=T,f=24,s=1,v=1,c=1,r=1,C=1,i=1;AAAA\x1b\\")
    placement = screen.graphics.placements[0]
    row = placement.y

    stream.feed("\x1b[2 D")
    assert screen.graphics.placements == [placement]
    assert placement.y == row  # Rows of the buffer do not move.
