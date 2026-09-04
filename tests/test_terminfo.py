"""
The terminfo entry that describes a pane.

Two readers, one table. `screen.report_capabilities` answers a program
that asks over the wire, and this entry answers one that reads the
database instead. They come from `CAPABILITIES`, so they cannot say
different things.

The check that matters is that `tic` takes the entry: a source file
with one comma wrong compiles to nothing, and a pane whose `TERM`
names an entry that is not there is worse off than one that says
`xterm-256color`.
"""
import pathlib
import shutil
import subprocess

import pytest

from ptterm.screen import CAPABILITIES, TERMINAL_NAME
from ptterm.terminfo import PARENT, terminfo_source

tic = shutil.which("tic")
infocmp = shutil.which("infocmp")

pytestmark = pytest.mark.skipif(
    not (tic and infocmp), reason="ncurses is not on the path"
)


@pytest.fixture
def compiled(tmp_path):
    "The entry, compiled into a database of its own."
    source = tmp_path / "pymux.ti"
    source.write_text(terminfo_source())
    database = tmp_path / "terminfo"
    database.mkdir()
    subprocess.run(
        [tic, "-x", "-o", str(database), str(source)], check=True, capture_output=True
    )
    return database


def described(database):
    "What ncurses reads back out of the database."
    answer = subprocess.run(
        [infocmp, "-x", TERMINAL_NAME],
        check=True,
        capture_output=True,
        text=True,
        env={"TERMINFO_DIRS": "%s:" % database, "PATH": "/usr/bin:/bin"},
    )
    return answer.stdout


def test_the_entry_compiles(compiled):
    assert (compiled / TERMINAL_NAME[0] / TERMINAL_NAME).exists()


def test_every_capability_of_the_table_is_in_the_entry(compiled):
    "Apart from the three that describe the query and not the terminal."
    text = described(compiled)
    for name in CAPABILITIES:
        if name in ("TN", "name", "Co"):
            continue
        assert name in text, "%s is not in the entry" % name


def test_the_entry_carries_what_the_parent_holds(compiled):
    "'use=' brings in the rest, so the entry stands on its own."
    text = described(compiled)
    for capability in ("cup=", "smcup=", "setaf=", "kcuu1="):
        assert capability in text


def test_the_shape_and_the_colour_of_an_underline_are_there(compiled):
    text = described(compiled)
    assert "Smulx=" in text
    assert "Setulc=" in text
    assert "Su," in text or "Su=" in text


def test_the_source_names_a_parent():
    assert "use=%s," % PARENT in terminfo_source()


def test_the_name_can_be_something_else():
    assert terminfo_source(name="pymux-256color").startswith("pymux-256color|")
