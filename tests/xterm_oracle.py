"""
Compare the screen of ptterm against xterm itself.

Every other judge is a library. xterm is a program: it draws on an X
display and it has no screen model to call. So this one runs it, on a
display of its own, and asks it what it drew.

**It reads the screen with DECRQCRA.** "CSI Pid ; Pp ; Pt ; Pl ; Pb ;
Pr * y" answers the checksum of a rectangle. A rectangle of one cell
gives that one cell, and `checksumExtension` says what goes into the
number:

    1  csPOSITIVE  do not negate the sum
    2  csATTRIBS   leave the video attributes out
    4  csNOTRIM    count a blank cell like any other
    8  csDRAWN     count a cell nobody wrote, as a space
    16 csBYTE      the character as drawn, not folded to eight bits

All five together, which is 31, make the checksum of one cell the code
point of that cell and nothing else. `Pid` comes back in the answer, so
each query carries the number of the cell it asks about, and a report
that some other sequence caused cannot be read as a cell.

**So it holds the character and nothing else.** No colour, no
underline, no link. That is why xterm has no seat on the panel:
`verdict()` drops what any judge on it misses, and a judge that misses
everything would blind the whole panel. `panel.what_xterm_draws` asks
xterm on its own, where the panel has nothing to say.
Lillecarl/pymux#10.

**One xterm answers every probe.** Starting one is what costs: about
four tenths of a second, once. So the process stays up and "ESC c"
clears it between probes. A probe of eight rows by twenty four columns
then costs under five milliseconds, and one of twenty four by eighty,
which is 1920 queries and 1920 answers, costs ten. Adding this judge
moved `checks.ptterm-panel` from 3.21 to 3.23 seconds.

xterm in slave mode writes the id of its window to the pty as soon as
the window is there. That is the one thing it says on its own, and it
is what says the terminal is ready.
"""
import os
import re
import select
import time
from typing import Callable, List, Optional, Tuple

from kitty_oracle import HISTORY, Cell
from pyte import escape
from pyte.sequences import esc

__all__ = ["xterm_is_available", "xterm_cells"]

#: What goes into a DECRQCRA checksum: the character, positive, for
#: every cell, and not folded to eight bits. `xtermCheckRect` in
#: xterm's `screen.c` is where the bits are read.
CHECKSUM_EXTENSION = 31

#: How long to wait for one answer. A build machine under load starts
#: an X client slowly, and a wait that is too short reads as a fault in
#: the emulator.
PATIENCE = 60.0

#: A cell that holds nothing but its character. Every other field
#: stays at the value a judge answers when it cannot hold that field.
BLANK = Cell(
    char=" ",
    fg=None,
    bg=None,
    bold=False,
    italic=False,
    underline=0,
    reverse=False,
)

#: The answer to one DECRQCRA: "DCS Pid ! ~ D..D ST".
_ANSWER = re.compile(r"\x1bP(\d+)!~([0-9A-Fa-f]+)(?:\x1b\\|\x9c)")

#: The answer to "CSI 18 t", which is the size of the text area.
_SIZE = re.compile(r"\x1b\[8;(\d+);(\d+)t")

#: The id of the window, which xterm writes to the pty in slave mode
#: once the window is there. `main.c` calls it "Write window id so
#: master end can read and use".
_READY = re.compile(r"[0-9a-f]+\r?\n")


def _always(said: str) -> bool:
    "Nothing to wait for: the write itself is the whole exchange."
    return True


def _argv(path: str, lines: int, columns: int, slave: str, fd: int) -> List[str]:
    """
    xterm, told to read a pty that somebody else made.

    "-S<name>/<fd>" is slave mode: xterm takes the file descriptor as
    the terminal it serves, rather than making a pty and forking a
    shell into it. The name before the slash is what "ps" shows.

    The rest is what a judge needs. A checksum has to answer, and both
    the query and the resize are window operations that xterm refuses
    by default.
    """
    return [
        path,
        "-S%s/%d" % (slave, fd),
        "-geometry", "%dx%d" % (columns, lines),
        # A font that fontconfig serves, so the display needs no font
        # path of its own. Small, because the window has to fit the
        # screen at eighty columns and more.
        "-fa", "DejaVu Sans Mono",
        "-fs", "8",
        "+sb",
        "-b", "0",
        "-bw", "0",
        # Always UTF-8, whatever the locale says, because every judge
        # is asked in UTF-8.
        "-u8",
        # A checksum and a resize are both window operations.
        "-xrm", "XTerm*allowWindowOps: true",
        "-xrm", "XTerm*checksumExtension: %d" % CHECKSUM_EXTENSION,
        # As much history as every other judge keeps.
        # `kitty_oracle.HISTORY` says why the number is one number.
        "-xrm", "XTerm*saveLines: %d" % HISTORY,
        "-xrm", "XTerm*cursorBlink: false",
    ]


class _Xterm:
    "One xterm, and the pty that it reads."

    def __init__(self, path: str) -> None:
        self.path = path
        self.fd: Optional[int] = None
        self.process = None
        #: What xterm has said since the last thing this side wrote.
        self.said = ""

    def start(self, lines: int, columns: int) -> None:
        import pty
        import subprocess
        import tty

        master, slave = pty.openpty()
        # The pty translates nothing and echoes nothing. xterm reads the
        # master, so what this side writes to the slave is what xterm
        # sees, byte for byte.
        tty.setraw(slave)
        try:
            self.process = subprocess.Popen(
                _argv(self.path, lines, columns, os.ttyname(slave), master),
                pass_fds=(master,),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        finally:
            os.close(master)
        self.fd = slave

        # The window id says the window is there. xterm sets the pty up
        # on the way, so the settings go on again after it.
        self._talk("", lambda said: _READY.search(said))
        tty.setraw(slave)

    def stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _talk(self, out: str, done: Callable[[str], object]) -> object:
        """
        Say something to xterm, and wait until the answer says enough.

        The write and the read run together. A screen of two thousand
        cells is two thousand queries and two thousand answers, and
        neither fits in a pty: writing it all first would fill the
        buffer while xterm waits for room to answer.

        `done` reads only what xterm said after the last write, so a
        report that an earlier probe caused is never read as this one.
        The whole write goes out before `done` is asked anything.
        """
        payload = out.encode("utf-8", "surrogatepass")
        self.said = ""
        sent = 0
        deadline = time.monotonic() + PATIENCE
        while True:
            if sent >= len(payload):
                found = done(self.said)
                if found:
                    return found
            left = deadline - time.monotonic()
            if left <= 0:
                raise RuntimeError(
                    "xterm answered %r and no more" % (self.said[-400:],)
                )
            writable = [self.fd] if sent < len(payload) else []
            readable, ready, _ = select.select([self.fd], writable, [], min(left, 0.5))
            if ready:
                sent += os.write(self.fd, payload[sent : sent + 4096])
            if readable:
                piece = os.read(self.fd, 1 << 16)
                if not piece:
                    raise RuntimeError("xterm let go of the pty")
                self.said += piece.decode("utf-8", "replace")

    def resize(self, lines: int, columns: int) -> None:
        """
        Take a new size, and wait until xterm has taken it.

        "CSI 8 ; h ; w t" asks, and "CSI 18 t" reports the size that
        the text area has now. The report can come back before the X
        server has resized the window, so it is asked again until it
        says the right thing.
        """
        deadline = time.monotonic() + PATIENCE
        while True:
            found = self._talk(
                "\x1b[8;%d;%dt\x1b[18t" % (lines, columns), _SIZE.search
            )
            if (int(found.group(1)), int(found.group(2))) == (lines, columns):
                return
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "xterm stayed %s by %s, and %d by %d was asked for"
                    % (found.group(1), found.group(2), lines, columns)
                )

    def cells(self, lines: int, columns: int) -> List[List[Cell]]:
        "Read every cell of the screen that is there now."
        wanted = lines * columns
        queries = []
        for y in range(lines):
            for x in range(columns):
                # The identifier is the number of the cell, so an
                # answer says which cell it is about.
                where = y * columns + x + 1
                queries.append(
                    "\x1b[%d;0;%d;%d;%d;%d*y" % (where, y + 1, x + 1, y + 1, x + 1)
                )

        def enough(said: str):
            found = _ANSWER.findall(said)
            return found if len(found) >= wanted else None

        rows = [[BLANK] * columns for _ in range(lines)]
        for where, value in self._talk("".join(queries), enough):
            index = int(where) - 1
            if not 0 <= index < wanted:
                continue
            number = int(value, 16)
            # A cell that counts for nothing holds nothing: the second
            # half of a wide character is the one that does, and ptterm
            # answers a space for it too.
            char = chr(number) if number else " "
            rows[index // columns][index % columns] = BLANK._replace(char=char)
        return rows

    def screen(
        self,
        data: str,
        lines: int,
        columns: int,
        resize: Optional[Tuple[int, int]] = None,
    ) -> List[List[Cell]]:
        """
        Clear the screen, write `data` on it, and read every cell back.

        "ESC c" is a full reset, which puts every setting back to the
        one the command line named. The size is not one of them, so it
        is asked for again.
        """
        self._talk(esc(escape.RIS), _always)
        self.resize(lines, columns)
        self._talk(data, _always)
        if resize is not None:
            self.resize(*resize)
            lines, columns = resize
        return self.cells(lines, columns)


_XTERM: Optional[_Xterm] = None
_FAILED = False


def xterm_is_available() -> bool:
    "True when `PTTERM_XTERM` names an xterm that a display will take."
    global _XTERM, _FAILED
    if _FAILED:
        return False
    if _XTERM is not None:
        return True

    path = os.environ.get("PTTERM_XTERM")
    if not path or not os.access(path, os.X_OK) or not os.environ.get("DISPLAY"):
        _FAILED = True
        return False

    import atexit

    started = _Xterm(path)
    try:
        started.start(24, 80)
    except Exception:
        started.stop()
        _FAILED = True
        raise
    atexit.register(started.stop)
    _XTERM = started
    return True


def xterm_cells(
    data: str, lines: int, columns: int, resize: Optional[Tuple[int, int]] = None
) -> List[List[Cell]]:
    """
    Feed `data` to xterm and read the screen back.

    Only the character of a cell comes back. A checksum carries no
    colour and no underline, so every other field holds the value a
    judge answers when it cannot hold that field.

    xterm rewraps no text when the screen changes width, so a `resize`
    here says what the old rows look like at the new size and not what
    a reflow made of them.
    """
    assert xterm_is_available(), "PTTERM_XTERM names no xterm"
    return _XTERM.screen(data, lines, columns, resize)
