"""
Run esctest2 against ptterm on a pty of its own, and compare the result
with a recorded list.

esctest2 is the conformance suite that Thomas Dickey maintains, after
George Nachman wrote it for iTerm2. It judges a terminal from the
inside: it runs as a program in that terminal, writes control sequences
and reads the reports that come back. Nothing in it knows what ptterm
is.

So ptterm is the terminal on trial, and this file is the terminal
program around it. There is no prompt_toolkit application, no layout
and no client. A `Process` on a `PosixBackend` is the whole host: it
opens a pty, forks the suite onto it, feeds what comes back into a
`BetterScreen` through a `BetterStream`, and writes every answer of
that screen to the pty. That is what a pane is, without the pane.

The suite reads the screen with DECRQCRA, one cell at a time. That is
the instrument. Without an answer to it, no test that looks at the
screen can say anything at all.

**This host answers a resize.** A program asks for one with DECSLPP,
DECCOLM or XTWINOPS, and ptterm passes the ask to whoever embeds it,
because a pane cannot take room from its neighbours. A terminal that
owns its pty can, so this one does. It is the largest difference
between this list and the one that `pymux/tests/esctest-failures.txt`
holds, and it is the point of running the suite twice: what fails here
is ptterm, and what fails there and not here is what pymux puts around
it.

Run it:

    nix build --file . checks.ptterm-esctest

Narrow it to one class while hunting one failure. A narrowed run is
judged too: a name in the list that the regular expression does not
choose was never going to run, so it does not count as missing.

    PTTERM_ESCTEST_INCLUDE=BSTests nix build --file . checks.ptterm-esctest

Every run writes the list it saw and the log that says why, whatever
the verdict, because the run of a check does not fail when the suite
fails. So reading the reasons and writing the list again are the same
command:

    nix build --file . checks.ptterm-esctest.run
    less result/esctest.log
    cp result/failures.txt ptterm/tests/esctest-failures.txt

Three variables reach this file from `ptterm/nix/checks.nix`:
`PTTERM_ESCTEST` names the directory that holds `esctest.py`, and the
check does nothing when it is not set. `PTTERM_ESCTEST_INCLUDE` is the
regular expression of test names to run. `PTTERM_ESCTEST_OUT` names the
directory to write the list and the log into.
"""
import asyncio
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from ptterm.backends.posix import PosixBackend
from ptterm.process import Process

HERE = Path(__file__).parent

#: The tests that fail today, one name per line.
BASELINE = HERE / "esctest-failures.txt"

#: The screen the suite asks for in its own reset, before every test.
#: This host answers that ask, so the size only decides what the first
#: test before the first reset sees.
ROWS, COLUMNS = 25, 80

#: The sizes this host will take. A resize comes from the program on
#: trial, and a suite that asks for a screen of a million rows should
#: get a refusal and not a dead machine.
SMALLEST, LARGEST = 1, 500

#: How long a report may take before the suite gives up on it, in
#: seconds. A sequence that goes unanswered costs this much every time
#: a test asks for it.
REPORT_TIMEOUT = "2"

#: How long the whole run may take.
RUN_TIMEOUT = 900.0

#: How often the driver looks at the run. The loop has to turn for the
#: reader to read at all, and `PosixBackend` reports the end of the
#: child from a thread, with a call that does not wake a loop that
#: sleeps. So the loop is never allowed to sleep for long.
TICK = 0.02

#: The program on the pty. It runs the suite and exits.
#:
#: It drives the suite test by test instead of letting it run itself,
#: for one reason. A test that reads fewer reports than the terminal
#: sends leaves the rest in the pipe, and every read after that is one
#: report behind. One deviation early on then decides the result of
#: every test after it. Throwing away what is left over before each
#: test keeps every verdict about that test alone.
RUNNER = '''
import os, select, sys, tty

# Nobody reads this screen after the run, and a traceback drawn on it
# goes away with the process. Put it where the check can find it.
sys.stderr = open(os.environ["ESCTEST_LOG"] + ".stderr", "w", buffering=1)

sys.path.insert(0, os.environ["ESCTEST_DIR"])
os.chdir(os.environ["ESCTEST_DIR"])

# esctest.py runs itself when it is imported: the last line of the file
# calls main(). So the import is the run, and the arguments have to be
# in place before it. "^$" matches no test, which makes that run empty
# and leaves the suite set up and ready to be driven.
sys.argv = ["esctest.py",
            "--expected-terminal=xterm",
            # Which xterm ptterm answers as, where the two differ.
            # xterm 383 split reverse wraparound in two: "?45" now
            # goes back only over a line that was reached by wrapping,
            # and "?1045" carries the old behaviour that went back
            # over any line. ptterm follows the split, so the suite has
            # to ask for the later reading.
            "--xterm-reverse-wrap=383",
            # This host answers a resize, so it has the window
            # operations of xterm. Without the option the suite
            # expects them to be off, and a test that then passes is
            # reported as a failure of its own.
            "--options", "xtermWinopsEnabled",
            "--no-print-logs",
            "--logfile=" + os.environ["ESCTEST_LOG"],
            "--timeout=" + os.environ["ESCTEST_TIMEOUT"],
            "--include=^$"]

import escargs, escio, esclog, esctest

if escio.stdin_fd is None:
    # The import ran nothing, so the file has grown a main guard since.
    esctest.init()

# That empty run ended with a shutdown, which takes the terminal out of
# raw mode. And now the real selection of tests.
tty.setraw(escio.stdin_fd)
escargs.args.include = os.environ["ESCTEST_INCLUDE"]


def drain():
    "Throw away every report that the test before this one left."
    while select.select([0], [], [], 0.05)[0]:
        if not os.read(0, 65536):
            break


passed = failed = known = 0
try:
    for name, method in esctest.MatchingNamesAndMethods():
        drain()
        status = esctest.RunTest(name, method)
        if status is None:
            known += 1
        elif status:
            passed += 1
        else:
            failed += 1
    esclog.LogInfo("*** %d passed, %d known bugs, %d failed ***"
                   % (passed, known, failed))
finally:
    escio.Shutdown()
'''


class Failed(AssertionError):
    pass


def read_baseline():
    "The tests that are known to fail, as a set of names."
    names = set()
    for line in BASELINE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line)
    return names


def keep(directory: Path, failed, log: str) -> None:
    """
    Keep the list of failures and the log that says why.

    Every run writes both, whatever the verdict. The log matters as much
    as the list: a run happens in the build sandbox, and the names alone
    do not say what the screen did wrong.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "failures.txt").write_text(
        "# The esctest2 tests that failed in this run. Every name here is a\n"
        "# real difference between ptterm and xterm.\n"
        "#\n"
        "# This is what the run saw. To make it what the check expects:\n"
        "#     nix build --file . checks.ptterm-esctest.run\n"
        "#     cp result/failures.txt ptterm/tests/esctest-failures.txt\n"
        + "".join(name + "\n" for name in sorted(failed))
    )
    (directory / "esctest.log").write_text(log)


def failures_in(log: str):
    """
    The tests that failed, as a set of names.

    The suite writes one line per failure while it runs. Those are read
    rather than the list it prints at the end, because a run that dies
    halfway still wrote them.
    """
    return set(re.findall(r"^\*\*\* TEST (\S+) FAILED:", log, re.MULTILINE))


def tests_that_ran(log: str):
    "Every test the suite started, as a set of names."
    return set(re.findall(r"^Run test: (\S+)$", log, re.MULTILINE))


async def drive(runner: Path) -> None:
    """
    Run the suite on a pty, with ptterm as the terminal on the other
    side of it.

    The backend and the process are made here and not before, because
    both take the loop that is running.
    """
    ended = False

    def done() -> None:
        nonlocal ended
        ended = True

    def resize(lines, columns) -> None:
        """
        Take the size the program asks for.

        ptterm hands the ask on rather than answering it, because a pane
        cannot take room from the panes beside it. This host owns the
        pty, so it can. A side the program leaves alone arrives as None
        and keeps the size it has.
        """
        width = process.sx if columns is None else columns
        height = process.sy if lines is None else lines
        if not SMALLEST <= width <= LARGEST or not SMALLEST <= height <= LARGEST:
            return
        process.set_size(width, height)

    backend = PosixBackend.from_command([sys.executable, str(runner)])
    process = Process(
        invalidate=lambda: None,
        backend=backend,
        done_callback=done,
        resize_func=resize,
    )

    # What `Process.start` does, with a size of our own. It sets 120 by
    # 24, and the child reads the size of the pty before the first
    # sequence reaches this side.
    process.set_size(COLUMNS, ROWS)
    backend.start()
    backend.connect_reader()

    # The loop has to keep turning: it is what reads the pty, and the
    # end of the child is reported by a call that does not wake it.
    deadline = time.monotonic() + RUN_TIMEOUT
    while not ended:
        if time.monotonic() > deadline:
            backend.kill()
            raise Failed("the suite did not end in %g seconds" % RUN_TIMEOUT)
        await asyncio.sleep(TICK)


def run(tmp: Path, directory: Path) -> str:
    "Run the suite against ptterm and return what it logged."
    runner = tmp / "esctest_runner.py"
    runner.write_text(RUNNER)

    log = tmp / "esctest.log"

    # The child inherits this environment through `execv`, so it is set
    # here and not passed.
    os.environ["ESCTEST_DIR"] = str(directory)
    os.environ["ESCTEST_LOG"] = str(log)
    os.environ["ESCTEST_TIMEOUT"] = REPORT_TIMEOUT
    os.environ["ESCTEST_INCLUDE"] = os.environ.get("PTTERM_ESCTEST_INCLUDE", ".*")
    os.environ["TERM"] = "xterm-256color"
    os.environ["LANG"] = "C.UTF-8"

    try:
        asyncio.run(drive(runner))
    except BaseException:
        stderr = Path(str(log) + ".stderr")
        if stderr.exists():
            print("--- what the suite wrote to stderr ---")
            print(stderr.read_text(errors="replace")[-4000:])
        if log.exists():
            print("--- the last of the esctest log ---")
            print(log.read_text(errors="replace")[-4000:])
        raise

    return log.read_text(errors="replace")


def report(log: str, include: str) -> int:
    """
    Compare the run with the recorded list. Returns the exit status.

    A difference in either direction is a failure, and the message says
    how to write the list again.

    `include` is the regular expression that chose which tests ran. A
    name in the list that it does not choose was never going to run, so
    it is not missing. Without that, every narrowed run would fail for
    every test it left out.
    """
    ran = tests_that_ran(log)
    failed = failures_in(log)
    known = read_baseline()
    chosen = {name for name in known if re.search(include, name)}

    print("esctest: %d tests ran, %d failed" % (len(ran), len(failed)))

    if not ran:
        print("esctest: the suite ran nothing at all")
        return 1

    new = sorted(failed - known)
    fixed = sorted((known & ran) - failed)
    missing = sorted(chosen - ran)

    for name in new:
        print("esctest: FAILS NOW, and did not before: " + name)
    for name in fixed:
        print("esctest: PASSES NOW, so the list is out of date: " + name)
    for name in missing:
        print("esctest: named in the list, but the suite never ran it: " + name)

    if new or fixed or missing:
        print(
            "\nesctest: %s no longer describes the run. Write it again with:\n"
            "    nix build --file . checks.ptterm-esctest.run\n"
            "    cp result/failures.txt ptterm/tests/%s\n"
            "and read result/esctest.log for what each one did."
            % (BASELINE.name, BASELINE.name)
        )
        return 1

    print("esctest: the run matches %s." % BASELINE.name)
    return 0


def main() -> int:
    directory = os.environ.get("PTTERM_ESCTEST", "")
    if not directory:
        print("esctest: PTTERM_ESCTEST is not set, so there is nothing to run.")
        return 0

    include = os.environ.get("PTTERM_ESCTEST_INCLUDE", ".*")

    tmp = Path(tempfile.mkdtemp(prefix="ptterm-esctest-"))
    log = run(tmp, Path(directory))

    # Keep the list and the log first, and judge afterwards. The run of
    # this check does not fail because the suite failed, so what it
    # leaves is there to read either way.
    out = os.environ.get("PTTERM_ESCTEST_OUT", "")
    if out:
        keep(Path(out), failures_in(log), log)

    return report(log, include)


if __name__ == "__main__":
    sys.exit(main())
