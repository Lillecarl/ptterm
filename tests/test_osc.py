"""
Tests for the OSC sequences that a pane sends.

A pane has no palette of its own, but a program that asks for one needs
an answer: without it, it waits forever.
"""
from ptterm.osc import DEFAULT_COLORS, PALETTE, Color, parse_kitty_color_query
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

BLACK = "rgb:0000/0000/0000"
WHITE = "rgb:ffff/ffff/ffff"


def make_screen():
    responses = []
    screen = BetterScreen(24, 80, write_process_input=responses.append)
    stream = BetterStream(screen)
    return screen, stream, responses


# ----------------------------------------------------------------------
# The colour helpers.


def test_a_colour_is_written_with_doubled_components():
    assert Color(0x12, 0x34, 0x56).spec == "rgb:1212/3434/5656"
    assert Color(0, 0, 0).spec == BLACK
    assert Color(255, 255, 255).spec == WHITE


def test_the_palette_has_the_full_256_colours():
    assert len(PALETTE) == 256
    assert PALETTE[0] == (0, 0, 0)
    assert PALETTE[15] == (255, 255, 255)
    assert PALETTE[16] == (0, 0, 0)  # Start of the cube.
    assert PALETTE[231] == (255, 255, 255)  # End of the cube.
    assert PALETTE[232] == (8, 8, 8)  # Start of the grey ramp.
    assert PALETTE[255] == (238, 238, 238)


def test_reading_a_kitty_colour_query():
    assert parse_kitty_color_query("foreground=?;cursor=?") == [
        ("foreground", True),
        ("cursor", True),
    ]
    assert parse_kitty_color_query("foreground=green") == [
        ("foreground", False)
    ]
    assert parse_kitty_color_query("background") == [("background", False)]
    assert parse_kitty_color_query("") is None
    assert parse_kitty_color_query(";;") is None


# ----------------------------------------------------------------------
# The xterm colour queries.


def test_the_background_query():
    # yazi asks this on startup.
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]11;?\x07")
    assert responses == ["\x1b]11;%s\x1b\\" % BLACK]


def test_the_foreground_query():
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]10;?\x07")
    assert responses == ["\x1b]10;%s\x1b\\" % WHITE]


def test_the_cursor_colour_query():
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]12;?\x1b\\")
    assert responses == ["\x1b]12;%s\x1b\\" % WHITE]


def test_the_selection_colour_queries():
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]17;?\x07")
    stream.feed("\x1b]19;?\x07")
    assert responses == [
        "\x1b]17;%s\x1b\\" % DEFAULT_COLORS["selection_background"].spec,
        "\x1b]19;%s\x1b\\" % DEFAULT_COLORS["selection_foreground"].spec,
    ]


def test_setting_a_colour_answers_nothing_and_holds_it():
    # A set is not a query, so it gets no answer. The pane keeps the
    # colour, and the next query reads it back.
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]11;rgb:ff/00/00\x07")
    assert responses == []
    stream.feed("\x1b]11;?\x07")
    assert responses == ["\x1b]11;rgb:ffff/0000/0000\x1b\\"]


# ----------------------------------------------------------------------
# The palette query.


def test_a_palette_query():
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]4;1;?\x07")
    assert responses == ["\x1b]4;1;rgb:cdcd/0000/0000\x1b\\"]


def test_several_palette_entries_at_once():
    # One answer for each question. xterm sends them apart, and a
    # program reads them apart: it reads up to the terminator once for
    # each query it sent. Joining them leaves it reading the second
    # answer as part of the first.
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]4;0;?;15;?\x07")
    assert responses == [
        "\x1b]4;0;%s\x1b\\" % BLACK,
        "\x1b]4;15;%s\x1b\\" % WHITE,
    ]


def test_a_palette_entry_that_does_not_exist():
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]4;999;?\x07")
    assert responses == []


def test_setting_a_palette_entry_is_ignored():
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]4;1;rgb:00/ff/00\x07")
    assert responses == []


# ----------------------------------------------------------------------
# The kitty colour query.


def test_a_kitty_colour_query():
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]21;background=?\x1b\\")
    assert responses == ["\x1b]21;background=%s\x1b\\" % BLACK]


def test_several_kitty_keys_at_once():
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]21;foreground=?;background=?\x1b\\")
    assert responses == [
        "\x1b]21;foreground=%s;background=%s\x1b\\" % (WHITE, BLACK)
    ]


def test_a_kitty_query_for_a_palette_entry():
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]21;3=?\x1b\\")
    assert responses == ["\x1b]21;3=rgb:cdcd/cdcd/0000\x1b\\"]


def test_a_kitty_query_for_a_colour_we_do_not_hold():
    # An empty value is how a terminal says "not set".
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]21;visual_bell=?\x1b\\")
    assert responses == ["\x1b]21;visual_bell=\x1b\\"]


def test_a_kitty_colour_set_is_ignored():
    _screen, stream, responses = make_screen()
    stream.feed("\x1b]21;background=green\x1b\\")
    assert responses == []


# ----------------------------------------------------------------------
# Everything else.


def test_the_title_still_works():
    screen, stream, responses = make_screen()
    stream.feed("\x1b]2;a title\x07")
    assert screen.title == "a title"
    assert responses == []


def test_the_icon_name_still_works():
    screen, stream, responses = make_screen()
    stream.feed("\x1b]1;an icon\x07")
    assert screen.icon_name == "an icon"


def test_an_unknown_sequence_is_consumed():
    screen, stream, responses = make_screen()
    stream.feed("\x1b]52;c;aGVsbG8=\x07")
    stream.feed("\x1b]99;i=1;body\x1b\\")
    stream.feed("hello")
    assert responses == []
    row = screen.pt_screen.data_buffer[0]
    assert "".join(row[i].char for i in range(5)) == "hello"


def test_a_hyperlink_does_not_reach_the_screen():
    screen, stream, responses = make_screen()
    stream.feed("\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\")
    row = screen.pt_screen.data_buffer[0]
    assert "".join(row[i].char for i in range(4)) == "link"
