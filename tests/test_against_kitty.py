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
        "abc\x1b[2;5Hdef",
        "abc\x1b[2;5Hdef\x1b[Agh",
        "abc\x08\x08X",
        "a\tb\tc",
        "\x1b[10;10Hx\x1b[H",
        "one\x1b7two\x1b8three",
    ],
)
def test_text_and_the_cursor(data):
    check(data)


# ----------------------------------------------------------------------
# Colours and attributes.


@pytest.mark.parametrize(
    "data",
    [
        "\x1b[31mred\x1b[m plain",
        "\x1b[1;4mhi\x1b[m there",
        "\x1b[3mitalic\x1b[23m plain",
        "\x1b[7mreverse\x1b[27m plain",
        "\x1b[38;2;10;20;30m\x1b[48;2;40;50;60mx",
        "\x1b[38;5;9m\x1b[48;5;12mx",
        "\x1b[90mbright\x1b[m",
        "\x1b[41;32mmix\x1b[39mfg\x1b[49mbg",
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
        "hi\x1b[K",
        "\x1b[42mhi\x1b[K",
        "\x1b[42mhello\x1b[1K",
        "\x1b[41mhello\x1b[2K",
        "hello\x1b[42m\x1b[J",
        "hello\x1b[42m\x1b[2J",
        "hello\x1b[1;1H\x1b[43m\x1b[3X",
        "\x1b[31m\x1b[7mhi\x1b[K",
        "\x1b[42m\x1b[2;2Hhi\x1b[K",
    ],
)
def test_erasing(data):
    check(data)


# ----------------------------------------------------------------------
# Lines and characters that move.


@pytest.mark.parametrize(
    "data",
    [
        "a\r\nb\r\nc\x1b[2;1H\x1b[L",
        "a\r\nb\r\nc\x1b[2;1H\x1b[M",
        "abcdef\x1b[1;3H\x1b[2@",
        "abcdef\x1b[1;3H\x1b[2P",
        "\x1b[2;4r\x1b[2;1Ha\r\nb\r\nc\r\nd",
        "a\r\nb\r\nc\r\nd\r\ne\r\nf\r\ng",
    ],
)
def test_lines_and_characters_that_move(data):
    check(data)


# ----------------------------------------------------------------------
# The comparison itself has to notice a wrong screen, or it proves
# nothing.


def test_the_comparison_notices_a_wrong_erase(monkeypatch):
    from ptterm.screen import BetterScreen

    # This is what ptterm did before: an erased cell went away, so the
    # background of the moment was lost.
    monkeypatch.setattr(BetterScreen, "erase_style", lambda self: "")

    found = differences("\x1b[42mhi\x1b[K")
    assert found, "the comparison did not see the background go missing"
