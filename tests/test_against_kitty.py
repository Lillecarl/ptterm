"""
The screen of ptterm must match the screen of kitty.

kitty carries its emulator as a python extension, so the same bytes can
go into both. It is the terminal that pymux runs inside, so what it
shows is what the user sees. A difference here is a bug that a user
will notice.

These tests skip when `PTTERM_KITTY` does not name a directory holding
the `kitty` package.
"""

import pytest

from kitty_oracle import differences, kitty_is_available, ptterm_cells
from pyte import escape
from pyte.sequences import csi, esc

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)


def check(data, lines=6, columns=20):
    found = differences(data, lines, columns)
    assert not found, "\n".join(found[:20])


# ----------------------------------------------------------------------
# Text and the cursor.


@pytest.mark.parametrize(
    "data",
    [
        "hello",
        "hello\r\nworld",
        "x" * 25,
        "x" * 40 + "\r\ny",
        "abc" + csi(escape.CUP, 2, 5) + "def",
        "abc" + csi(escape.CUP, 2, 5) + "def" + csi(escape.CUU) + "gh",
        "abc\x08\x08X",
        "a\tb\tc",
        csi(escape.CUP, 10, 10) + "x" + csi(escape.CUP),
        "one" + esc(escape.DECSC) + "two" + esc(escape.DECRC) + "three",
    ],
)
def test_text_and_the_cursor(data):
    check(data)


# ----------------------------------------------------------------------
# Colours and attributes.


@pytest.mark.parametrize(
    "data",
    [
        csi(escape.SGR, 31) + "red" + csi(escape.SGR) + " plain",
        csi(escape.SGR, 1, 4) + "hi" + csi(escape.SGR) + " there",
        csi(escape.SGR, 3) + "italic" + csi(escape.SGR, 23) + " plain",
        csi(escape.SGR, 7) + "reverse" + csi(escape.SGR, 27) + " plain",
        csi(escape.SGR, 38, 2, 10, 20, 30) + csi(escape.SGR, 48, 2, 40, 50, 60) + "x",
        csi(escape.SGR, 38, 5, 9) + csi(escape.SGR, 48, 5, 12) + "x",
        csi(escape.SGR, 90) + "bright" + csi(escape.SGR),
        (
            csi(escape.SGR, 41, 32)
            + "mix"
            + csi(escape.SGR, 39)
            + "fg"
            + csi(escape.SGR, 49)
            + "bg"
        ),
        # The shape of an underline, and the colour of the line.
        "\x1b[4:2mdouble\x1b[4:3mcurly\x1b[4:4mdotted\x1b[4:5mdashed\x1b[4:0m",
        csi(escape.SGR, 21) + "double" + csi(escape.SGR, 24) + " plain",
        "\x1b[4:3m\x1b[4msingle",
        "\x1b[4;58:2::255:0:0mred line\x1b[59m plain",
        "\x1b[4;58:5:9mindex\x1b[24m none\x1b[4m again",
        csi(escape.SGR, 4, 58, 5, 9) + "old form" + csi(escape.SGR, 0),
        # The parts of one colour, with colons between them.
        "\x1b[38:5:9m\x1b[48:5:12mx",
        "\x1b[38:2::10:20:30m\x1b[48:2::40:50:60mx",
        "\x1b[38:2:10:20:30mx",
    ],
)
def test_colours_and_attributes(data):
    check(data)


# ----------------------------------------------------------------------
# Erasing. A terminal paints an erased cell with the background that is
# set now, which is how htop draws the header of its table.


@pytest.mark.parametrize(
    "data",
    [
        "hi" + csi(escape.EL),
        csi(escape.SGR, 42) + "hi" + csi(escape.EL),
        csi(escape.SGR, 42) + "hello" + csi(escape.EL, 1),
        csi(escape.SGR, 41) + "hello" + csi(escape.EL, 2),
        "hello" + csi(escape.SGR, 42) + csi(escape.ED),
        "hello" + csi(escape.SGR, 42) + csi(escape.ED, 2),
        "hello" + csi(escape.CUP, 1, 1) + csi(escape.SGR, 43) + csi(escape.ECH, 3),
        csi(escape.SGR, 31) + csi(escape.SGR, 7) + "hi" + csi(escape.EL),
        csi(escape.SGR, 42) + csi(escape.CUP, 2, 2) + "hi" + csi(escape.EL),
    ],
)
def test_erasing(data):
    check(data)


# ----------------------------------------------------------------------
# Lines and characters that move.


@pytest.mark.parametrize(
    "data",
    [
        "a\r\nb\r\nc" + csi(escape.CUP, 2, 1) + csi(escape.IL),
        "a\r\nb\r\nc" + csi(escape.CUP, 2, 1) + csi(escape.DL),
        "abcdef" + csi(escape.CUP, 1, 3) + csi(escape.ICH, 2),
        "abcdef" + csi(escape.CUP, 1, 3) + csi(escape.DCH, 2),
        csi(escape.DECSTBM, 2, 4) + csi(escape.CUP, 2, 1) + "a\r\nb\r\nc\r\nd",
        "a\r\nb\r\nc\r\nd\r\ne\r\nf\r\ng",
    ],
)
def test_lines_and_characters_that_move(data):
    check(data)


# ----------------------------------------------------------------------
# The comparison itself has to notice a wrong screen, or it proves
# nothing.


def test_the_comparison_notices_a_wrong_erase(monkeypatch):
    from pyte.screen import Screen

    # This is what ptterm did before: an erased cell went away, so the
    # background of the moment was lost.
    monkeypatch.setattr(Screen, "erase_appearance", lambda self: None)

    found = differences(csi(escape.SGR, 42) + "hi" + csi(escape.EL))
    assert found, "the comparison did not see the background go missing"
