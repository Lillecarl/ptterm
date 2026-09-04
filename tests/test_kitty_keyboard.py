"""Tests for the kitty keyboard protocol flag stack in BetterScreen."""
import pyte

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def make_screen():
    "Return (screen, stream, responses)."
    responses = []
    screen = BetterScreen(24, 80, write_process_input=responses.append)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream, responses


def test_query_reports_zero_initially():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[?u")
    assert responses == ["\x1b[?0u"]
    assert screen.kitty_keyboard_flags == 0


def test_push_and_pop():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[>1u")
    assert screen.kitty_keyboard_flags == 1
    stream.feed("\x1b[>9u")
    assert screen.kitty_keyboard_flags == 9

    stream.feed("\x1b[<u")
    assert screen.kitty_keyboard_flags == 1
    stream.feed("\x1b[<u")
    assert screen.kitty_keyboard_flags == 0

    # Popping from an empty stack is a no-op.
    stream.feed("\x1b[<u")
    assert screen.kitty_keyboard_flags == 0


def test_push_without_flags_defaults_to_zero():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[>u")
    assert screen.kitty_keyboard_flags == 0
    assert responses == []


def test_pop_multiple_entries():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[>1u\x1b[>2u\x1b[>4u")
    assert screen.kitty_keyboard_flags == 4

    # Pop two entries.
    stream.feed("\x1b[<2u")
    assert screen.kitty_keyboard_flags == 1

    # Popping more entries than the stack holds empties it.
    stream.feed("\x1b[<5u")
    assert screen.kitty_keyboard_flags == 0


def test_pop_count_defaults_to_one():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[>1u\x1b[>2u\x1b[<u")
    assert screen.kitty_keyboard_flags == 1


def test_set_mode_1_sets_exactly():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[=3;1u")
    assert screen.kitty_keyboard_flags == 3
    stream.feed("\x1b[=1;1u")
    assert screen.kitty_keyboard_flags == 1


def test_set_defaults_to_mode_1():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[=5u")
    assert screen.kitty_keyboard_flags == 5


def test_set_mode_2_sets_bits():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[=3;1u")
    stream.feed("\x1b[=12;2u")
    assert screen.kitty_keyboard_flags == 3 | 12


def test_set_mode_3_resets_bits():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[=15;1u")
    stream.feed("\x1b[=4;3u")
    assert screen.kitty_keyboard_flags == 15 & ~4


def test_set_replaces_top_of_stack():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[>1u")
    stream.feed("\x1b[>2u")
    stream.feed("\x1b[=4;1u")
    assert screen.kitty_keyboard_flags == 4
    stream.feed("\x1b[<u")
    # The entry below the replaced top is untouched.
    assert screen.kitty_keyboard_flags == 1


def test_query_reports_current_flags():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[>5u")
    stream.feed("\x1b[?u")
    assert responses == ["\x1b[?5u"]


def test_query_claims_every_flag_of_a_legacy_keyboard_as_well():
    """
    A pane asks the terminal what it does, and the answer has to hold.
    It holds for a legacy keyboard too: the release that such a
    keyboard never sends is made up, and the shifted key of a letter
    is known.
    """
    screen, stream, responses = make_screen()
    assert screen.keyboard_source_flags == 0
    assert screen.synthesize_key_events is True
    stream.feed("\x1b[>31u")
    stream.feed("\x1b[?u")
    assert responses == ["\x1b[?31u"]


def test_query_drops_what_the_keyboard_cannot_serve_on_its_own():
    "With nothing made up, the answer holds only what really arrives."
    screen, stream, responses = make_screen()
    screen.synthesize_key_events = False
    stream.feed("\x1b[>31u")
    stream.feed("\x1b[?u")
    # 31 without the event types (2) and the other codes (4).
    assert responses == ["\x1b[?25u"]
    assert screen.kitty_keyboard_flags == 31


def test_query_keeps_a_flag_that_the_keyboard_serves():
    screen, stream, responses = make_screen()
    screen.synthesize_key_events = False
    screen.keyboard_source_flags = 0b10
    stream.feed("\x1b[>31u")
    stream.feed("\x1b[?u")
    # The event types stay; the other codes of a key still go.
    assert responses == ["\x1b[?27u"]


def test_the_keyboard_of_the_host_survives_a_reset():
    "It says what the terminal of the user does, and a pane cannot."
    screen, stream, responses = make_screen()
    screen.keyboard_source_flags = 0b110
    screen.synthesize_key_events = False
    stream.feed("\x1bc")
    assert screen.keyboard_source_flags == 0b110
    assert screen.synthesize_key_events is False
    assert screen.kitty_keyboard_flags == 0


def test_reset_clears_stack():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[>1u")
    screen.reset()
    assert screen.kitty_keyboard_flags == 0


def test_stack_size_is_limited():
    screen, stream, responses = make_screen()
    for i in range(screen.kitty_max_flags_stack_size + 10):
        stream.feed("\x1b[>1u")
    assert len(screen.kitty_flags_stack) == screen.kitty_max_flags_stack_size


def test_plain_csi_u_is_ignored():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[97u")
    assert screen.kitty_keyboard_flags == 0
    assert responses == []


def test_apc_and_dcs_are_consumed():
    "Graphics sequences must not corrupt the screen content."
    screen, stream, responses = make_screen()

    def row_text():
        return "".join(
            screen.pt_screen.data_buffer[0][i].char for i in range(40)
        )

    stream.feed("before\x1b_Gf=32,s=10,v=10;AAAA\x1b\\after")
    assert row_text().startswith("beforeafter")
    assert "AAAA" not in row_text()

    # A DCS that is not a sixel image. (A DECRQSS request.)
    stream.feed("\x1bP$q\"p\x1b\\!")
    assert row_text().startswith("beforeafter!")
    assert "$q" not in row_text()


def test_pyte_default_stream_does_not_dispatch_u():
    # pyte's own Stream class has no "u" entry in its csi map, so the
    # sequences don't reach the handler. (BetterStream adds the mapping.)
    responses = []
    screen = BetterScreen(24, 80, write_process_input=responses.append)
    stream = pyte.ByteStream(screen)
    stream.feed(b"\x1b[>1u")
    assert screen.kitty_keyboard_flags == 0
    assert responses == []


# ----------------------------------------------------------------------
# Device and window reports.


def test_a_cursor_position_report():
    screen, stream, responses = make_screen()
    stream.feed("hello\r\n")
    stream.feed("\x1b[6n")
    assert responses == ["\x1b[2;1R"]


def test_a_private_cursor_position_report_carries_the_page():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[?6n")
    assert responses == ["\x1b[?1;1;1R"]


def test_a_status_report():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[5n")
    assert responses == ["\x1b[0n"]


def test_a_colour_scheme_report():
    # yazi asks this on startup. Before it was answered, the whole
    # emulator raised and the pane went blank.
    screen, stream, responses = make_screen()
    stream.feed("\x1b[?996n")
    assert responses == ["\x1b[?997;1n"]


def test_an_unknown_device_status_is_ignored():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[?5522n")
    stream.feed("\x1b[99n")
    stream.feed("hello")
    assert responses == []
    row = screen.pt_screen.data_buffer[0]
    assert "".join(row[i].char for i in range(5)) == "hello"


def test_the_cell_size_report():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[16t")
    # Height first, then width. It matches the cell that the graphics
    # state assumes, so both sides count cells alike.
    assert responses == ["\x1b[6;20;10t"]


def test_the_text_area_reports():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[18t")
    assert responses == ["\x1b[8;24;80t"]
    responses.clear()
    stream.feed("\x1b[14t")
    assert responses == ["\x1b[4;480;800t"]


def test_other_window_manipulation_is_ignored():
    screen, stream, responses = make_screen()
    stream.feed("\x1b[3;10;10t")  # Move the window.
    stream.feed("hello")
    assert responses == []
    row = screen.pt_screen.data_buffer[0]
    assert "".join(row[i].char for i in range(5)) == "hello"
