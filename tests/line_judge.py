"""
A judge that answers one line of JSON with another.

Three of the judges work this way: the two written in Rust, the one
that reads libghostty-vt, and the one that reads xterm.js. Each is a
program that starts once and answers request after request, because
the hunt asks tens of thousands of times and a process for each would
cost more than the comparison.

The protocol is one line in and one line out:

    {"data": "...", "lines": 6, "columns": 20}
    {"<name>": [[[char, fg, bg, bold, italic, ul, rev, ulcol,
                  link, link_name], ...]]}

A colour is null, ["index", n] or ["rgb", r, g, b]. `link` is the
target of an "OSC 8" and `link_name` is what that emulator calls the
one link; `number_the_links` turns the name into a number of the
screen, because no two emulators name a link alike.

A request may carry one more field:

    {"data": "...", "lines": 6, "columns": 20, "resize": [4, 40]}

`resize` is the size to take **after** the data, as `[lines, columns]`.
`lines` and `columns` are then only the size the data was written at,
and the screen that comes back is the size `resize` names. What the
rows hold is what the reflow of that emulator made of them, which is
the whole point: a reflow is where terminals disagree most, and the
panel had no way to ask. Lillecarl/pymux#64.

Every judge keeps `kitty_oracle.HISTORY` rows of scrollback, so a
widening has rows to pull back. A judge with none would answer "blank"
and agree with every other judge with none, which says how the judges
were built and nothing about the emulators.
"""
import atexit
import json
import os
import subprocess
from typing import Dict, List, Optional, Sequence, Tuple

from kitty_oracle import Cell, number_the_links

__all__ = ["LineJudge", "color_of"]


def color_of(value) -> Optional[Tuple]:
    """
    The colour that a judge holds, in the form that `kitty_oracle` uses.

    A number keeps its number, at every value, because the terminal of
    the user paints the palette from its own theme.
    """
    if value is None:
        return None
    kind = value[0]
    if kind == "rgb":
        return ("rgb", value[1], value[2], value[3])
    return ("index", value[1])


class LineJudge:
    """
    One program that answers for one or more emulators.

    `variable` names the environment variable that holds the path of
    the program. The tests skip when it is not set, so a machine
    without the judge runs the rest.
    """

    def __init__(self, variable: str, names: Sequence[str]) -> None:
        self.variable = variable
        self.names = tuple(names)
        self._process: Optional[subprocess.Popen] = None
        self._failed = False

    def is_available(self) -> bool:
        "True when the variable names a program that runs."
        if self._failed:
            return False
        if self._process is not None:
            return self._process.poll() is None

        path = os.environ.get(self.variable)
        if not path or not os.access(path, os.X_OK):
            self._failed = True
            return False
        try:
            self._process = subprocess.Popen(
                [path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError:
            self._failed = True
            return False
        atexit.register(self.stop)
        return True

    def stop(self) -> None:
        "Let the program finish, and kill it if it will not."
        process, self._process = self._process, None
        if process is None:
            return
        try:
            process.stdin.close()
            process.wait(timeout=5)
        except Exception:
            process.kill()

    def ask(
        self,
        data: str,
        lines: int,
        columns: int,
        resize: Optional[Tuple[int, int]] = None,
    ) -> Dict[str, List[List[Cell]]]:
        "One request, and the screens that come back."
        assert self.is_available(), "%s names no program" % (self.variable,)
        asked = {"data": data, "lines": lines, "columns": columns}
        if resize is not None:
            asked["resize"] = list(resize)
        request = json.dumps(asked)
        self._process.stdin.write(request + "\n")
        self._process.stdin.flush()
        answer = self._process.stdout.readline()
        assert answer, "the judge behind %s stopped answering" % (self.variable,)
        raw = json.loads(answer)

        return {
            name: number_the_links(
                [
                    [
                        Cell(
                            char=cell[0] or " ",
                            fg=color_of(cell[1]),
                            bg=color_of(cell[2]),
                            bold=cell[3],
                            italic=cell[4],
                            underline=cell[5],
                            reverse=cell[6],
                            underline_color=color_of(cell[7]),
                            hyperlink=cell[8],
                            hyperlink_id=cell[9],
                        )
                        for cell in row
                    ]
                    for row in raw[name]
                ]
            )
            for name in self.names
            if name in raw
        }

    def cells(
        self,
        name: str,
        data: str,
        lines: int,
        columns: int,
        resize: Optional[Tuple[int, int]] = None,
    ) -> List[List[Cell]]:
        "Feed `data` to one emulator of this judge and read the screen back."
        return self.ask(data, lines, columns, resize)[name]
