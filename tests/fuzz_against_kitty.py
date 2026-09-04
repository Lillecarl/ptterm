"""
Random escape sequences, compared cell by cell against kitty.

A hand written test only covers what somebody thought of. This builds
programs out of the pieces that a real program uses and checks that
ptterm draws what kitty draws. When one fails, hypothesis cuts it down
to the shortest sequence that still fails, which is usually short
enough to read.

This file is not named `test_*`, so a plain run of the suite leaves it
alone. It is a tool for hunting, not a gate: it finds deviations faster
than they get fixed, and each one needs a decision about whether to
follow kitty or xterm. `nix-build -A checks.fuzz` runs it, and
`PTTERM_FUZZ` says how many examples to try.
"""
import os

import pytest

hypothesis = pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from kitty_oracle import differences, kitty_is_available  # noqa: E402
from vterm_oracle import libvterm_is_available, three_way  # noqa: E402

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)

LINES, COLUMNS = 8, 24

#: How many examples to try. A build wants to stay quick, so keep the
#: default low and raise it by hand when hunting.
EXAMPLES = int(os.environ.get("PTTERM_FUZZ", "300"))

small = st.integers(min_value=0, max_value=9)
row = st.integers(min_value=1, max_value=LINES)
column = st.integers(min_value=1, max_value=COLUMNS)

#: The alphabet that the random text comes from.
#:
#: A double width character takes two cells, so it breaks a pair when
#: it lands on one and it wraps one column earlier than the rest. A
#: half width character takes one cell, which is the trap next to it.
#:
#: No combining mark: it belongs to the character before it, and an
#: erased cell holds a space here where kitty holds nothing, so the two
#: disagree about a mark that lands on one. `test_combining_marks`
#: covers the marks by hand and `test_known_deviations` holds the
#: difference.
#:
#: No emoji: the width of one comes from the tables of the wcwidth
#: package on our side and from the tables that kitty compiles on
#: theirs, and a difference between the two is a difference of Unicode
#: versions, not a bug of the screen.
ALPHABET = (
    "abcXY 0123.#äé"  # Narrow.
    "你好漢Ａ"  # Double width.
    "ｶﾅ"  # Half width.
)

text = st.text(alphabet=st.sampled_from(ALPHABET), min_size=1, max_size=8)

#: The payload of a string sequence. It holds no control character, so
#: that only the terminator ends it.
payload = st.text(
    alphabet=st.sampled_from("abc019;=:,?/. "),
    min_size=0,
    max_size=10,
)

#: The terminators that end a string sequence.
string_terminator = st.sampled_from(["\x1b\\", "\x07"])

#: The OSC codes that a program really sends.
OSC_CODES = ["0", "1", "2", "4", "8", "10", "11", "12", "21", "22", "52",
             "99", "133", "777", "30001"]

osc = st.builds(
    lambda code, param, end: "\x1b]%s;%s%s" % (code, param, end),
    st.sampled_from(OSC_CODES),
    payload,
    string_terminator,
)

#: DCS, APC, PM and SOS. Each holds a payload up to the string
#: terminator and writes no cell.
#:
#: A DCS payload that starts with "q" is a sixel image and an APC
#: payload that starts with "G" is the graphics protocol of kitty.
#: Both draw, so both sides would need a comparison of pixels rather
#: than of cells. `test_string_sequences` holds one of each by hand.
string_sequence = st.builds(
    lambda opener, param: "\x1b%s%s\x1b\\" % (opener, param),
    st.sampled_from("P_^X"),
    payload.filter(lambda value: not value[:1] in ("q", "G")),
)

#: The renditions that a program really uses. The first sixteen colours
#: go by number as well, because a terminal paints those from the theme
#: of the user.
RENDITIONS = [
    "0",
    "1",
    "3",
    "4",
    "7",
    "22",
    "23",
    "24",
    "27",
    "30",
    "31",
    "37",
    "39",
    "40",
    "42",
    "47",
    "49",
    "90",
    "97",
    "100",
    "107",
    "38;5;1",
    "38;5;9",
    "38;5;200",
    "48;5;2",
    "48;5;250",
    "38;2;10;20;30",
    "48;2;200;100;50",
]

pieces = st.one_of(
    text,
    st.just("\r"),
    st.just("\n"),
    st.just("\r\n"),
    # No tab: kitty moves to the next line on a tab at the right
    # margin and ptterm does not. See `test_known_deviations`.
    # No backspace: kitty steps back to the end of the row above when
    # the cursor sits in the first column and ptterm does not. See
    # `test_known_deviations`.
    st.just("\x1b7"),
    st.just("\x1b8"),
    st.just("\x1bD"),
    st.just("\x1bM"),
    st.sampled_from(["\x1b[?7h", "\x1b[?7l"]),
    st.builds(lambda n, c: "\x1b[%d%s" % (n, c), small,
              st.sampled_from("ABCDEFGLM@PX")),
    # SU and SD take their count from one, because kitty reads a zero
    # as no scroll and xterm reads it as one. See
    # `test_known_deviations`.
    st.builds(lambda n, c: "\x1b[%d%s" % (n, c),
              st.integers(min_value=1, max_value=9), st.sampled_from("ST")),
    st.builds(lambda n: "\x1b[%dG" % n, column),
    st.builds(lambda n: "\x1b[%dd" % n, row),
    st.builds(lambda r, c: "\x1b[%d;%dH" % (r, c), row, column),
    st.builds(lambda n: "\x1b[%dK" % n, st.integers(0, 2)),
    st.builds(lambda n: "\x1b[%dJ" % n, st.integers(0, 2)),
    st.builds(lambda t, b: "\x1b[%d;%dr" % (t, b), row, row),
    st.builds(lambda s: "\x1b[%sm" % s, st.sampled_from(RENDITIONS)),
    osc,
    string_sequence,
    # The character sets. "ESC ( 0" is the line drawing set of the DEC
    # terminals, and shift out and shift in pick G1 and G0.
    st.sampled_from(["\x1b(0", "\x1b(B", "\x1b)0", "\x1b)B", "\x0e", "\x0f"]),
    # The alternate screen. Only "?1049" is here: the two older names
    # keep what the screen held the time before, which ptterm does not.
    # See `test_known_deviations`.
    st.sampled_from(["\x1b[?1049h", "\x1b[?1049l"]),
)

program = st.lists(pieces, min_size=1, max_size=24).map("".join)


@settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(program)
def test_a_random_program_gives_the_same_screen(data):
    # The style of a blank is left out here. ptterm follows xterm and
    # kitty does not, in more than one place, and each of those is
    # written down in `test_known_deviations`. What stays is every
    # character and where it sits, which is where the bugs were.
    found = differences(data, lines=LINES, columns=COLUMNS, blank_style=False)
    assert not found, "%r\n%s" % (data, "\n".join(found[:10]))


@settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(program)
@pytest.mark.skipif(
    not libvterm_is_available(), reason="PTTERM_LIBVTERM names no library"
)
def test_a_random_program_never_leaves_ptterm_alone(data):
    """
    kitty and libvterm never agree with each other against ptterm.

    This is the hunt that needs no decision afterwards. A difference
    from one emulator is a question: which of the two is right? A
    difference from both of them at once is an answer.
    """
    verdict = three_way(data, lines=LINES, columns=COLUMNS, blank_style=False)
    assert verdict != "ptterm-wrong", "%r\n%s" % (
        data,
        "\n".join(differences(data, lines=LINES, columns=COLUMNS,
                              blank_style=False)[:10]),
    )
