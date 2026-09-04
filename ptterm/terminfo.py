"""
The terminfo entry that describes a pane.

A program has two ways to learn what a terminal can do. It can ask,
which `screen.report_capabilities` answers, or it can read the
database of the machine it runs on, which is what every program built
on ncurses does.

This writes the entry for the second way, out of the same table that
answers the first. One source, two readers: the database and the wire
cannot say different things.

Compile it with:

    python -m ptterm.terminfo | tic -x -o <directory> -

The entry names `xterm-256color` as its parent, because that is what a
pane emulates apart from the capabilities below. `tic` copies the
parent in, so what comes out stands on its own.
"""
import sys

from .screen import CAPABILITIES, TERMINAL_NAME

__all__ = ["PARENT", "terminfo_source"]

#: The entry that a pane emulates apart from what it adds. `tic`
#: copies it in, so the result needs nothing else at run time.
PARENT = "xterm-256color"

#: The names of `CAPABILITIES` that describe the query and not the
#: terminal. "TN" and "name" answer with the name of the entry, and
#: "Co" is what termcap calls "colors".
NOT_IN_THE_ENTRY = frozenset(["TN", "name", "Co"])


def terminfo_source(name: str = TERMINAL_NAME, parent: str = PARENT) -> str:
    """
    The entry, as `tic` reads it.

    A capability that is only there or not takes its name alone, a
    number takes "#" and a string takes "=". That is the whole syntax
    that this needs.
    """
    booleans = []
    numbers = []
    strings = []
    for capability, value in sorted(CAPABILITIES.items()):
        if capability in NOT_IN_THE_ENTRY:
            continue
        if value is True:
            booleans.append("%s," % capability)
        elif isinstance(value, int):
            numbers.append("%s#%d," % (capability, value))
        else:
            strings.append("%s=%s," % (capability, value))

    lines = ["%s|%s terminal multiplexer," % (name, name)]
    lines.extend("\t" + line for line in booleans + numbers + strings)
    lines.append("\tuse=%s," % parent)
    return "\n".join(lines) + "\n"


def main() -> None:
    sys.stdout.write(terminfo_source())


if __name__ == "__main__":
    main()
