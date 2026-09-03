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
