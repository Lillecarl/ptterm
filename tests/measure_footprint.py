"""
What a scrollback costs to hold, in bytes.

`measure_instructions.py` measures what a history costs to *touch*: a
linefeed, a reflow, a frame. Nothing measures what it costs to *keep*,
and that is the other half of the same question. A person raises
`history-limit` to read a long build log, opens sixteen panes and
leaves them for a week, and the machine either has the room or it
swaps.

## Bytes are a fair unit, and seconds are not

`measure_instructions.py` counts bytecode because a second belongs to
the machine that counted it. Bytes do not: the same objects on the
same interpreter take the same room on every machine, so a budget file
can hold them the way it holds an instruction count.

`tracemalloc` is what counts them, and it counts **what Python
allocated**, not what the process holds. That is the number to want.
Resident memory includes the interpreter, the arenas it has not given
back and every other job in the sandbox; it moves when nothing has
changed.

## What it measures

`a_filled_pane(depth)` from `measure_instructions.py` is the fixture:
a real `_TerminalControl` whose history is full to `depth` rows and
has pruned at least once, so the buffer is at its limit rather than on
the way to it.

Each depth is measured twice over:

- **held**, the bytes the filled pane keeps. Everything the parser
  built and did not throw away.
- **a row**, the difference between this depth and the one before it,
  over the rows between them. This is the one to read: it says what
  one line of scrollback costs, and whether the answer to "keep fifty
  thousand rows" is megabytes or gigabytes.

  **It is marginal on purpose.** A filled pane holds the history and
  the pane -- the screen, the parser, the widget's caches -- so
  dividing the whole by the depth charges a row for a share of all
  that, and the shallowest depth pays the most of it. The difference
  between two depths is the history alone. The first depth therefore
  has no per-row figure, because it has nothing to be a difference
  from.

And one line that is not a cost:

- **the sites**, the allocation sites that hold the most, so that a
  number a person does not like points at a line of code.

Two shapes of history, because they are not the same object. **Plain**
is one row per line of output. **Wrapped** is two rows per line, with
the second marked in `wrapped_lines`, so the same depth holds half as
many lines and carries the marks as well.

## What it is judged against

`tests/footprint-budgets.txt` holds one line per measurement, and a
run that differs by more than the tolerance fails in either direction.
A count that climbed is the fault this check is for; a count that fell
is a budget nobody updated.

    nix build --file . checks.ptterm-footprint.run
    less result/log
    cp result/footprint-budgets.txt ptterm/tests/footprint-budgets.txt

Two knobs reach this file from `ptterm/nix/checks.nix`:

    PTTERM_FOOTPRINT_INCLUDE=2000 nix build --file . checks.ptterm-footprint
    PTTERM_FOOTPRINT_TOLERANCE=10 nix build --file . checks.ptterm-footprint
"""

import asyncio
import gc
import os
import re
import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from measure_instructions import DEPTHS, a_filled_pane  # noqa: E402

HERE = Path(__file__).parent

#: The counts that this check expects, one measurement per line.
BUDGETS = HERE / "footprint-budgets.txt"

#: How far a count may move from its budget before the check fails, as
#: a percentage. A refactor of one object moves a total a little; the
#: fault this check is for moves it by a lot.
DEFAULT_TOLERANCE = 5.0

#: How many allocation sites the log names. They are instrumentation
#: and nothing judges them, so this is about what a person reads.
SITES = 12

#: The two shapes of history, and whether each line wraps.
SHAPES = (("plain", False), ("wrapped", True))


def held(depth: int, wrapping: bool) -> tuple[int, list]:
    """
    The bytes one filled pane keeps, and where they were allocated.

    **The snapshot is taken while the pane is alive**, and the fill
    runs inside the trace so that what the parser built on the way is
    counted where it survived. `gc.collect` first, so that what the
    fill threw away is gone rather than pending.

    The pane is returned to nobody and freed by the caller's next
    statement; its bytes are read off the snapshot, which holds
    numbers and not objects.
    """
    gc.collect()
    tracemalloc.start(1)

    pane = a_filled_pane(depth, wrapping)
    gc.collect()

    snapshot = tracemalloc.take_snapshot()
    tracemalloc.stop()

    # The pane has to outlive the snapshot, or the fill is measured
    # against a pane that has already gone.
    assert pane.screen is not None

    statistics = snapshot.statistics("lineno")
    return sum(one.size for one in statistics), statistics[:SITES]


def _where(frame) -> str:
    """
    An allocation site, as a reader can use it.

    A path in the store is a hundred characters of hash before the part
    that says which file, so only the package and what is under it
    stays: `pyte/screen.py:1990`.
    """
    parts = Path(frame.filename).parts
    if "site-packages" in parts:
        parts = parts[parts.index("site-packages") + 1 :]
    else:
        parts = parts[-2:]
    return "%s:%d" % ("/".join(parts), frame.lineno)


def _bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(count) < 1024 or unit == "GB":
            return "%.1f %s" % (count, unit)
        count /= 1024.0
    return "%d B" % (count,)


def read_budgets() -> dict[str, int]:
    if not BUDGETS.is_file():
        return {}

    budgets = {}
    for line in BUDGETS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _space, count = line.rpartition(" ")
        budgets[name.strip()] = int(count)
    return budgets


def write_budgets(counts: dict[str, int]) -> None:
    out = os.environ.get("PTTERM_FOOTPRINT_OUT", "")
    if not out:
        return

    lines = [
        "# What a full scrollback costs to hold, in bytes that Python\n",
        "# allocated. `tests/measure_footprint.py` says what each line\n",
        "# covers and why bytes are a fair unit where seconds are not.\n",
        "#\n",
        "# This is what the run saw. To make it what the check expects:\n",
        "#     nix build --file . checks.ptterm-footprint.run\n",
        "#     cp result/footprint-budgets.txt ptterm/tests/footprint-budgets.txt\n",
    ]
    lines += ["%s %d\n" % (name, counts[name]) for name in sorted(counts)]
    (Path(out) / "footprint-budgets.txt").write_text("".join(lines))


def main() -> int:
    include = os.environ.get("PTTERM_FOOTPRINT_INCLUDE", "")
    tolerance = float(os.environ.get("PTTERM_FOOTPRINT_TOLERANCE") or DEFAULT_TOLERANCE)

    counts: dict[str, int] = {}
    sites: dict[str, list] = {}

    # `Process` reads the running event loop, and a script starts none.
    # `measure_instructions.py` does the same for the same reason.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        for depth in DEPTHS:
            for shape, wrapping in SHAPES:
                name = "%s %d rows" % (shape, depth)
                if include and not re.search(include, name):
                    continue

                print("measuring %s..." % (name,))
                counts[name], sites[name] = held(depth, wrapping)
    finally:
        asyncio.set_event_loop(None)
        loop.close()

    if not counts:
        print("Nothing matched %r." % (include,))
        return 1

    print("\n--- what a full history holds ---")
    print("%-24s %14s %12s" % ("", "held", "a row"))

    for shape, _wrapping in SHAPES:
        deeper = None
        for depth in DEPTHS:
            name = "%s %d rows" % (shape, depth)
            if name not in counts:
                continue

            # **The marginal cost, not the total over the depth.** A
            # filled pane holds the history and the pane: the screen,
            # the parser, the widget's caches. Dividing the whole by
            # the depth charges a row for a share of all that, and the
            # shallowest depth pays the most. The difference between
            # two depths is the history alone.
            a_row = ""
            if deeper is not None:
                before, at = deeper
                a_row = _bytes((counts[name] - counts[before]) / (depth - at))

            print("%-24s %14s %12s" % (name, _bytes(counts[name]), a_row))
            deeper = (name, depth)

    print("\n--- where the bytes are ---")
    for name in sorted(sites):
        print("\n%s:" % (name,))
        for one in sites[name]:
            print("  %-13s %s" % (_bytes(one.size), _where(one.traceback[0])))

    write_budgets(counts)

    budgets = read_budgets()
    over = []
    for name, count in sorted(counts.items()):
        budget = budgets.get(name)
        if budget is None:
            over.append("%s has no budget, and this run holds %d" % (name, count))
            continue
        moved = abs(count - budget) * 100.0 / max(1, budget)
        if moved > tolerance:
            over.append(
                "%s holds %d, and its budget is %d: %.1f%% away"
                % (name, count, budget, moved)
            )

    if over:
        print("\n--- past the budget ---")
        for line in over:
            print(line)
        print("\n`tests/measure_footprint.py` says how to record a new budget.")
        return 1

    print("\nEvery footprint is within %.1f%% of its budget." % (tolerance,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
