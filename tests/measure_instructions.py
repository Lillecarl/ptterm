"""
Hold the cost of parsing a recording to a budget.

A change that makes ptterm ten times slower passes every other check
here. Nothing measures the cost, so nothing notices until somebody runs
pymux and it feels wrong.

This measures it, in bytecode instructions and not in seconds. A second
belongs to the machine that counted it: this build sandbox runs beside
fifteen other jobs, and a number from it means nothing on another
machine or on the same one an hour later. An instruction count is the
same everywhere. `tests/instructions.py` says how it is taken and what
moves it.

## What it measures

The recordings that Alacritty ships. Each one is the raw output of a
real program: vim, tmux, fish, zsh, htop, up to a third of a megabyte
of it. They are already here for `checks.pymux-alacritty`, and they are
the largest and most honest workload in the repository.

One measurement is one recording fed to a fresh `BetterScreen` through
`BetterStream`, on the screen that Alacritty recorded it at. That is
the parser and the screen and nothing else: no pty, no client, no
render.

## What it is judged against

`tests/instruction-budgets.txt` holds one line per recording: the name
and the count. A run that differs from its budget by more than the
tolerance fails, in either direction. Both directions matter. A count
that climbed is the fault this check is for, and a count that fell is
a number nobody updated, which makes the budget a lie.

    nix build --file . checks.ptterm-instructions.run
    less result/log
    cp result/instruction-budgets.txt ptterm/tests/instruction-budgets.txt

Two knobs reach this file from `ptterm/nix/checks.nix`:

    PTTERM_INSTRUCTIONS_INCLUDE=vim nix build --file . checks.ptterm-instructions
    PTTERM_INSTRUCTIONS_TOLERANCE=2 nix build --file . checks.ptterm-instructions

`PTTERM_INSTRUCTIONS` names the directory of recordings and
`PTTERM_INSTRUCTIONS_OUT` is where the run leaves its report.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from instructions import count_instructions  # noqa: E402

from ptterm.screen import BetterScreen  # noqa: E402
from ptterm.stream import BetterStream  # noqa: E402

HERE = Path(__file__).parent

#: The counts that this check expects, one name per line.
BUDGETS = HERE / "instruction-budgets.txt"

#: How far a count may move from its budget before the check fails, as
#: a percentage. A refactor moves a count a little; the fault this
#: check is for moves it by a lot.
DEFAULT_TOLERANCE = 5.0

#: The recordings that are too small to hold a budget. A few hundred
#: bytes is mostly the cost of building a screen, so the count says
#: more about the screen size than about the parser.
SMALLEST = 2000


def recordings(root: Path, include: str):
    "Every recording worth measuring, by name, largest first."
    found = []
    for directory in sorted(root.iterdir()):
        recording = directory / "alacritty.recording"
        size = directory / "size.json"
        if not recording.is_file() or not size.is_file():
            continue
        if include and not re.search(include, directory.name):
            continue
        data = recording.read_bytes()
        if len(data) < SMALLEST:
            continue
        shape = json.loads(size.read_text())
        found.append((directory.name, data, shape["screen_lines"], shape["columns"]))
    found.sort(key=lambda one: (-len(one[1]), one[0]))
    return found


def cost(data: bytes, lines: int, columns: int) -> int:
    "The instructions that parsing one recording takes."
    text = data.decode("utf-8", "replace")

    def work():
        screen = BetterScreen(lines, columns, write_process_input=lambda answer: None)
        BetterStream(screen).feed(text)

    return count_instructions(work)


def read_budgets(path: Path):
    "The recorded count of each recording."
    budgets = {}
    if not path.is_file():
        return budgets
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, count = line.rsplit(None, 1)
        budgets[name] = int(count)
    return budgets


HEADER = """\
# What it costs ptterm to parse each of Alacritty's recordings, in
# bytecode instructions. `tests/measure_instructions.py` says why the
# unit is not a second.
#
# This is what the run saw. To make it what the check expects:
#     nix build --file . checks.ptterm-instructions.run
#     cp result/instruction-budgets.txt ptterm/tests/instruction-budgets.txt
"""


def main() -> int:
    root = os.environ.get("PTTERM_INSTRUCTIONS", "")
    if not root:
        print("PTTERM_INSTRUCTIONS is not set, so there is nothing to measure.")
        return 1

    include = os.environ.get("PTTERM_INSTRUCTIONS_INCLUDE", "")
    tolerance = float(
        os.environ.get("PTTERM_INSTRUCTIONS_TOLERANCE", "") or DEFAULT_TOLERANCE
    )

    found = recordings(Path(root), include)
    if not found:
        print("No recording matched %r, so this run measured nothing." % include)
        return 1

    budgets = read_budgets(BUDGETS)
    counts = {}
    wrong = []

    for name, data, lines, columns in found:
        counted = cost(data, lines, columns)
        counts[name] = counted
        budget = budgets.get(name)
        if budget is None:
            print("%-32s %12d  (no budget yet)" % (name, counted))
            wrong.append(name)
            continue
        moved = 100.0 * (counted - budget) / budget
        mark = "ok " if abs(moved) <= tolerance else "OFF"
        print(
            "%-32s %12d  budget %12d  %+6.2f%%  %s"
            % (name, counted, budget, moved, mark)
        )
        if abs(moved) > tolerance:
            wrong.append(name)

    out = os.environ.get("PTTERM_INSTRUCTIONS_OUT", "")
    if out:
        report = HEADER + "".join(
            "%-32s %d\n" % (name, counts[name]) for name in sorted(counts)
        )
        (Path(out) / "instruction-budgets.txt").write_text(report)

    if include:
        print(
            "\nThis run measured %d of the recordings, so it makes no claim "
            "about the rest." % len(found)
        )

    if wrong:
        print(
            "\n%d of %d moved by more than %.1f%%: %s"
            % (len(wrong), len(found), tolerance, ", ".join(sorted(wrong)))
        )
        print(
            "A count that climbed is what this check is for. A count that "
            "fell is a budget nobody updated. Read the numbers, then:"
        )
        print("    cp result/instruction-budgets.txt "
              "ptterm/tests/instruction-budgets.txt")
        return 1

    print("\nEvery recording is within %.1f%% of its budget." % tolerance)
    return 0


if __name__ == "__main__":
    sys.exit(main())
