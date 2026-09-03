"""
Hyperlinks (OSC 8).

A link belongs to the cells that a program draws while it is open, not
to the terminal. The screen keeps the target and every cell carries it,
so the renderer can open the link again on the terminal of the user.
"""
import base64

import pytest

from ptterm.osc import MAX_HYPERLINK_LENGTH, parse_hyperlink
from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

LINK = "https://example.com/a"


def _screen(lines=3, columns=12):
    screen = BetterScreen(lines, columns, write_process_input=lambda data: None)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream


def _style(screen, column, row=0):
    return screen.pt_screen.data_buffer[row][column].style


def _token(target):
    return "[hyperlink:%s]" % base64.b64encode(target.encode()).decode()


def open_link(target=LINK, params=""):
    return "\x1b]8;%s;%s\x1b\\" % (params, target)


CLOSE = "\x1b]8;;\x1b\\"


# ----------------------------------------------------------------------
# Reading the payload.


def test_a_target_is_read():
    assert parse_hyperlink(";" + LINK) == LINK


def test_the_parameters_are_read_and_dropped():
    assert parse_hyperlink("id=1;" + LINK) == LINK


def test_an_empty_target_closes_the_link():
    assert parse_hyperlink(";") == ""
    assert parse_hyperlink("id=1;") == ""


def test_a_payload_without_a_semicolon_is_no_link():
    assert parse_hyperlink(LINK) is None


@pytest.mark.parametrize("target", ["a\x1b]0;owned\x07", "a\x07b", "a\nb", "a\x7fb"])
def test_a_target_with_a_control_character_is_dropped(target):
    assert parse_hyperlink(";" + target) is None


def test_a_target_that_is_too_long_is_dropped():
    assert parse_hyperlink(";" + "a" * MAX_HYPERLINK_LENGTH) is not None
    assert parse_hyperlink(";" + "a" * (MAX_HYPERLINK_LENGTH + 1)) is None


def test_a_target_with_text_of_a_user_survives():
    assert parse_hyperlink(";https://example.com/är") is not None


# ----------------------------------------------------------------------
# What a cell carries.


def test_the_cells_of_a_link_carry_it():
    screen, stream = _screen()
    stream.feed(open_link() + "link" + CLOSE + "plain")
    for column in range(4):
        assert _token(LINK) in _style(screen, column)
    for column in range(4, 9):
        assert "hyperlink" not in _style(screen, column)


def test_a_link_and_a_rendition_live_together():
    screen, stream = _screen()
    stream.feed("\x1b[1;31m" + open_link() + "a")
    style = _style(screen, 0)
    assert "bold" in style
    assert _token(LINK) in style


def test_a_rendition_after_a_link_keeps_the_link():
    screen, stream = _screen()
    stream.feed(open_link() + "a\x1b[1mb")
    assert _token(LINK) in _style(screen, 1)
    assert "bold" in _style(screen, 1)


def test_a_reset_of_the_rendition_keeps_the_link():
    "'CSI 0 m' says nothing about a link."
    screen, stream = _screen()
    stream.feed("\x1b[1m" + open_link() + "a\x1b[0mb")
    assert _token(LINK) in _style(screen, 1)
    assert "bold" not in _style(screen, 1)


def test_a_second_link_replaces_the_first():
    screen, stream = _screen()
    stream.feed(open_link("https://a") + "x" + open_link("https://b") + "y")
    assert _token("https://a") in _style(screen, 0)
    assert _token("https://b") in _style(screen, 1)


def test_a_link_with_an_identifier():
    screen, stream = _screen()
    stream.feed(open_link(params="id=7") + "x")
    assert _token(LINK) in _style(screen, 0)


def test_a_target_that_is_dropped_leaves_the_link_alone():
    # The second target holds an escape, so it never becomes a link and
    # the first one stays open.
    screen, stream = _screen()
    stream.feed(open_link() + "a\x1b]8;;https://b\x1b[2J\x1b\\b")
    assert _token(LINK) in _style(screen, 0)
    assert screen.hyperlink == LINK


def test_a_save_and_a_restore_leave_the_link_alone():
    "'ESC 7' remembers the rendition, and a link is not one."
    screen, stream = _screen()
    stream.feed("\x1b7" + open_link() + "\x1b8a")
    assert _token(LINK) in _style(screen, 0)


def test_the_screen_holds_the_target():
    screen, stream = _screen()
    stream.feed(open_link())
    assert screen.hyperlink == LINK
    stream.feed(CLOSE)
    assert screen.hyperlink == ""
