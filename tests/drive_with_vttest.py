"""
Walk vttest against ptterm, and keep every screen it draws.

vttest is the other conformance program of Thomas Dickey, after Per
Lindberg wrote it in 1985. It is nothing like esctest2. esctest2 reads
the screen back with DECRQCRA and judges it, so it can be a gate.
vttest draws a screen and asks a person whether what they see is right.

So this is not a gate, and it does not try to be. It is a walker: it
enters every menu item, answers every "Push <RETURN>", and writes down
what the screen held each time. What comes out is a text file of every
screen vttest can draw, with the menu path that reached it. A person
reads that file. Lillecarl/pymux#46 says why the recorded list comes
before any question about a gate.

The host is the one `drive_with_esctest.py` uses, for the same reason:
a `Process` on a `PosixBackend` is a terminal with no pane around it,
so what this judges is ptterm alone. It answers a resize too, because
vttest switches between 80 and 132 columns and a screen drawn at the
wrong width says nothing.

**Never send a key before the prompt is on the screen.** `holdit()` in
vttest's `unix_io.c` calls `inflush()` before it prints "Push
<RETURN>", and `inflush` throws away everything waiting on the input.
A key sent early is a key that vanishes, and then both sides wait.

**The fence is a fact and not a guess.** vttest says nothing about
where it is, so the first version of this file waited for the screen
to stop moving. That costs a wait on every one of four hundred
screens, and the whole walk took a quarter of an hour. But vttest is a
child on a pty this process owns, so there is something exact to read:
`/proc/<pid>/syscall` says it is blocked in `read` on file descriptor
zero, and `select` says the pty holds nothing more to draw. Together
those two mean it has finished and wants a key. `Walk.waiting` holds
them. The walk then takes about a minute.

That is Linux, and only a Linux with `/proc/<pid>/syscall`. There is
no fence on macOS, so the walk does not run there and says so.

**A menu is walked once.** vttest builds each level out of the level
below it: the VT220 menu is a submenu of the VT320 menu, which is a
submenu of the VT420 menu. Walking each of them from the top is the
same screens three times over, and it is most of the run. The walker
leaves a menu it has already walked, and writes the path down. Use
`PTTERM_VTTEST_INCLUDE` to walk one of them at the level it sits
under.

Run it:

    nix build --file . checks.ptterm-vttest.run
    less result/screens.txt

Narrow it to one item of the main menu while hunting one screen. The
regular expression matches the top level entry, as "N title":

    PTTERM_VTTEST_INCLUDE='^1 ' nix build --file . checks.ptterm-vttest.run

`PTTERM_VTTEST_ARGS` passes options to vttest itself. The useful one is
`-u`, which stops it switching the terminal out of UTF-8 at startup.

Three variables reach this file from `ptterm/nix/checks.nix`:
`PTTERM_VTTEST` names the program, and the check does nothing when it
is not set. `PTTERM_VTTEST_OUT` names the directory to write the
screens and the log into. `PTTERM_VTTEST_INCLUDE` narrows the walk.
"""
from __future__ import annotations

import asyncio
import os
import platform
import re
import select
import shlex
import sys
import termios
import time
from pathlib import Path

from ptterm.backends.posix import PosixBackend
from ptterm.process import Process
from ptterm.screen import DoubleHeight, TerminalChar

#: The screen vttest draws on. Its own default is 24 by 80, with 132
#: as the wide setting, and it prints the size in the title when it is
#: given anything else.
ROWS, COLUMNS = 24, 80

#: The sizes this host will take, the way `drive_with_esctest.py` does.
#: A program asks for a resize and a real terminal answers, but a
#: program that asks for a million rows should get a refusal.
SMALLEST, LARGEST = 1, 500

#: How long the whole walk may take, in seconds. The fence is exact,
#: so this is not a budget the walk spends: it is the point at which
#: something has gone wrong and the run should say so.
#:
#: Measured, the walk takes 247 seconds for 502 screens, and two runs
#: write the same list of them. Most steps end at the fence in under
#: twenty milliseconds. The time is vttest sleeping: `read_buffer`
#: in its `unix_io.c` sleeps a tenth of a second before every reply it
#: reads, and `reset.c` sleeps whole seconds after RIS because a real
#: terminal would. The run prints where its time went, so a walk that
#: grows says why.
RUN_TIMEOUT = 420.0

#: How often the driver looks at the run. The loop has to turn for the
#: reader to read at all.
TICK = 0.005

#: How long one screen may take before the walker gives up on it, in
#: seconds.
#:
#: Almost every step ends at the fence and costs nothing. This covers
#: the one shape the fence cannot see: `read_buffer` in vttest's
#: `unix_io.c` sleeps a tenth of a second and then reads whatever has
#: arrived, so a report that ptterm never answers leaves vttest awake
#: and looping rather than blocked in `read`. Nothing tells that apart
#: from a test that is drawing slowly.
#:
#: Twenty seconds let each of those run to the end, and thirty-nine of
#: them cost two hundred seconds of a five minute walk. Five is enough
#: for every test that does finish, and the walk records the path of
#: each one it cuts off, which is a finding rather than a fault: it
#: names a report ptterm does not answer.
PROMPT_TIMEOUT = 5.0

#: The same, once the walker knows this screen wants a person. It has
#: waited the long time here already, and the escape ladder comes back
#: to the same screen several times over.
SHORT_TIMEOUT = 0.5

#: How long the pty has to stay quiet before the screen is believed,
#: in seconds.
#:
#: The fence and this are not the same question. The fence says vttest
#: is blocked wanting a key. This says nothing more is on its way. A
#: report test writes its query, sleeps a tenth of a second, reads what
#: has arrived and draws it, and whether the reply lands inside one of
#: those sleeps or across two of them decides what the screen holds.
#: The fence cannot see that; a screen that has stopped changing can.
SETTLE = 0.03

#: How long to leave a screen that wants a person, between one escape
#: and the next. Such a screen reads a key without waiting for a line,
#: so an escape that it does not want leaves it blocked exactly where
#: it was and the fence says so again at once.
ESCAPE_GRACE = 0.1

#: The number of the `read` system call, by machine. `/proc/<pid>/syscall`
#: names the call a process is blocked in, and that is the fence: vttest
#: reads its keyboard with `read(0, ...)` and nothing else.
#:
#: This is Linux only, and a machine that is not in this table has no
#: fence either. Without a fence there is nothing but guessing, and a
#: walk that guesses takes a quarter of an hour instead of a minute.
#: So the walk does not run at all there, and says so.
READ_SYSCALL = {"x86_64": 0, "aarch64": 63, "riscv64": 63}

#: What a screen asks for, and what to send it.
#:
#: vttest writes the key it wants on the screen, in its own words, the
#: same way it writes "Push <RETURN>". So the walker reads the
#: instruction rather than guessing, and sends nothing at all to a
#: screen that names no key.
#:
#: That rule is what makes the walk repeatable. The version before this
#: worked through a ladder of likely keys whenever it was unsure, and
#: one of them was "0", which leaves a menu. A mistimed "0" dropped out
#: of a menu the walk was in the middle of and took every item below it
#: with it. Two runs then covered different amounts of vttest: 666
#: screens against 712, diverging from the thirtieth screen.
ASKS = (
    (re.compile(r"Press 'q' to quit"), "q"),
    (re.compile(r"[Rr]epeat a key to quit"), "qq"),
    (re.compile(r"press any key twice to quit"), "qq"),
    (re.compile(r"Finish with RETURN"), "\r"),
    (re.compile(r"Finish with TAB"), "\t"),
    (re.compile(r"[Pp]ress the backspace key"), "\b"),
    (re.compile(r"press return to continue"), "\r"),
)

#: What to send to a screen that asks for nothing, once it has stopped
#: making progress. A report that ptterm never answers leaves vttest
#: polling, and it comes out of that by itself, so the walker waits
#: first and only then sends this.
#:
#: **It has to be a line with something on it.** `inputline` in
#: vttest's `unix_io.c` ends with `while (!*s)`, so it throws an empty
#: line away and reads again. The free text prompts of `xterm.c` — the
#: window title, the font name — use it, and a bare return there is a
#: deadlock: vttest blocks in `read` for ever and the walker spins.
#: Measured at "3 Set window title", where the driver burned 52.9
#: seconds of CPU in twenty minutes and vttest used 0.2.
LAST_RESORT = "x\r"

#: How many times to look at a screen that asks for nothing before
#: sending `LAST_RESORT`.
PATIENCE = 3

#: A guard against a menu that never ends.
MOST_STEPS = 20000

#: The menu items that need a person, and the reason for each. A path
#: that matches one of these regular expressions is never entered.
#:
#: An exclusion is not a finding. A finding says the screen was wrong.
#: An exclusion says nobody can answer the question from here, so there
#: is no screen to look at.
NOT_OURS = (
    (
        r"^5 Test of keyboard",
        "it reads keys, one at a time, and says what it got. A walker "
        "has no fingers, and the answers it would send are the answers "
        "it wrote itself.",
    ),
    (
        r"^12 Modify test-parameters",
        "it changes what the run after it does. A recorded list has to "
        "be the same list every time.",
    ),
    (
        r"/ \d+ Test VT\d+ features$",
        "vttest builds each level out of the level below it, so the "
        "VT220 menu is a submenu of the VT320 menu and that one is a "
        "submenu of the VT420 menu. The main menu reaches each level "
        "directly, under \"Test of VT<n> features\", and this pattern "
        "matches only the nested copies. Walking all three is the same "
        "screens three times over and most of the run.",
    ),
    (
        r"/ \d+ Test keyboard-control / ",
        "DECBKM, DECNKM, DECKBUM and DECKPM each ask for a key on a "
        "keyboard and say what came back. A walker has no fingers.",
    ),
    (
        r"/ \d+ Test User-Defined Keys \(DECUDK\)$",
        "it loads a function key and asks a person to press it. "
        "`tst_udk` in vttest's vt220.c reads until it gets a 'q'.",
    ),
    (
        r"/ \d+ Test Send/Receive mode \(SRM\)$",
        "it turns the local echo off and on and asks a person to type "
        "and say what they saw.",
    ),
    (
        r"/ \d+ Set/Reset Mode - LineFeed / Newline$",
        "it asks for the RETURN key and reads what the keyboard sent, "
        "which is what LNM changes. The walker writes bytes to the pty "
        "and never encodes a key, so it can only send itself back.",
    ),
    (
        r"/ \d+ Request Mode \(DECRQM\)/Report Mode \(DECRPM\)",
        "vttest asks about sixty modes in a row and waits a tenth of a "
        "second for each reply. It comes out by itself and costs most "
        "of a walk to watch. Which of those ptterm answers is worth "
        "its own measurement, and this is not it.",
    ),
    (
        r"/ \d+ Test Checksum of Rectangular Area \(DECRQCRA\): G[LR]$",
        "the same shape: a run of queries, each waited for. esctest2 "
        "already covers DECRQCRA one assertion at a time.",
    ),
    (
        r"/ \d+ Select Flow Control Type \(DECSFC\)$",
        "it waits for a reply to DECRQSS that does not come.",
    ),
    (
        r"/ 4 Bug D: Narrow to wide screen$",
        "it resizes and then waits, and what it waits for depends on "
        "the terminal answering the resize before it asks.",
    ),
    (
        r"/ 13 Test Keyboard Layout with G0 Selection$",
        "it is the keyboard test again, with a character set chosen. "
        "`tst_keyboard_layout` in vttest's keyboard.c reads a key at a "
        "time until it gets a carriage return.",
    ),
)

#: The prompt of a menu, and the largest choice it takes.
MENU_PROMPT = re.compile(r"Enter choice number \(0 - (\d+)\):")

#: One line of a menu: the number, a mark, and the description.
#: `show_entry` in vttest's `main.c` writes '*' where the item is not
#: implemented and '.' where it is.
MENU_ENTRY = re.compile(r"^\s+(\d+)[.*] (.+?)\s*$")

#: What `holdit` writes when it waits for a return.
HOLD = "Push <RETURN>"

#: How a double sized row is written down. A text dump of one is blank
#: information without it: item 4 of the main menu is entirely about
#: rows that are twice as big, and every cell in them looks ordinary.
_DOUBLE_HEIGHT_WORDS = {
    DoubleHeight.NONE: "double-width",
    DoubleHeight.TOP: "double-height-top",
    DoubleHeight.BOTTOM: "double-height-bottom",
}


class Failed(AssertionError):
    pass


class Frame:
    "One menu the walker stands in, and how far through it is."

    def __init__(self, key, entries, largest: int) -> None:
        #: What tells this menu from another. `key_of` says what it is.
        self.key = key
        #: The items of the menu, as (number, description) pairs. They
        #: are read again on every visit, because a menu relabels an
        #: item to say what it would do next.
        self.entries = entries
        #: The largest choice the prompt takes. Item 0 leaves.
        self.largest = largest
        #: The next item to enter.
        self.next = 1
        #: The name of the item the walker is inside, if any.
        self.inside: str | None = None


def _text_of(cell) -> str:
    """
    One cell, as what it shows.

    A cell that nothing wrote is not a `TerminalChar`, and it shows a
    space. The second half of a wide character holds no character at
    all, and it shows nothing: the character before it already covers
    both columns, so the row stays as wide as the screen.
    """
    if not isinstance(cell, TerminalChar):
        return " "
    return cell.char


def rows_of(screen) -> list[str]:
    "Every row of the visible screen, as text."
    buffer = screen.pt_screen.data_buffer
    offset = screen.line_offset
    out = []
    for row in range(screen.lines):
        line = buffer[offset + row]
        out.append("".join(_text_of(line[column])
                           for column in range(screen.columns)))
    return out


def attributes_of(screen) -> list[str]:
    "The rows that are drawn twice as big, and how."
    offset = screen.line_offset
    out = []
    for row in range(screen.lines):
        attribute = screen.line_attributes.get(offset + row)
        if attribute is None:
            continue
        out.append("%d %s" % (row, _DOUBLE_HEIGHT_WORDS[attribute.double_height]))
    return out


def entries_of(rows: list[str]):
    "The menu entries on a screen, as (number, description) pairs."
    found = []
    for row in rows:
        match = MENU_ENTRY.match(row)
        if match:
            found.append((int(match.group(1)), match.group(2)))
    return tuple(found)


def key_of(rows: list[str], entries):
    """
    What tells one menu from another: its title, and how many items.

    Not the text of the items. Several menus relabel an item to say
    what it would do next, and the printer menu is the worst of them:
    "Assign printer" becomes "Release printer" as soon as it is used.
    A key that held the text would call each of those a new menu, walk
    it from the top, and never come out.

    **This is a guess, and it is the last one left.** vttest knows the
    answer exactly: `current_menu` in its `main.c` holds the position
    of the menu it is in, one number per level, and `title` writes it
    above the items as "Menu 11.8.2.4.1.1: ...". Reading that off the
    screen does not work, because `menu2` redraws with
    `vt_move(top, 1); vt_clear(0)`, which wipes the title line. The key
    then flips between the real number and nothing, the walker decides
    it is back at the main menu, and re-walks everything: measured at
    10250 screens against 456.

    The same number reaches the log, and there it cannot be wiped.
    `main.c` writes `Note: choice <number>: <name>` on every choice
    vttest takes. Reading the log is how this stops guessing.
    """
    first = len(rows)
    for number, row in enumerate(rows):
        if MENU_ENTRY.match(row):
            first = number
            break
    title = tuple(row.strip() for row in rows[:first] if row.strip())
    return title, tuple(number for number, _ in entries)


def largest_choice(rows: list[str]) -> int | None:
    "The N of `Enter choice number (0 - N)`, or None on no menu."
    for row in rows:
        match = MENU_PROMPT.search(row)
        if match:
            return int(match.group(1))
    return None


def holds(rows: list[str]) -> bool:
    "Whether the screen waits for a return."
    return any(HOLD in row for row in rows)


def prompted(rows: list[str]) -> bool:
    """
    Whether vttest is asking a person, rather than the terminal.

    The fence cannot tell the two apart. `instr` in vttest's
    `unix_io.c` calls `inchar`, and `inchar` does a blocking
    `read(0, ...)` — the same call `readnl` makes for a menu choice.
    So a test that has sent DECRQSS and is waiting for ptterm to
    answer looks exactly like a test waiting for a key.

    The screen tells them apart. vttest writes "Enter choice number"
    or "Push <RETURN>" before it waits for a person, and writes
    neither before it waits for a reply. Without this the walker
    caught the gap between a query and its answer, wrote the screen
    down as one that wanted a person, and did so only sometimes: two
    runs then differed on DECSLRM, DECSPRTT, DECTME, DECTTC, DECSCS
    and S7C1T.
    """
    return largest_choice(rows) is not None or holds(rows)


def asked_for(rows: list[str]):
    "The keys this screen asks for in words, or None if it names none."
    text = "\n".join(rows)
    for pattern, keys in ASKS:
        if pattern.search(text):
            return keys
    return None


def read_syscall_here():
    """
    The number of the `read` call, or None where there is no fence.

    Three things have to hold: Linux, a kernel that writes
    `/proc/<pid>/syscall`, and a machine this file knows the number
    for. macOS fails the first.
    """
    number = READ_SYSCALL.get(platform.machine())
    if number is None or not Path("/proc/self/syscall").exists():
        return None
    return number


class Walk:
    """
    The walker: a depth first pass over every menu vttest has.

    It knows nothing about which item does what. It reads the screen,
    and the screen says whether vttest wants a menu choice, a return,
    or something this cannot give.
    """

    def __init__(self, include: str, through: bool = False) -> None:
        self.include = re.compile(include)
        #: Whether vttest draws on this program's own terminal too.
        #: When it does, everything the walker says goes to stderr, so
        #: that its words are never mistaken for what vttest drew.
        self.through = through
        self.say = sys.stderr if through else sys.stdout
        self.process: Process | None = None
        self.ended = False
        #: The number of the `read` call on this machine. `main`
        #: refuses to walk without it, so it is never None here.
        self.read_syscall = read_syscall_here()
        #: Set when the walker has answered the last menu, so a screen
        #: that comes after it is the program on its way out.
        self.leaving = False

        #: The menus the walker stands in, outermost first.
        self.stack: list[Frame] = []
        #: Every screen that was held, as text.
        self.screens: list[str] = []
        #: What `NOT_OURS` kept the walker out of, as (path, reason).
        self.left_out: list[tuple[str, str]] = []
        #: The paths where no prompt came, so the screen wants a person.
        self.stuck: list[str] = []
        #: The same, as a set, so one path is written down once.
        self.asked: set[str] = set()
        #: The top level items the include kept out.
        self.narrowed: list[str] = []
        #: The menus that have been walked to the end.
        self.walked: set = set()
        #: How many screens each path has taken, so each one gets a
        #: number within its own item and not over the whole run.
        self.taken: dict[str, int] = {}
        #: The last screen kept for each path, so the same one held
        #: twice is not written down twice.
        self.last: dict[str, list[str]] = {}
        #: When the pty last had something on it, for `SETTLE`.
        self.arrived = time.monotonic()
        #: The identity of every screen kept, in order. Two runs that
        #: do not write the same list are two runs whose pictures
        #: cannot be compared, so this is what says the walk is
        #: reliable.
        self.identities: list[str] = []
        #: How long each step took, as (seconds, path). A walk with the
        #: fence spends its time where vttest spends it, so this says
        #: which tests are slow rather than how long a guess was.
        self.spent: list[tuple[float, str]] = []
        #: Every menu the walker met, by key, with the path it was at.
        #: Two menus with one key are a key that does not tell them
        #: apart, and this file is where that shows.
        self.menus: dict = {}
        #: The paths where such a menu turned up a second time.
        self.again: list[str] = []

    # -- the host -------------------------------------------------------

    def done(self) -> None:
        self.ended = True

    def resize(self, lines, columns) -> None:
        """
        Take the size vttest asks for.

        It switches between 80 and 132 columns in several tests, and a
        screen drawn at the width it did not ask for is a screen that
        says nothing. A side it leaves alone arrives as None.
        """
        process = self.process
        assert process is not None
        width = process.sx if columns is None else columns
        height = process.sy if lines is None else lines
        if not SMALLEST <= width <= LARGEST:
            return
        if not SMALLEST <= height <= LARGEST:
            return
        process.set_size(width, height)

    def hush(self, backend) -> None:
        """
        Take the echo off the pty before vttest starts.

        The fence alone is not enough to say vttest has acted on a key.
        `/proc/<pid>/syscall` reports the call a task is blocked in, and
        a task that has been woken but not yet scheduled still reports
        the `read` it is about to leave. So the walker could read the
        screen it had just answered, answer it again, and skip the
        screen after it. Two runs then walk different amounts of vttest,
        which was measured: 666 screens against 712.

        So the walker waits for the screen to change as well. That only
        works if vttest is the only thing that can change it, and echo
        is the other thing: the line discipline writes every key back
        before vttest has seen it.

        vttest keeps this. `init_ttymodes` copies the modes it found,
        and `restore_ttymodes` puts those back, so the modes it starts
        from are the ones set here.
        """
        modes = termios.tcgetattr(backend.slave)
        modes[3] &= ~termios.ECHO
        termios.tcsetattr(backend.slave, termios.TCSANOW, modes)

    def pass_through(self, backend) -> None:
        """
        Send what vttest writes to this program's own terminal as well.

        Without this the walk happens where nobody can see it. With it
        the walker is a proxy: vttest draws on a real terminal, and the
        same bytes go into the ptterm model that decides when a screen
        is ready. That is what lets a picture be taken of vttest in
        kitty or foot, with pymux in the chain and without it, and the
        two compared.

        Nothing goes the other way. The walker answers vttest itself,
        so the keyboard of the outer terminal is not in the loop and
        there is no input to forward.

        The bytes are the ones the reader decoded, encoded again. That
        is exact for anything well formed, which vttest is.
        """
        original = backend.read_text
        # The real terminal, and not `sys.stdout`. `main` points that
        # at stderr before the walk starts, so reading it here would
        # send every byte vttest drew into the log and leave the
        # terminal blank. Both go to the same place in a nix log, so
        # the mistake looked right until a picture was taken.
        out = sys.__stdout__.buffer

        def read_text(amount: int = 4096) -> str:
            data = original(amount)
            if data:
                out.write(data.encode("utf-8", "surrogatepass"))
                out.flush()
            return data

        backend.read_text = read_text

    def start(self, command: list[str]) -> None:
        backend = PosixBackend.from_command(command)
        self.hush(backend)
        if self.through:
            self.pass_through(backend)
        self.process = Process(
            invalidate=lambda: None,
            backend=backend,
            done_callback=self.done,
            resize_func=self.resize,
        )
        # The size first, so the child forks onto a pty of the size it
        # will really have. `Process.start` would set 120 by 24.
        self.process.set_size(COLUMNS, ROWS)
        backend.start()
        backend.connect_reader()

    def answer(self, text: str) -> None:
        "Send one line to vttest. `readnl` waits for the newline."
        self.send(text + "\n")

    def escape(self, text: str) -> None:
        "Send something to a screen the walker does not understand."
        self.send(text)

    def send(self, text: str) -> None:
        assert self.process is not None
        self.process.write_input(text)

    def waiting(self) -> bool:
        """
        Whether vttest has finished drawing and wants a key.

        This is the fence, and it is not a guess. vttest is a child on
        a pty this process owns, so two facts settle the question.

        It is blocked in `read` on file descriptor 0. Every input path
        of vttest ends there: `readnl` for a menu choice, `inchar` for
        a raw key, `read_buffer` for the reply to a report. A process
        that is still drawing is in `write` or `nanosleep` instead, and
        `/proc/<pid>/syscall` says which.

        And the master side of the pty holds nothing more, so what it
        drew has already reached the screen.

        Neither is a timer. A screen costs what it costs to draw and
        nothing after that, which is why a walk with the fence takes
        about a minute and a walk without it takes a quarter of an
        hour.
        """
        assert self.process is not None
        backend = self.process.backend
        if backend.master is None or backend.pid is None:
            return False
        if select.select([backend.master], [], [], 0)[0]:
            # Something is still on its way. Date it, so the settle
            # below counts from the last byte and not from the answer.
            self.arrived = time.monotonic()
            return False
        try:
            fields = Path("/proc/%d/syscall" % backend.pid).read_text().split()
        except OSError:
            # The child is gone, or /proc says "running".
            return False
        if len(fields) < 2 or fields[0] != str(self.read_syscall):
            return False
        if int(fields[1], 16) != 0:
            return False
        # Blocked on the keyboard, and quiet for long enough that
        # nothing else is coming. `SETTLE` says why both are needed.
        return time.monotonic() - self.arrived >= SETTLE

    def mode(self) -> str:
        """
        Which read vttest is in, from the modes of the pty.

        The fence says vttest wants a key. It does not say which of
        three calls is asking, and the three want different things:
        `inputline` wants a menu choice and a newline, `readnl` wants
        the newline alone, and `inchar` wants one key with no line at
        all. Guessing between them is what makes a walk unreliable.

        The line discipline knows. `inputline` and `readnl` run in the
        mode vttest starts in, which is canonical with echo. Every test
        that reads keys itself calls `set_tty_raw(TRUE)` and
        `set_tty_echo(FALSE)` first, and those clear ICANON and ECHO on
        the very pty this process owns. So the mode tells a screen that
        wants a line from a screen that wants a keyboard, and the
        second kind is exactly the kind no walker can answer.
        """
        assert self.process is not None
        master = self.process.backend.master
        if master is None:
            return "gone"
        try:
            flags = termios.tcgetattr(master)[3]
        except termios.error:
            return "gone"
        words = []
        words.append("canonical" if flags & termios.ICANON else "raw")
        words.append("echo" if flags & termios.ECHO else "no-echo")
        return " ".join(words)

    async def next_prompt(self, anchor: list[str], timeout: float):
        """
        Wait until vttest wants a key, and return what it had drawn.

        Two things have to hold, and the second is not optional.

        The fence: vttest is blocked reading its keyboard and the pty
        holds nothing more to draw. `waiting` says why that is a fact.

        And the screen has moved since the answer that got us here.
        The fence alone races: a task woken by that answer but not yet
        scheduled still reports the read it is leaving, so the walker
        would read the screen it had just answered and answer it again.
        `hush` takes the echo off so that a screen which has moved has
        moved because vttest drew on it.
        """
        assert self.process is not None
        deadline = time.monotonic() + timeout
        while not self.ended:
            rows = rows_of(self.process.screen)
            if rows != anchor and self.waiting() and prompted(rows):
                return rows
            if time.monotonic() > deadline:
                return rows
            await asyncio.sleep(TICK)
        return rows_of(self.process.screen)

    # -- what a screen means --------------------------------------------

    def path_of(self, name: str | None = None) -> str:
        "The menu path, as the names that reached here."
        names = [frame.inside for frame in self.stack if frame.inside]
        if name is not None:
            names.append(name)
        return " / ".join(names)

    def keep(self, rows: list[str], why: str) -> None:
        "Write one screen down, with the path that reached it."
        assert self.process is not None
        screen = self.process.screen
        attributes = attributes_of(screen)
        path = self.path_of() or "(the main menu)"

        # A screen held twice is one screen. The report tests wait a
        # tenth of a second for a reply and then read what has arrived,
        # so a reply that lands across two of those sleeps makes vttest
        # hold the same screen again. Whether that happens is a race
        # inside vttest, and counting the repeat would put a screen in
        # one run's list and not the other's: measured on DECXCPR,
        # DECTME, DECTTC and DECSCS. Nothing is lost by dropping it,
        # because it is the same picture.
        if self.last.get(path) == rows:
            return
        self.last[path] = rows
        out = [
            "",
            "=" * 72,
            "path: %s" % path,
            "why:  %s" % why,
            "size: %d rows by %d columns" % (screen.lines, screen.columns),
            "the pty is: %s" % self.mode(),
            "cursor: row %d, column %d" % (
                screen.pt_cursor_position.y - screen.line_offset,
                screen.pt_cursor_position.x,
            ),
        ]
        if attributes:
            out.append("line attributes: %s" % ", ".join(attributes))
        out.append("-" * 72)
        for number, row in enumerate(rows):
            out.append("%2d |%s|" % (number, row))
        self.screens.append("\n".join(out))

        # The identity of this screen: the path that reached it, and
        # which screen of that item it is. Never an ordinal over the
        # whole run, because then one screen more anywhere renames
        # every screen after it and no two runs can be compared.
        self.taken[path] = self.taken.get(path, 0) + 1
        identity = "%s #%d" % (path, self.taken[path])
        self.identities.append(identity)

        # Say so while it happens, not at the end. This walk takes
        # minutes, and a run that prints nothing until it is over
        # cannot be watched with `nix log`. Twice that turned a walk
        # which had deadlocked into one that looked merely slow: the
        # driver was spinning at four percent of a core and vttest had
        # used a fifth of a second in twenty minutes.
        print("vttest: %s" % identity, file=self.say, flush=True)

    def excluded(self, path: str) -> str | None:
        "The reason `NOT_OURS` keeps the walker out of a path, or None."
        for pattern, reason in NOT_OURS:
            if re.search(pattern, path):
                return reason
        return None

    def frame_for(self, key, entries, largest: int) -> Frame:
        """
        The frame this menu belongs to.

        A menu the walker already stands in means it came back out of
        an item. A menu it does not know is one it just entered. The
        key is what tells them apart, because nothing else does: the
        two screens are drawn the same way.
        """
        for depth, frame in enumerate(self.stack):
            if frame.key == key:
                del self.stack[depth + 1:]
                frame.inside = None
                frame.entries = entries
                return frame
        frame = Frame(key, entries, largest)
        self.stack.append(frame)
        return frame

    # -- the walk -------------------------------------------------------

    async def run(self) -> None:
        unknown = 0
        anchor: list[str] = []
        for _ in range(MOST_STEPS):
            if self.ended:
                return
            here = self.path_of() or "(the main menu)"
            started = time.monotonic()
            waiting = SHORT_TIMEOUT if here in self.asked else PROMPT_TIMEOUT
            rows = await self.next_prompt(anchor, waiting)
            # What the screen holds as the next answer goes out. The
            # prompt after it has to differ from this.
            anchor = rows
            self.spent.append((time.monotonic() - started, here))
            if self.ended:
                return

            largest = largest_choice(rows)
            if largest is not None:
                unknown = 0
                self.at_a_menu(rows, largest)
                continue

            if holds(rows):
                unknown = 0
                self.keep(rows, "vttest asked to push return")
                self.answer("")
                continue

            # Neither prompt, and the last menu is answered: this is
            # vttest on its way out.
            if self.leaving:
                return

            # Neither prompt. The screen asks a person for something,
            # so write it down once and work through the escapes.
            if here not in self.asked:
                self.asked.add(here)
                self.keep(rows, "no menu and no return; the pty is %s"
                          % self.mode())
                self.stuck.append(here)

            keys = asked_for(rows)
            if keys is None:
                # The screen names no key. Wait: vttest polling for a
                # reply that never comes gets there on its own.
                unknown += 1
                if unknown < PATIENCE:
                    continue
                keys = LAST_RESORT
            unknown = 0
            self.escape(keys)
            # A key this screen did not want leaves it blocked in the
            # same read, and the fence would say so again in the same
            # millisecond.
            await asyncio.sleep(ESCAPE_GRACE)

        raise Failed("the walk took more than %d steps" % MOST_STEPS)

    def at_a_menu(self, rows: list[str], largest: int) -> None:
        "Choose the next item of the menu that is on the screen."
        entries = entries_of(rows)
        key = key_of(rows, entries)
        self.menus.setdefault(key, []).append(self.path_of())
        frame = self.frame_for(key, entries, largest)

        # A menu that has been walked already. vttest builds each level
        # out of the level below it, so the VT220 menu is a submenu of
        # the VT320 menu, which is a submenu of the VT420 menu. Walking
        # it once for each is the same screens three times over, and it
        # is most of the run. `PTTERM_VTTEST_INCLUDE` is how to walk one
        # of them again at the level it sits under.
        if key in self.walked and len(self.stack) > 1:
            self.again.append(self.path_of())
            self.leave()
            return

        while frame.next <= frame.largest:
            number = frame.next
            frame.next += 1
            name = self.name_of(frame, number)
            path = self.path_of(name)

            if not self.stack[:-1] and not self.include.search(name):
                self.narrowed.append(name)
                continue

            reason = self.excluded(path)
            if reason is not None:
                self.left_out.append((path, reason))
                continue

            frame.inside = name
            self.answer(str(number))
            return

        # Every item of this menu is done.
        self.walked.add(frame.key)
        self.leave()

    def leave(self) -> None:
        "Item 0 leaves a menu, and leaving the main menu ends vttest."
        self.stack.pop()
        if not self.stack:
            self.leaving = True
        self.answer("0")

    def name_of(self, frame: Frame, number: int) -> str:
        "How one item of a menu is written in a path."
        for entry, description in frame.entries:
            if entry == number:
                return "%d %s" % (number, description)
        # The menu holds more items than the page shows. The choice
        # still works, because it is a number and not a position.
        return "%d (not on this page)" % number


def keep(directory: Path, walk: Walk, log: Path) -> None:
    "Write the screens, and everything the walk found out."
    directory.mkdir(parents=True, exist_ok=True)

    head = [
        "# Every screen vttest drew against ptterm, and the menu path",
        "# that reached it. Lillecarl/pymux#46 says why this is a list to",
        "# read and not a gate: vttest draws, and a person looks.",
        "#",
        "# %d screens." % len(walk.screens),
        "#",
        "# An erased cell is written as a space. The second half of a wide",
        "# character is written as nothing, so a row is as wide as the",
        "# screen. A row that is drawn twice as big says so above the",
        "# picture, because every cell in one looks ordinary.",
        "",
    ]
    for path in walk.stuck:
        head.append("# No prompt came at: %s" % path)
    for path, reason in walk.left_out:
        head.append("# Left out: %s: %s" % (path, reason))
    for path in walk.again:
        head.append("# Walked already, so not walked again: %s" % path)

    (directory / "screens.txt").write_text(
        "\n".join(head) + "\n" + "\n".join(walk.screens) + "\n"
    )
    if log.exists():
        (directory / "vttest.log").write_text(log.read_text(errors="replace"))

    # The identity of every screen, in order. Two runs have to write
    # the same file, or the pictures of one cannot be lined up against
    # the pictures of the other.
    (directory / "paths.txt").write_text(
        "# Every screen this walk kept, in order, by the name it is\n"
        "# known by. Two runs must write this file identically.\n"
        "\n"
        + "".join(one + "\n" for one in walk.identities)
    )

    # Every menu, by the key that is supposed to tell it from the
    # others. A key with two paths under it is a key that does not.
    menus = ["# Every menu the walk met, by the key that names it.", ""]
    for (title, numbers), paths in walk.menus.items():
        menus.append("key: %s | %d items" % (" / ".join(title), len(numbers)))
        for path in sorted(set(paths)):
            menus.append("    %s" % (path or "(the main menu)"))
    (directory / "menus.txt").write_text("\n".join(menus) + "\n")


def report(walk: Walk, include: str) -> int:
    """
    Say what the walk did. Returns the exit status.

    This judges the walk and not the screens. A screen that is wrong is
    a finding for a person to make, and there is no recorded list to
    compare against yet. What fails here is a walk that did not happen:
    no screen at all, or an exclusion that names nothing.
    """
    print("vttest: %d screens, %d menu paths left out, %d without a prompt, "
          "%d menus met a second time"
          % (len(walk.screens), len(walk.left_out), len(walk.stuck),
             len(walk.again)))
    for path, reason in walk.left_out:
        print("vttest: left out %s: %s" % (path, reason))
    for path in walk.stuck:
        print("vttest: no prompt came at: %s" % path)
    if walk.narrowed:
        print("vttest: the include left out %d items of the main menu"
              % len(walk.narrowed))

    print("vttest: %d steps took %.1f seconds. The slowest ten:"
          % (len(walk.spent), sum(one for one, _ in walk.spent)))
    for seconds, path in sorted(walk.spent, reverse=True)[:10]:
        print("vttest:   %5.1fs  %s" % (seconds, path))
    for edge in (0.02, 0.05, 0.2, 1.0):
        over = [one for one, _ in walk.spent if one > edge]
        print("vttest:   %4d steps over %.2fs, %.1f seconds of the total"
              % (len(over), edge, sum(over)))

    if not walk.screens:
        print("vttest: the walk drew nothing at all")
        return 1

    # An exclusion that names nothing is stale. A narrowed walk chooses
    # too few items to say that, so it says nothing.
    if include == ".*":
        for pattern, _ in NOT_OURS:
            if not any(re.search(pattern, path) for path, _ in walk.left_out):
                print("vttest: NOT_OURS leaves out %r, and no menu item has "
                      "that name." % pattern)
                return 1

    return 0


async def drive(walk: Walk, command: list[str]) -> None:
    "Start vttest and walk it, with a budget for the whole run."
    walk.start(command)
    try:
        await asyncio.wait_for(walk.run(), RUN_TIMEOUT)
    except asyncio.TimeoutError:
        raise Failed("the walk did not end in %g seconds" % RUN_TIMEOUT)
    finally:
        assert walk.process is not None
        if not walk.ended:
            walk.process.kill()


def main() -> int:
    program = os.environ.get("PTTERM_VTTEST", "")
    if not program:
        print("vttest: PTTERM_VTTEST is not set, so there is nothing to run.")
        return 0

    if read_syscall_here() is None:
        # No fence, so the walk would have to guess when vttest has
        # finished drawing. Guessing costs a wait on every one of four
        # hundred screens and gets the answer wrong sometimes. A walk
        # that cannot be exact is not worth running.
        print("vttest: this machine has no /proc/<pid>/syscall, so there is "
              "no fence and the walk does not run.")
        return 0

    include = os.environ.get("PTTERM_VTTEST_INCLUDE", ".*")
    out = os.environ.get("PTTERM_VTTEST_OUT", "")

    log = Path(os.environ.get("TMPDIR", "/tmp")) / "vttest.log"
    command = [program, "-l", str(log)]
    command += shlex.split(os.environ.get("PTTERM_VTTEST_ARGS", ""))

    os.environ["TERM"] = "xterm-256color"
    os.environ["LANG"] = "C.UTF-8"

    walk = Walk(include, through=os.environ.get("PTTERM_VTTEST_THROUGH") == "1")
    if walk.through:
        # Everything this program says now goes to stderr. Its stdout
        # belongs to vttest, and a word of ours on that screen would be
        # a word in the picture.
        sys.stdout = sys.stderr
    failed = None
    try:
        asyncio.run(drive(walk, command))
    except Failed as error:
        # A walk that stopped early still drew the screens up to where
        # it stopped, and it still knows where its time went. Say both,
        # and fail afterwards.
        failed = error

    # Keep what the walk drew before judging it.
    if out:
        keep(Path(out), walk, log)

    status = report(walk, include)
    if failed is not None:
        print("vttest: %s" % failed)
        return 1
    return status


if __name__ == "__main__":
    sys.exit(main())
