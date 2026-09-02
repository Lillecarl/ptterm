"""
Tests for the key data translation in ptterm.kitty_keys.

`translate_key_data` converts raw key data (as produced by the terminal
feeding the pane) into the encoding that the pane expects, given its
kitty keyboard protocol flags.
"""
from ptterm.kitty_keys import translate_key_data

DISAMBIGUATE = 0b1
REPORT_ALL = 0b1000


def test_flags_zero_legacy_passthrough():
    # Legacy data passes through byte-exact.
    assert translate_key_data("hello", flags=0) == "hello"
    assert translate_key_data("\x1ba", flags=0) == "\x1ba"
    assert translate_key_data("\x01", flags=0) == "\x01"
    assert translate_key_data("\x1b[1;5D", flags=0) == "\x1b[1;5D"
    assert translate_key_data("\x1b[2~", flags=0) == "\x1b[2~"
    assert translate_key_data("\x1bOP", flags=0) == "\x1bOP"


def test_flags_zero_kitty_to_legacy():
    # Kitty sequences are translated to their legacy equivalents.
    assert translate_key_data("\x1b[97;5u", flags=0) == "\x01"
    assert translate_key_data("\x1b[13;5u", flags=0) == "\n"
    assert translate_key_data("\x1b[97;3u", flags=0) == "\x1ba"
    assert translate_key_data("\x1b[27u", flags=0) == "\x1b"
    assert translate_key_data("\x1b[97u", flags=0) == "a"


def test_flags_zero_opaque_sequences_pass_through():
    # Replies and unknown sequences are untouched.
    assert translate_key_data("\x1b[?1;2c", flags=0) == "\x1b[?1;2c"
    assert translate_key_data("\x1b[?u", flags=0) == "\x1b[?u"


def test_release_events_are_dropped():
    assert translate_key_data("\x1b[97;1:3u", flags=0) == ""
    assert translate_key_data("a\x1b[97;1:3ub", flags=0) == "ab"


def test_disambiguate_encodes_ctrl_and_alt():
    assert translate_key_data("\x01", flags=DISAMBIGUATE) == "\x1b[97;5u"
    assert translate_key_data("\x1ba", flags=DISAMBIGUATE) == "\x1b[97;3u"
    assert translate_key_data("\x1b", flags=DISAMBIGUATE) == "\x1b[27u"
    # ctrl+enter / ctrl+tab / ctrl+backspace.
    assert translate_key_data("\n", flags=DISAMBIGUATE) == "\x1b[106;5u"
    assert translate_key_data("\x1b[13;5u", flags=DISAMBIGUATE) == "\x1b[13;5u"


def test_disambiguate_keeps_text_and_plain_functional_keys_legacy():
    assert translate_key_data("a", flags=DISAMBIGUATE) == "a"
    assert translate_key_data("A", flags=DISAMBIGUATE) == "A"
    assert translate_key_data("\r", flags=DISAMBIGUATE) == "\r"
    assert translate_key_data("\t", flags=DISAMBIGUATE) == "\t"
    assert translate_key_data("\x7f", flags=DISAMBIGUATE) == "\x7f"
    assert translate_key_data("\x1b[D", flags=DISAMBIGUATE) == "\x1b[D"
    assert translate_key_data("\x1b[15~", flags=DISAMBIGUATE) == "\x1b[15~"


def test_disambiguate_kitty_input_round_trips():
    # Kitty-encoded input re-encodes to the same bytes.
    assert translate_key_data("\x1b[97;5u", flags=DISAMBIGUATE) == "\x1b[97;5u"
    assert translate_key_data("\x1b[97;3u", flags=DISAMBIGUATE) == "\x1b[97;3u"
    assert translate_key_data("\x1b[1;5D", flags=DISAMBIGUATE) == "\x1b[1;5D"


def test_report_all_keys_encodes_everything():
    assert translate_key_data("a", flags=REPORT_ALL) == "\x1b[97u"
    assert translate_key_data("\r", flags=REPORT_ALL) == "\x1b[13u"
    assert translate_key_data("\x1b[D", flags=REPORT_ALL) == "\x1b[1D"
    assert translate_key_data("\x01", flags=REPORT_ALL) == "\x1b[97;5u"


def test_application_cursor_mode():
    # In application cursor mode, unmodified arrows use SS3.
    assert translate_key_data("\x1b[D", flags=0, application_mode=True) == "\x1bOD"
    assert translate_key_data("\x1bOD", flags=0) == "\x1b[D"
    assert translate_key_data("\x1bOD", flags=0, application_mode=True) == "\x1bOD"


def test_text_from_reported_text():
    # "shift+1 with text '!'" translates to '!' in legacy mode.
    assert translate_key_data("\x1b[49;2;33u", flags=0) == "!"
    assert translate_key_data("\x1b[97;2;65u", flags=DISAMBIGUATE) == "A"


def test_shift_only_kitty_input():
    # shift+a without reported text.
    assert translate_key_data("\x1b[97;2u", flags=0) == "A"


def test_mixed_data():
    # Text, control characters and sequences in one chunk.
    data = "a\x01b\x1b[97;5u c"
    assert translate_key_data(data, flags=0) == "a\x01b\x01 c"
    assert (
        translate_key_data(data, flags=DISAMBIGUATE)
        == "a\x1b[97;5ub\x1b[97;5u c"
    )


def test_trailing_escape():
    assert translate_key_data("\x1b", flags=0) == "\x1b"
    assert translate_key_data("\x1b", flags=DISAMBIGUATE) == "\x1b[27u"
