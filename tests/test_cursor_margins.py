"""
The margins hold the cursor only while it is inside the region.

A cursor above the top margin moves up to the top of the screen, and
one below the bottom margin moves down to the bottom of it. Anything
else turns a move up into a move down, which is what pyte did.
"""
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def _screen(lines=5, columns=8):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    return screen, stream


def _row(screen):
    return screen.pt_cursor_position.y - screen.line_offset


def test_a_move_up_above_the_region_reaches_the_top():
    screen, stream = _screen()
    # "CSI r" homes the cursor, which is above a top margin of two.
    stream.feed("\x1b[2;3r\x1b[A")
    assert _row(screen) == 0


def test_a_reverse_index_above_the_region_stays():
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1bM")
    assert _row(screen) == 0


def test_a_move_down_below_the_region_reaches_the_bottom():
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1b[5;1H\x1b[B")
    assert _row(screen) == 4


def test_an_index_below_the_region_stays():
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1b[5;1H\x1bD")
    assert _row(screen) == 4


def test_a_move_up_inside_the_region_stops_at_the_top_margin():
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1b[3;1H\x1b[9A")
    assert _row(screen) == 1


def test_a_move_down_inside_the_region_stops_at_the_bottom_margin():
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1b[3;1H\x1b[9B")
    assert _row(screen) == 2


def test_a_move_down_without_margins_stops_at_the_bottom():
    screen, stream = _screen()
    stream.feed("\x1b[9B")
    assert _row(screen) == 4


def test_a_move_down_above_the_region_reaches_the_bottom():
    # "CSI r" homes the cursor, which leaves it above a top margin of
    # two. The bottom margin belongs to the region, not to a cursor
    # that sits outside it, so the screen stops the move.
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1b[9B")
    assert _row(screen) == 4


def test_a_move_up_below_the_region_reaches_the_top():
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1b[5;1H\x1b[9A")
    assert _row(screen) == 0


def test_a_move_down_above_the_region_counts_the_lines():
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1b[3B")
    assert _row(screen) == 3


# ----------------------------------------------------------------------
# Origin mode. The region is the whole page a program sees, so a row
# past the bottom of it holds at the bottom.


def test_a_row_past_the_region_holds_at_the_bottom():
    screen, stream = _screen()
    stream.feed("\x1b[1;2r\x1b[?6h\x1b[3;1H")
    assert _row(screen) == 1


def test_it_holds_at_the_bottom_of_a_region_that_starts_lower():
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1b[?6h\x1b[5;1H")
    assert _row(screen) == 2


def test_a_row_far_past_the_region_holds_there_as_well():
    screen, stream = _screen()
    stream.feed("\x1b[2;3r\x1b[?6h\x1b[99;1H")
    assert _row(screen) == 2


def test_the_column_moves_even_when_the_row_is_past_the_region():
    "The move happens. pyte left the cursor where it stood."
    screen, stream = _screen()
    stream.feed("\x1b[1;2r\x1b[?6h\x1b[3;4H")
    assert (_row(screen), screen.pt_cursor_position.x) == (1, 3)


def test_a_row_inside_the_region_lands_where_it_was_asked():
    screen, stream = _screen()
    stream.feed("\x1b[1;2r\x1b[?6h\x1b[2;1H")
    assert _row(screen) == 1


def test_the_region_does_not_hold_the_row_without_origin_mode():
    screen, stream = _screen()
    stream.feed("\x1b[1;2r\x1b[3;1H")
    assert _row(screen) == 2


# ----------------------------------------------------------------------
# HPB and VPB, the two of the position family that move backward. They
# move the way CUB and CUU move, so they are bounded the same way.
# Lillecarl/pymux#52.


def test_hpb_moves_the_cursor_to_the_left():
    screen, stream = _screen()
    stream.feed("\x1b[1;7H\x1b[3j")
    assert screen.pt_cursor_position.x == 3


def test_hpb_with_no_parameter_moves_one_column():
    screen, stream = _screen()
    stream.feed("\x1b[1;7H\x1b[j")
    assert screen.pt_cursor_position.x == 5


def test_hpb_stops_at_the_first_column():
    screen, stream = _screen()
    stream.feed("\x1b[1;3H\x1b[9j")
    assert screen.pt_cursor_position.x == 0


def test_hpb_stops_at_the_left_margin():
    screen, stream = _screen()
    stream.feed("\x1b[?69h\x1b[3;6s\x1b[1;5H\x1b[9j")
    assert screen.pt_cursor_position.x == 2


def test_vpb_moves_the_cursor_up():
    screen, stream = _screen()
    stream.feed("\x1b[4;1H\x1b[2k")
    assert _row(screen) == 1


def test_vpb_with_no_parameter_moves_one_row():
    screen, stream = _screen()
    stream.feed("\x1b[4;1H\x1b[k")
    assert _row(screen) == 2


def test_vpb_stops_at_the_first_row():
    screen, stream = _screen()
    stream.feed("\x1b[3;1H\x1b[9k")
    assert _row(screen) == 0


def test_vpb_stops_at_the_top_margin():
    screen, stream = _screen()
    stream.feed("\x1b[2;4r\x1b[4;1H\x1b[9k")
    assert _row(screen) == 1


def test_hpb_ends_the_wait_to_wrap():
    """
    A character in the last column leaves the cursor waiting to wrap.
    Every move of the cursor ends that wait, and libvterm clears its own
    `at_phantom` on HPB for the same reason.
    """
    screen, stream = _screen()
    stream.feed("abcdefgh\x1b[0jX")
    assert screen.pt_cursor_position.y - screen.line_offset == 0
