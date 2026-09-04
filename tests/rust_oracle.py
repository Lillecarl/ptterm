"""
Compare the screen of ptterm against WezTerm and Alacritty.

Both are written in Rust and both keep a screen model of their own,
which `tests/judges` reads back through a small program. One process
answers one request after another, because the hunt asks tens of
thousands of times.

`PTTERM_JUDGES` names that program. The tests skip when it is not set.

These two know everything that a cell of ours holds, the shape of an
underline and the colour of the line included, so nothing is dropped
before the comparison.

The shape of a cell, and the reader that turns a ptterm screen into
cells, live in `kitty_oracle`. This adds two more readers.
"""
import atexit
import json
import os
import subprocess
from typing import Dict, List, Optional, Tuple

from kitty_oracle import (
    Cell,
    _256_COLORS,
    as_seen,
    as_text,
    ptterm_cells,
)

__all__ = [
    "judges_are_available",
    "JUDGE_NAMES",
    "judge_cells",
    "judge_differences",
]

#: The emulators that the program answers for.
JUDGE_NAMES = ("wezterm", "alacritty")

_process: Optional[subprocess.Popen] = None


def judges_are_available() -> bool:
    "True when `PTTERM_JUDGES` names a program that runs."
    global _process
    if _process is not None:
        return _process.poll() is None
    path = os.environ.get("PTTERM_JUDGES")
    if not path or not os.access(path, os.X_OK):
        return False
    try:
        _process = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
    except OSError:
        return False
    atexit.register(_stop)
    return True


def _stop() -> None:
    global _process
    if _process is None:
        return
    try:
        _process.stdin.close()
        _process.wait(timeout=5)
    except Exception:
        _process.kill()
    _process = None


def _color(value) -> Optional[Tuple]:
    """
    The colour that a judge holds, in the form that `kitty_oracle` uses.

    A number of the first sixteen keeps its number, because a terminal
    paints those from the theme of the user. Anything above becomes the
    colour it stands for, the way ptterm resolves it.
    """
    if value is None:
        return None
    kind = value[0]
    if kind == "rgb":
        return ("rgb", value[1], value[2], value[3])
    index = value[1]
    if index < 16:
        return ("index", index)
    if index < len(_256_COLORS):
        red, green, blue = _256_COLORS[index]
        return ("rgb", red, green, blue)
    return None


def _ask(data: str, lines: int, columns: int) -> Dict[str, List[List[Cell]]]:
    "One request to the program, and the screens that come back."
    assert judges_are_available(), "PTTERM_JUDGES names no program"
    request = json.dumps({"data": data, "lines": lines, "columns": columns})
    _process.stdin.write(request + "\n")
    _process.stdin.flush()
    answer = _process.stdout.readline()
    assert answer, "the judges stopped answering"
    raw = json.loads(answer)

    screens = {}
    for name in JUDGE_NAMES:
        screens[name] = [
            [
                Cell(
                    char=cell[0] or " ",
                    fg=_color(cell[1]),
                    bg=_color(cell[2]),
                    bold=cell[3],
                    italic=cell[4],
                    underline=cell[5],
                    reverse=cell[6],
                    underline_color=_color(cell[7]),
                )
                for cell in row
            ]
            for row in raw[name]
        ]
    return screens


def judge_cells(name: str, data: str, lines: int, columns: int) -> List[List[Cell]]:
    "Feed `data` to one of the judges and read the screen back."
    return _ask(data, lines, columns)[name]


def _keeper(strict: bool, blank_style: bool):
    if strict:
        return lambda cell: cell
    return as_seen if blank_style else as_text


def judge_differences(
    name: str,
    data: str,
    lines: int = 6,
    columns: int = 20,
    strict: bool = False,
    blank_style: bool = True,
) -> List[str]:
    "Every cell where ptterm and one judge do not agree, as readable lines."
    ours = ptterm_cells(data, lines, columns)
    theirs = judge_cells(name, data, lines, columns)
    keep = _keeper(strict, blank_style)

    reported = []
    for y in range(lines):
        for x in range(columns):
            mine, other = keep(ours[y][x]), keep(theirs[y][x])
            if mine != other:
                reported.append(
                    "cell %d,%d: ptterm %r, %s %r" % (y, x, mine, name, other)
                )
    return reported
