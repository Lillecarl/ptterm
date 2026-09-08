"""
What a program started by this widget finds in its environment.

The widget owns a screen and a `Process`. It is therefore the only
layer that can say the two things a program has to be told: that it
draws on this screen and not on the terminal the application runs in,
and where the entry that describes this screen lives. `pyte` has no
child to set an environment for, and `ptyhost` runs a program and has
no opinion on what parses the bytes. Lillecarl/pymux#125.

**These tests fork.** The answers are read off the screen of a real
`sh`, so they say what the child really got and not what this file
thinks the code passes down.
"""

import asyncio
import os

import pytest

from pyte.environment import DEFAULT_DATABASE, terminal_name
from pyte.screen import Screen
from pyte.terminfo import TERMINAL_NAME
from pyte.streams import Stream
from ptyhost import Process

from ptterm.terminal import _in_the_child, create_backend

#: Wide enough that a store path does not wrap, so a row is one answer.
COLUMNS = 400

#: What the child prints: one name and its value on each row.
REPORT = [
    "TERM",
    "TERMINFO_DIRS",
    "COLORTERM",
    "KITTY_WINDOW_ID",
    "HOME",
]

#: The last row the child writes. The run waits for it rather than for
#: the end of the program: what a program writes just before it exits
#: is sometimes lost, because the reaper closes the pty without
#: draining it (Lillecarl/pymux#121). So the child lingers instead.
SENTINEL = "THE END"

SCRIPT = (
    "\n".join('printf "%%s=%%s\\n" %s "$%s"' % (name, name) for name in REPORT)
    + '\nprintf "%s\\n"\nsleep 30\n' % SENTINEL
)

#: What the tests wait, in seconds, and how often the loop turns.
TIMEOUT = 20.0
TICK = 0.01

#: What the outer environment says, so that the child can be asked
#: whether it inherited it or not.
OF_THE_OUTER_TERMINAL = {"KITTY_WINDOW_ID": "1"}
OF_THE_USER = {"HOME": "/home/someone"}


def _read(screen) -> dict:
    "The rows of the screen, as the names and values the child printed."
    answers = {}
    for y in range(screen.lines):
        row = screen.page.data_buffer[y]
        text = "".join(row[x].char for x in range(COLUMNS)).rstrip()
        name, _, value = text.partition("=")
        if name in REPORT:
            answers[name] = value
        if text == SENTINEL:
            answers[SENTINEL] = ""
    return answers


async def run_and_read() -> dict:
    "Start `sh` through the widget's own backend and read what it prints."
    screen = Screen(len(REPORT) + 3, COLUMNS, write_process_input=lambda data: None)
    stream = Stream(screen)
    stream.attach(screen)

    process = Process(
        backend=create_backend(["sh", "-c", SCRIPT], None),
        receive=stream.feed,
    )
    process.set_size(COLUMNS, len(REPORT) + 3)
    process.start()

    try:
        deadline = asyncio.get_event_loop().time() + TIMEOUT
        while SENTINEL not in _read(screen):
            if asyncio.get_event_loop().time() > deadline:
                raise AssertionError(
                    "waited %g seconds; the screen holds %r" % (TIMEOUT, _read(screen))
                )
            await asyncio.sleep(TICK)
    finally:
        process.kill()

    return _read(screen)


@pytest.fixture(scope="module")
def answers() -> dict:
    """
    One child for every test here. It answers every question at once,
    and forking once is worth more than the isolation of forking six
    times for the same six rows.
    """
    kept = dict(os.environ)
    os.environ.update(OF_THE_OUTER_TERMINAL)
    os.environ.update(OF_THE_USER)
    try:
        return asyncio.run(run_and_read())
    finally:
        os.environ.clear()
        os.environ.update(kept)


def test_a_program_is_told_the_name_of_this_screen(answers):
    """
    And not the name of the terminal that the tests themselves run in.

    The name is `pyte` and not the fallback, because a suite runs
    against a build and a build compiles the entry into `pyte`.
    """
    assert answers["TERM"] == TERMINAL_NAME


def test_the_name_never_carries_the_suffix(answers):
    """
    The entry has `pyte-256color` as an alias, and a pane must never be
    given that spelling.

    A program reads "256color" out of `TERM`, decides that the palette
    is the limit, and quantises a 24 bit colour to an index before this
    screen ever sees it.
    """
    assert "256color" not in answers["TERM"]


def test_a_program_finds_the_entry_that_it_is_told_about(answers):
    """
    Naming an entry that is not installed is worse than naming xterm,
    so the two go together: the name is claimed only when the database
    that holds it is named as well.

    The database of `pyte` comes first, and the rest of the list after
    it. An empty entry in that list is the place the system keeps, so
    a program still finds everything it found before.
    """
    assert answers["TERMINFO_DIRS"].startswith(DEFAULT_DATABASE + ":")


def test_a_program_may_write_a_colour(answers):
    assert answers["COLORTERM"] == "truecolor"


def test_the_name_of_the_outer_terminal_is_gone(answers):
    "A program that finds it draws with a protocol this screen lacks."
    assert answers["KITTY_WINDOW_ID"] == ""


def test_the_rest_of_the_environment_reaches_the_program(answers):
    assert answers["HOME"] == "/home/someone"


# ----------------------------------------------------------------------
# The hook itself, with no child around it.
#
# There is no fork here, so the hook writes the environment of the test
# run itself. Every test below therefore gives it a copy: without one
# it leaves `COLORTERM` and `TERMINFO_DIRS` behind, and drops the
# variables that name a terminal, for every test after it.


@pytest.fixture
def an_environment_of_its_own(monkeypatch):
    monkeypatch.setattr(os, "environ", dict(os.environ))


def test_the_hook_of_the_caller_runs_last(an_environment_of_its_own):
    """
    An embedder can still say something different. pymux does: it has
    an option for the name a pane is given.
    """
    os.environ["TERM"] = "nothing"

    def theirs() -> None:
        os.environ["TERM"] = "theirs"

    _in_the_child(theirs)()
    assert os.environ["TERM"] == "theirs"


def test_the_hook_works_without_one_of_their_own(an_environment_of_its_own):
    os.environ["TERM"] = "nothing"
    _in_the_child(None)()
    assert os.environ["TERM"] == terminal_name()
