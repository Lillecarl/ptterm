"""
Hyperlinks (OSC 8).

A link belongs to the cells that a program draws while it is open, not
to the terminal. The screen keeps the target and every cell carries it,
so the renderer can open the link again on the terminal of the user.

A link also has an id. The id joins the pieces of one link, so a link
that a line break cuts in two is one link and not two. A cell carries
the id the same way it carries the target.
"""
import base64

import pytest

from pyte.osc import (
    MAX_HYPERLINK_ID_LENGTH,
    MAX_HYPERLINK_LENGTH,
    parse_hyperlink,
)
from pyte.screen import Screen
from pyte.streams import Stream
from ptterm.style import style_of
from pyte import escape
from pyte.sequences import csi
from pyte.sequences import esc
from pyte.modes import PrivateMode
from pyte.sequences import set_mode

LINK = "https://example.com/a"


def _screen(lines=3, columns=12):
    screen = Screen(lines, columns, write_process_input=lambda data: None)
    stream = Stream(screen)
    return screen, stream


def _style(screen, column, row=0):
    return style_of(screen.page.data_buffer[row][column].appearance)


def _token(target):
    return "[hyperlink:%s]" % base64.b64encode(target.encode()).decode()


def _id_token(link_id):
    return "[hyperlink-id:%s]" % base64.b64encode(link_id.encode()).decode()


def open_link(target=LINK, params=""):
    return "\x1b]8;%s;%s\x1b\\" % (params, target)


CLOSE = "\x1b]8;;\x1b\\"


# ----------------------------------------------------------------------
# Reading the payload.


def test_a_target_is_read():
    assert parse_hyperlink(";" + LINK) == ("", LINK)


def test_an_id_is_read():
    assert parse_hyperlink("id=1;" + LINK) == ("1", LINK)


def test_an_id_among_other_parameters_is_read():
    "The field is 'key=value : key=value', and 'id' is the only key."
    assert parse_hyperlink("a=b:id=1:c=d;" + LINK) == ("1", LINK)
    assert parse_hyperlink("a=b;" + LINK) == ("", LINK)


def test_an_empty_target_closes_the_link():
    assert parse_hyperlink(";") == ("", "")
    assert parse_hyperlink("id=1;") == ("", "")


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


@pytest.mark.parametrize("link_id", ["a\x1bb", "a\x07b", "a\nb", "a\x7fb", "a=b"])
def test_an_id_that_would_break_the_sequence_is_dropped(link_id):
    "The link still opens. Only the id goes."
    assert parse_hyperlink("id=%s;%s" % (link_id, LINK)) == ("", LINK)


def test_an_id_that_is_too_long_is_dropped():
    longest = "i" * MAX_HYPERLINK_ID_LENGTH
    assert parse_hyperlink("id=%s;%s" % (longest, LINK)) == (longest, LINK)
    assert parse_hyperlink("id=%si;%s" % (longest, LINK)) == ("", LINK)


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
    stream.feed(csi(escape.SGR, 1, 31) + open_link() + "a")
    style = _style(screen, 0)
    assert "bold" in style
    assert _token(LINK) in style


def test_a_rendition_after_a_link_keeps_the_link():
    screen, stream = _screen()
    stream.feed(open_link() + "a" + csi(escape.SGR, 1) + "b")
    assert _token(LINK) in _style(screen, 1)
    assert "bold" in _style(screen, 1)


def test_a_reset_of_the_rendition_keeps_the_link():
    "'CSI 0 m' says nothing about a link."
    screen, stream = _screen()
    stream.feed(csi(escape.SGR, 1) + open_link() + "a" + csi(escape.SGR, 0) + "b")
    assert _token(LINK) in _style(screen, 1)
    assert "bold" not in _style(screen, 1)


def test_a_second_link_replaces_the_first():
    screen, stream = _screen()
    stream.feed(open_link("https://a") + "x" + open_link("https://b") + "y")
    assert _token("https://a") in _style(screen, 0)
    assert _token("https://b") in _style(screen, 1)


def test_the_cells_of_a_link_carry_its_id():
    screen, stream = _screen()
    stream.feed(open_link(params="id=7") + "x")
    assert _token(LINK) in _style(screen, 0)
    assert _id_token("7") in _style(screen, 0)


def test_a_link_with_no_id_carries_none():
    screen, stream = _screen()
    stream.feed(open_link() + "x")
    assert "hyperlink-id" not in _style(screen, 0)


def test_a_new_id_opens_the_same_target_again():
    "Two ids are two links, whatever the target says."
    screen, stream = _screen()
    stream.feed(open_link(params="id=1") + "x" + open_link(params="id=2") + "y")
    assert _id_token("1") in _style(screen, 0)
    assert _id_token("2") in _style(screen, 1)


def test_the_screen_holds_the_id():
    screen, stream = _screen()
    stream.feed(open_link(params="id=7"))
    assert screen.hyperlink_id == "7"
    stream.feed(CLOSE)
    assert screen.hyperlink_id == ""


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
    stream.feed(esc(escape.DECSC) + open_link() + esc(escape.DECRC) + "a")
    assert _token(LINK) in _style(screen, 0)


def test_the_screen_holds_the_target():
    screen, stream = _screen()
    stream.feed(open_link())
    assert screen.hyperlink == LINK
    stream.feed(CLOSE)
    assert screen.hyperlink == ""


def test_a_link_of_the_alternate_screen_does_not_reach_the_first():
    "A program that leaves a link open may not hand it to the shell."
    screen, stream = _screen()
    stream.feed("\x1b[?1049h" + open_link() + "a\x1b[?1049lb")
    assert screen.hyperlink == ""
    assert "hyperlink" not in _style(screen, 0)


def test_the_alternate_screen_starts_with_no_link():
    screen, stream = _screen()
    stream.feed(open_link() + set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR) + "a")
    assert screen.hyperlink == ""
    assert "hyperlink" not in _style(screen, 0)


def test_a_link_of_the_first_screen_does_not_come_back():
    """
    A link is not part of the cursor that "?1049" saves, and the cells
    of the first screen keep the one they were drawn with anyway.
    """
    screen, stream = _screen()
    stream.feed(open_link() + "a\x1b[?1049h\x1b[?1049lb")
    assert screen.hyperlink == ""
    assert _token(LINK) in _style(screen, 0)
    assert "hyperlink" not in _style(screen, 1)
