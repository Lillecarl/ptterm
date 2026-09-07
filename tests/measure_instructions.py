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

Each recording is measured three times.

**The parse** is the recording fed to a fresh `Screen` through
`Stream`, on the screen that Alacritty recorded it at. That is
the parser and the screen and nothing else: no pty, no client, no
render.

**The render**, written "<name> (render)", is the projection that comes
after it: `_TerminalControl.create_content` turns the screen into a
`UIContent`, and every row of that content is read. It is one frame of
what a person sees, and it is paid on every frame rather than once per
byte. Nothing measured it before, and Lillecarl/pymux#84 asked for it:
a change that moves the cost of a cell hides in the parse count,
because the parse walks the bytes and the render walks the cells.

**The redraw**, written "<name> (redraw)", is the frame after that one,
with one row changed in between. The render is the first frame of a
screen, where every row is new. A pane spends most of its life drawing
a screen it has almost entirely drawn before, and the two counts are
the same number today. Lillecarl/pymux#126 is why they should not be.

## What a deep history costs

Every recording above runs on a screen that has just started, so no
count here says what a pane costs after a day of work. A pane spends
its life at its history limit: tmux keeps two thousand rows by default
and a person who reads a long build log raises it, so ten thousand and
fifty thousand are both ordinary numbers.

So a second workload fills a history to a depth and then measures three
things on it, written "history <depth> (<what>)":

- **linefeed**, the cost of a hundred more lines of plain output. That
  is what a program pays to print. `Screen` prunes the history once per
  hundred linefeeds, so exactly one prune falls inside the count.
- **alternate**, the cost of entering the alternate screen and leaving
  it again. That is what a person pays to open vim and close it, and it
  is where `touch_everything` walks the whole buffer twice.
- **resize**, the cost of one column narrower, which is what dragging a
  window edge does. A reflow reads every row of the buffer and puts it
  back at the new width, so this is the whole history and not the
  screen, paid while a person watches the edge move.
- **copy**, the cost of opening copy mode. It builds a document of the
  whole history: every cell of every row, into text and a list of
  styles, and none of it is lazy.
- **redraw**, the cost of a frame with one row changed, which is the
  frame a pane draws all day.

**An instruction count cannot see all of this workload.** `max(buffer)`
and `min(buffer)` walk fifty thousand keys inside one `CALL`, and C runs
no bytecode. So each history measurement runs a second time, on a pane
of its own and with nothing counting, and prints the seconds that run
took in a column that nothing judges. A budget in seconds would fail on
a loaded machine. A reader who sees a count stand still while the
seconds climb is looking at exactly the cost the count cannot see.

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
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from instructions import count_instructions  # noqa: E402
from no_backend import NoBackend  # noqa: E402

from pyte.screen import Screen  # noqa: E402
from pyte.streams import Stream  # noqa: E402
from ptterm.terminal import Terminal, _TerminalControl  # noqa: E402

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
        screen = Screen(lines, columns, write_process_input=lambda answer: None)
        Stream(screen).feed(text)

    return count_instructions(work)


#: The name that the render of a recording is written under.
RENDER = "%s (render)"


def render_cost(data: bytes, lines: int, columns: int) -> int:
    """
    The instructions that one frame of the widget takes, on the screen
    that the recording left.

    The parse is not in the count: the recording goes in first, and
    only the projection is measured. That is one frame, and a pane
    draws a frame every time its content changes.

    The rows are the ones a pane at the bottom of its history shows,
    and never the whole buffer. prompt_toolkit asks for the rows it
    draws, so a count over the history would be a scroll through the
    whole recording and not a frame of it.
    """
    text = data.decode("utf-8", "replace")
    control = _TerminalControl(backend=NoBackend())
    # The size reaches the process the way a render does, and then the
    # program writes. A write before the size lands on a screen of no
    # columns.
    control.create_content(columns, lines)
    control.stream.feed(text)

    def work():
        content = control.create_content(columns, lines)
        first = max(0, content.line_count - lines)
        for number in range(first, content.line_count):
            content.get_line(number)

    return count_instructions(work)


#: The name that a frame after a change is written under.
REDRAW = "%s (redraw)"

#: What a program writes to change one row. It is the shape of a status
#: line that ticks: move the cursor, write a few characters, and touch
#: nothing else.
ONE_ROW_CHANGED = "\x1b[1;1Hredrawn"


def redraw_cost(data: bytes, lines: int, columns: int) -> int:
    """
    The instructions that a frame takes when one row changed since the
    frame before it.

    `render_cost` is the other end of the same question. It measures
    the first frame after a recording, where nothing has been drawn
    before and every row is new to whoever draws it.

    **A pane spends most of its life here instead.** A program writes a
    line, and the frame after it draws a screen that is almost entirely
    the screen it drew last time. A widget that knew which rows moved
    would pay for one of them; nothing knows, so every row is built
    again. Lillecarl/pymux#126 is that difference, and this is the
    number that says how big it is.
    """
    text = data.decode("utf-8", "replace")
    control = _TerminalControl(backend=NoBackend())
    control.create_content(columns, lines)
    control.stream.feed(text)

    def frame():
        content = control.create_content(columns, lines)
        first = max(0, content.line_count - lines)
        for number in range(first, content.line_count):
            content.get_line(number)

    # The frame before the change. Whatever the widget remembers of a
    # screen it has drawn, it remembers after this one.
    frame()
    control.stream.feed(ONE_ROW_CHANGED)

    return count_instructions(frame)


#: The depths of history to measure. Two thousand is what `Screen`
#: keeps by default, and what tmux keeps by default. The other two are
#: what a person sets who wants to scroll back through a build log.
DEPTHS = (2000, 10000, 50000)

#: The shape of the pane that the history workload runs in. It is the
#: size of a terminal that nobody resized.
HISTORY_LINES = 24
HISTORY_COLUMNS = 80

#: How many lines of plain output the linefeed measurement writes.
#: `Screen` prunes its history once per hundred linefeeds, so exactly
#: one prune falls inside a count of this many.
LINEFEED_ROWS = 100

#: How far past the depth the fill goes. The buffer has to be at its
#: limit and not on the way to it, so the fill outruns the depth by
#: more than one prune.
PAST_THE_DEPTH = 3 * LINEFEED_ROWS


def _fill(control, depth: int):
    "Write past the depth, so the history is full and not filling."
    control.create_content(HISTORY_COLUMNS, HISTORY_LINES)
    control.stream.feed(
        "".join(
            "line %d\r\n" % number
            for number in range(depth + HISTORY_LINES + PAST_THE_DEPTH)
        )
    )


def a_filled_pane(depth: int):
    "A widget whose history is full to `depth` rows."
    control = _TerminalControl(
        backend=NoBackend(), get_history_limit=lambda: depth
    )
    _fill(control, depth)
    return control


def a_filled_terminal(depth: int):
    """
    A whole `Terminal` whose history is full, because copy mode belongs
    to the widget and not to the control under it.
    """
    terminal = Terminal(
        backend=NoBackend(), get_history_limit=lambda: depth
    )
    _fill(terminal.terminal_control, depth)
    return terminal


def history_cost(depth: int, prepare):
    """
    What one piece of work costs on a pane filled to `depth`, as the
    instructions it runs and the seconds it takes.

    `prepare` builds a filled pane of its own and returns the work to
    measure, so that whatever the work needs first stays outside both
    numbers.

    The two runs are two panes. A count and a clock cannot come from
    one run: `sys.monitoring` calls back into Python on every bytecode,
    which makes the run tens of times slower than a real one. And each
    piece of work changes the pane it runs on, so the same pane cannot
    serve twice.
    """
    counted = count_instructions(prepare(depth))
    work = prepare(depth)
    started = time.perf_counter()
    work()
    return counted, time.perf_counter() - started


def linefeed_work(depth: int):
    "A hundred lines of plain output, which is what a program prints."
    control = a_filled_pane(depth)
    lines = "".join(
        "another line %d\r\n" % number for number in range(LINEFEED_ROWS)
    )
    return lambda: control.stream.feed(lines)


#: What a program writes to enter the alternate screen and leave it.
#: vim and less both do this, and both ends replace the buffer.
ALTERNATE_SCREEN = "\x1b[?1049h\x1b[?1049l"


def alternate_work(depth: int):
    "Opening a full screen program and closing it again."
    control = a_filled_pane(depth)
    return lambda: control.stream.feed(ALTERNATE_SCREEN)


def resize_work(depth: int):
    """
    One column narrower, which is what dragging a window edge does.

    A resize reflows: every row of the buffer is read, taken apart into
    characters and put back at the new width. That is the whole history
    and not the screen, and it happens while a person watches the edge
    move.
    """
    control = a_filled_pane(depth)
    return lambda: control.screen.resize(
        lines=HISTORY_LINES, columns=HISTORY_COLUMNS - 1
    )


def copy_work(depth: int):
    """
    Opening copy mode, which is what a person presses a key for.

    It builds a document of the whole history: every row, and every
    cell of every row, into text and a list of styles. Nothing of it is
    lazy, so the rows a person never scrolls to are paid for as well.
    """
    terminal = a_filled_terminal(depth)
    return terminal.read_the_screen_into_the_copy_buffer


def redraw_work(depth: int):
    "A frame with one row changed since the frame before it."
    control = a_filled_pane(depth)

    def frame():
        content = control.create_content(HISTORY_COLUMNS, HISTORY_LINES)
        first = max(0, content.line_count - HISTORY_LINES)
        for number in range(first, content.line_count):
            content.get_line(number)

    frame()
    control.stream.feed(ONE_ROW_CHANGED)
    return frame


#: The name that each history measurement is written under.
HISTORY = "history %d (%s)"

#: What the history workload measures, in the order it measures it.
HISTORY_WORK = (
    ("linefeed", linefeed_work),
    ("alternate", alternate_work),
    ("resize", resize_work),
    ("copy", copy_work),
    ("redraw", redraw_work),
)


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
# What it costs ptterm to parse each of Alacritty's recordings, to draw
# the first frame of the screen that each one leaves, and to draw the
# frame after that one with a single row changed. The unit is bytecode
# instructions; `tests/measure_instructions.py` says why it is not a
# second, and what "(render)" and "(redraw)" each measure.
#
# The "history <depth>" lines are the second workload: a pane whose
# scrollback is full to that many rows, and what it then costs to print
# a hundred lines, to open and close a full screen program, and to draw
# a frame with one row changed.
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
    histories = [
        (HISTORY % (depth, what), measure, depth)
        for depth in DEPTHS
        for what, measure in HISTORY_WORK
        if not include or re.search(include, HISTORY % (depth, what))
    ]
    if not found and not histories:
        print("Nothing matched %r, so this run measured nothing." % include)
        return 1

    budgets = read_budgets(BUDGETS)
    counts = {}
    wrong = []

    def judge(name: str, counted: int, seconds: float | None = None) -> None:
        """
        Print one measurement against its budget, and remember a miss.

        `seconds` is printed and never judged. It is there for the work
        that runs in C, which an instruction count cannot see.
        """
        counts[name] = counted
        clock = "" if seconds is None else "  %8.4fs" % seconds
        budget = budgets.get(name)
        if budget is None:
            print("%-40s %12d  (no budget yet)%s" % (name, counted, clock))
            wrong.append(name)
            return
        moved = 100.0 * (counted - budget) / budget
        mark = "ok " if abs(moved) <= tolerance else "OFF"
        print(
            "%-40s %12d  budget %12d  %+6.2f%%  %s%s"
            % (name, counted, budget, moved, mark, clock)
        )
        if abs(moved) > tolerance:
            wrong.append(name)

    def judge_over_time(name: str, prepare, depth: int) -> None:
        "Judge one history measurement, and print its clock as well."
        judge(name, *history_cost(depth, prepare))

    # `Process` reads the running event loop, and a script starts none.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        for name, data, lines, columns in found:
            judge(name, cost(data, lines, columns))
            judge(RENDER % name, render_cost(data, lines, columns))
            judge(REDRAW % name, redraw_cost(data, lines, columns))
        if histories:
            print()
        for name, measure, depth in histories:
            judge_over_time(name, measure, depth)
    finally:
        asyncio.set_event_loop(None)
        loop.close()

    out = os.environ.get("PTTERM_INSTRUCTIONS_OUT", "")
    if out:
        report = HEADER + "".join(
            "%-40s %d\n" % (name, counts[name]) for name in sorted(counts)
        )
        (Path(out) / "instruction-budgets.txt").write_text(report)

    if include:
        print(
            "\nThis run measured %d of the recordings and %d of the "
            "histories, so it makes no claim about the rest."
            % (len(found), len(histories))
        )

    if wrong:
        print(
            "\n%d of %d moved by more than %.1f%%: %s"
            % (len(wrong), len(counts), tolerance, ", ".join(sorted(wrong)))
        )
        print(
            "A count that climbed is what this check is for. A count that "
            "fell is a budget nobody updated. Read the numbers, then:"
        )
        print("    cp result/instruction-budgets.txt "
              "ptterm/tests/instruction-budgets.txt")
        return 1

    print("\nEvery measurement is within %.1f%% of its budget." % tolerance)
    return 0


if __name__ == "__main__":
    sys.exit(main())
