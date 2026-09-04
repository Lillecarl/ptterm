"""
Tests for the OSC sequences that a pane hands to its embedder.

A pane cannot serve the clipboard, a desktop notification or the shape
of the pointer. Only the terminal of the user can. Those sequences
therefore leave the pane through `osc_func`.
"""
import pytest

from ptterm.screen import FORWARDED_OSC, BetterScreen
from ptterm.stream import BetterStream


def make_screen():
    "Return (stream, list of forwarded sequences, list of answers)."
    forwarded = []
    answers = []
    screen = BetterScreen(
        24,
        80,
        write_process_input=answers.append,
        osc_func=lambda code, param: forwarded.append((code, param)),
    )
    stream = BetterStream(screen)
    return stream, forwarded, answers


def feed(stream, code, param):
    stream.feed("\x1b]%s;%s\x1b\\" % (code, param))


# ----------------------------------------------------------------------
# What leaves the pane.


@pytest.mark.parametrize(
    "code,param",
    [
        ("52", "c;aGVsbG8="),  # Set the clipboard.
        ("52", "p;"),  # Clear the primary selection.
        ("99", "i=1:d=0:p=title;Build ready"),  # A notification.
        ("22", "pointer"),  # The shape of the pointer.
    ],
)
def test_a_sequence_for_the_user_leaves_the_pane(code, param):
    stream, forwarded, answers = make_screen()
    feed(stream, code, param)
    assert forwarded == [(code, param)]
    assert answers == []  # The pane itself answers nothing.


def test_the_forwarded_codes_are_the_three_of_the_user():
    assert FORWARDED_OSC == {"22", "52", "99"}


def test_a_clipboard_query_stays_inside_the_pane():
    "Reading the clipboard of the user is not a right of a pane."
    stream, forwarded, answers = make_screen()
    feed(stream, "52", "c;?")
    feed(stream, "52", "p; ? ")
    assert forwarded == []
    assert answers == []


def test_a_clipboard_write_that_looks_like_a_query_still_leaves():
    "A question mark inside the payload is not a query."
    stream, forwarded, _answers = make_screen()
    feed(stream, "52", "c;Pz8/")
    assert forwarded == [("52", "c;Pz8/")]


# ----------------------------------------------------------------------
# What does not leave the pane.


@pytest.mark.parametrize(
    "code,param",
    [
        ("4", "1;?"),  # A palette query: the pane answers it.
        ("11", "?"),  # A background query: the pane answers it.
        ("21", "background=?"),  # A kitty colour query.
        ("7", "file:///home"),  # The working directory.
        ("8", ";https://example.com"),  # A hyperlink.
        ("777", "notify;title;body"),  # The rxvt notification.
    ],
)
def test_another_sequence_does_not_leave_the_pane(code, param):
    stream, forwarded, _answers = make_screen()
    feed(stream, code, param)
    assert forwarded == []


def test_the_title_does_not_leave_the_pane():
    "The title belongs to the pane. pymux draws it itself."
    stream, forwarded, _answers = make_screen()
    stream.feed("\x1b]0;a title\x1b\\")
    stream.feed("\x1b]2;a title\x1b\\")
    assert forwarded == []


# ----------------------------------------------------------------------
# A pane without an embedder.


def test_a_screen_without_a_function_consumes_the_sequence():
    "A plain ptterm has nowhere to send it, and must not raise."
    answers = []
    screen = BetterScreen(24, 80, write_process_input=answers.append)
    stream = BetterStream(screen)
    stream.feed("\x1b]52;c;aGVsbG8=\x1b\\")
    stream.feed("\x1b]99;i=1;done\x1b\\")
    assert answers == []


def test_the_screen_content_survives_a_forwarded_sequence():
    stream, forwarded, _answers = make_screen()
    screen = stream.listener
    stream.feed("before\x1b]52;c;aGVsbG8=\x1b\\after")
    line = screen.pt_screen.data_buffer[0]
    text = "".join(line[x].char for x in range(len("beforeafter")))
    assert text == "beforeafter"
    assert forwarded == [("52", "c;aGVsbG8=")]
