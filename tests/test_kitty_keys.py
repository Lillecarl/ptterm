"""
Tests for the key data translation in ptterm.kitty_keys.

`translate_key_data` converts raw key data (as produced by the terminal
feeding the pane) into the encoding that the pane expects, given its
kitty keyboard protocol flags.
"""
from ptterm.kitty_keys import translate_key_data

DISAMBIGUATE = 0b1
EVENT_TYPES = 0b10
ALTERNATE_KEYS = 0b100
REPORT_ALL = 0b1000
ASSOCIATED_TEXT = 0b10000


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
    # An arrow keeps the short form: the number of the sequence is one,
    # and kitty leaves out a parameter that holds its default. Only the
    # SS3 form of application mode goes away.
    assert translate_key_data("\x1b[D", flags=REPORT_ALL) == "\x1b[D"
    assert (
        translate_key_data("\x1b[D", flags=REPORT_ALL, application_mode=True)
        == "\x1b[D"
    )
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


def test_the_key_code_is_the_key_without_shift():
    """
    An upper case letter from a legacy terminal becomes the lower case
    key plus shift, because the protocol asks for the unshifted key.
    """
    assert translate_key_data("A", flags=REPORT_ALL) == "\x1b[97;2u"
    assert translate_key_data("Z", flags=REPORT_ALL) == "\x1b[122;2u"
    # A letter outside ASCII follows the same rule.
    assert translate_key_data("Ä", flags=REPORT_ALL) == "\x1b[228;2u"


def test_a_shifted_character_keeps_its_own_code():
    """
    Which key gives an exclamation mark depends on the layout, and the
    legacy encoding does not say. The character keeps its own code.
    """
    assert translate_key_data("!", flags=REPORT_ALL) == "\x1b[33u"
    assert translate_key_data(":", flags=REPORT_ALL) == "\x1b[58u"


def test_an_upper_case_letter_still_reaches_a_legacy_pane():
    "The shift goes back into the character on the way out."
    assert translate_key_data("A", flags=0) == "A"
    assert translate_key_data("A", flags=DISAMBIGUATE) == "A"
    assert translate_key_data("Ä", flags=0) == "Ä"


# ----------------------------------------------------------------------
# What only a terminal that speaks the protocol can send. ptterm passes
# it on when the pane asked for it, and drops it when the pane did not.
# The forms follow the encoder of kitty (kitty/key_encoding.c).

RELEASE = "\x1b[98;5:3u"


def test_a_release_reaches_a_pane_that_asked_for_the_event_types():
    assert translate_key_data(RELEASE, flags=EVENT_TYPES) == "\x1b[98;5:3u"
    assert (
        translate_key_data(RELEASE, flags=EVENT_TYPES | DISAMBIGUATE)
        == "\x1b[98;5:3u"
    )


def test_a_release_stops_at_a_pane_that_did_not_ask():
    "Nothing in the legacy encoding says that a key came back up."
    assert translate_key_data(RELEASE, flags=0) == ""
    assert translate_key_data(RELEASE, flags=DISAMBIGUATE) == ""
    assert translate_key_data(RELEASE, flags=REPORT_ALL) == ""


def test_a_release_of_a_text_key_leaves_the_modifiers_empty():
    "kitty writes the empty field rather than the value of no modifier."
    assert translate_key_data("\x1b[97;:3u", flags=EVENT_TYPES) == "\x1b[97;:3u"


def test_a_release_of_enter_needs_all_keys_as_escape_codes():
    """
    Enter, Tab and Backspace have a legacy form of one character, and
    kitty reports the release of one of them only when the pane asks
    for every key as an escape code.
    """
    for code in (13, 9, 127):
        release = "\x1b[%d;:3u" % code
        assert translate_key_data(release, flags=EVENT_TYPES) == ""
        assert (
            translate_key_data(release, flags=EVENT_TYPES | REPORT_ALL)
            == release
        )


def test_a_repeat_without_the_flag_is_a_press():
    "That is what the key did, and the legacy encoding says no more."
    assert translate_key_data("\x1b[97;1:2u", flags=0) == "a"
    assert translate_key_data("\x1b[97;1:2u", flags=EVENT_TYPES) == "\x1b[97;:2u"


def test_the_other_codes_of_a_key_reach_a_pane_that_asked():
    "The shifted key and the key of the base layout."
    assert (
        translate_key_data("\x1b[97:65;2u", flags=ALTERNATE_KEYS)
        == "\x1b[97:65;2u"
    )
    assert (
        translate_key_data("\x1b[97::99;2u", flags=ALTERNATE_KEYS)
        == "\x1b[97::99;2u"
    )
    # Without the flag they go away, and the key itself stays.
    assert translate_key_data("\x1b[97:65;2u", flags=REPORT_ALL) == "\x1b[97;2u"


def test_the_text_of_a_key_reaches_a_pane_that_asked():
    """
    The text of a printable key needs no modern terminal: the character
    that a legacy terminal sends is the text of that key event.
    """
    assert translate_key_data("A", flags=REPORT_ALL | ASSOCIATED_TEXT) == (
        "\x1b[97;2;65u"
    )
    assert translate_key_data("a", flags=ASSOCIATED_TEXT) == "\x1b[97;;97u"
    # A key that writes no text carries none.
    assert translate_key_data("\r", flags=REPORT_ALL | ASSOCIATED_TEXT) == (
        "\x1b[13u"
    )
    assert translate_key_data("\x01", flags=REPORT_ALL | ASSOCIATED_TEXT) == (
        "\x1b[97;5u"
    )


# ----------------------------------------------------------------------
# What a legacy keyboard cannot send, made up. A pane that asked for
# the event types reads every key going down and coming up; only the
# time between the two is lost.


def test_a_legacy_key_answers_with_a_press_and_a_release():
    assert translate_key_data("a", flags=EVENT_TYPES) == "a\x1b[97;:3u"
    assert (
        translate_key_data("a", flags=EVENT_TYPES | DISAMBIGUATE)
        == "a\x1b[97;:3u"
    )
    assert translate_key_data("\x01", flags=EVENT_TYPES) == "\x01\x1b[97;5:3u"
    assert translate_key_data("A", flags=EVENT_TYPES) == "A\x1b[97;2:3u"


def test_a_made_up_release_keeps_the_form_of_the_key():
    "An arrow comes up in the form of an arrow, not of a text key."
    assert translate_key_data("\x1b[D", flags=EVENT_TYPES) == "\x1b[D\x1b[1;:3D"
    assert translate_key_data("\x1b[2~", flags=EVENT_TYPES) == (
        "\x1b[2~\x1b[2;:3~"
    )


def test_enter_gets_no_made_up_release_either():
    """
    Enter, Tab and Backspace have no release in the protocol unless the
    pane asks for every key as an escape code. The rule that drops a
    real one drops a made up one.
    """
    assert translate_key_data("\r", flags=EVENT_TYPES) == "\r"
    assert translate_key_data("\t", flags=EVENT_TYPES) == "\t"
    assert translate_key_data("\r", flags=EVENT_TYPES | REPORT_ALL) == (
        "\x1b[13u\x1b[13;:3u"
    )


def test_a_keyboard_that_sends_its_own_release_is_left_alone():
    "Two releases for one key would be worse than none."
    assert (
        translate_key_data("a", flags=EVENT_TYPES, source_flags=0b11111) == "a"
    )
    assert (
        translate_key_data(
            "\x1b[97;:3u", flags=EVENT_TYPES, source_flags=0b11111
        )
        == "\x1b[97;:3u"
    )


def test_nothing_is_made_up_without_the_switch():
    "The host can ask for presses only. The pane then hears that."
    assert translate_key_data("a", flags=EVENT_TYPES, synthesize=False) == "a"
    assert (
        translate_key_data("\x01", flags=EVENT_TYPES, synthesize=False)
        == "\x01"
    )


def test_a_pane_that_asked_for_no_event_type_reads_no_release():
    assert translate_key_data("a", flags=0) == "a"
    assert translate_key_data("a", flags=DISAMBIGUATE) == "a"
    assert translate_key_data("a", flags=REPORT_ALL) == "\x1b[97u"


def test_the_shifted_key_of_a_letter_is_the_letter():
    """
    A pane that asks for the other codes of a key gets that one from a
    legacy keyboard as well. The key of the base layout stays out: it
    is the key itself on every Latin layout, and kitty leaves it out
    there too.
    """
    assert translate_key_data("A", flags=ALTERNATE_KEYS | REPORT_ALL) == (
        "\x1b[97:65;2u"
    )
    assert translate_key_data("Ä", flags=ALTERNATE_KEYS | REPORT_ALL) == (
        "\x1b[228:196;2u"
    )


def test_a_key_with_no_shifted_key_of_its_own_reports_none():
    "Which key gives an exclamation mark is a question of the layout."
    assert translate_key_data("!", flags=ALTERNATE_KEYS | REPORT_ALL) == (
        "\x1b[33u"
    )
    assert translate_key_data("a", flags=ALTERNATE_KEYS | REPORT_ALL) == (
        "\x1b[97u"
    )


def test_the_shifted_key_waits_for_a_pane_that_asked():
    assert translate_key_data("A", flags=REPORT_ALL) == "\x1b[97;2u"
    assert translate_key_data("A", flags=0) == "A"
