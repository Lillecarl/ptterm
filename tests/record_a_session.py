"""
Record what a real program writes to a terminal.

    python tests/record_a_session.py htop -- htop
    python tests/record_a_session.py vim --lines 24 --columns 80 -- vim README.md

The program runs on a pty of its own and everything passes through, so
the session looks normal. Three files come out:

- `<name>.bin`, what the program wrote. This is the corpus that the
  comparisons replay.
- `<name>.reads.json`, the size of every read. A pty hands over what it
  has when it has it, so a sequence reaches the terminal in one read or
  in three, and the screen has to be the same either way.
- `<name>.session.json`, both directions with a time on each piece.
  This is where a query and its answer sit next to each other: the
  program asks what the terminal can do, and what it draws afterwards
  depends on the answer. Reading a capture without it is guessing.

**A recording belongs to the terminal it was made on.** A program asks
what the terminal can do and draws what the answers allow, so the
bytes carry the answers of that terminal with them. `TERM` therefore
defaults to a plain one. Record under something exotic only when the
capture is meant to hold that.
"""
import argparse
import base64
import fcntl
import json
import os
import pathlib
import pty
import select
import shutil
import signal
import struct
import sys
import termios
import time
import tty

CORPUS = pathlib.Path(__file__).parent / "corpus"


def set_size(fd: int, lines: int, columns: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", lines, columns, 0, 0))


def record(name: str, command, lines: int, columns: int, term: str) -> None:
    CORPUS.mkdir(exist_ok=True)
    output = CORPUS / ("%s.bin" % name)
    reads = CORPUS / ("%s.reads.json" % name)
    session = CORPUS / ("%s.session.json" % name)

    child, master = pty.fork()
    if child == 0:
        os.environ["TERM"] = term
        os.environ["LINES"] = str(lines)
        os.environ["COLUMNS"] = str(columns)
        # A capture is worth nothing when the colours come from a
        # theme that nobody else has.
        os.environ.pop("COLORTERM", None)
        # A pager waits for a key that a recording of a program has
        # nobody to press.
        os.environ["PAGER"] = "cat"
        os.environ["GIT_PAGER"] = "cat"
        os.execvp(command[0], command)

    set_size(master, lines, columns)

    written = []
    sizes = []
    events = []
    started = time.monotonic()
    saved = None
    keyboard = sys.stdin.fileno()
    watching = [master, keyboard]
    if sys.stdin.isatty():
        saved = termios.tcgetattr(keyboard)
        tty.setraw(keyboard)

    try:
        while True:
            try:
                readable, _, _ = select.select(watching, [], [])
            except InterruptedError:
                continue

            if keyboard in readable:
                keys = os.read(keyboard, 4096)
                if keys:
                    os.write(master, keys)
                    events.append(
                        [
                            round(time.monotonic() - started, 6),
                            "in",
                            base64.b64encode(keys).decode("ascii"),
                        ]
                    )
                else:
                    # The end of the keyboard. Watching it further
                    # would spin, because select calls it readable and
                    # every read gives nothing.
                    watching.remove(keyboard)

            if master in readable:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                if not data:
                    break
                written.append(data)
                sizes.append(len(data))
                events.append(
                    [
                        round(time.monotonic() - started, 6),
                        "out",
                        base64.b64encode(data).decode("ascii"),
                    ]
                )
                os.write(sys.stdout.fileno(), data)
    finally:
        if saved is not None:
            termios.tcsetattr(keyboard, termios.TCSAFLUSH, saved)
        os.close(master)
        try:
            os.waitpid(child, 0)
        except ChildProcessError:
            pass

    output.write_bytes(b"".join(written))
    reads.write_text(json.dumps({"lines": lines, "columns": columns, "sizes": sizes}))
    session.write_text(
        json.dumps(
            {"lines": lines, "columns": columns, "term": term, "events": events}
        )
    )
    keys = sum(1 for event in events if event[1] == "in")
    print(
        "\r\n%s: %d bytes in %d reads, %d from the keyboard"
        % (output, sum(sizes), len(sizes), keys),
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="the name of the capture")
    parser.add_argument("--lines", type=int, default=24)
    parser.add_argument("--columns", type=int, default=80)
    parser.add_argument(
        "--term",
        default="xterm-256color",
        help="what the program is told the terminal is",
    )
    parser.add_argument("command", nargs="+", help="the program to run")
    arguments = parser.parse_args()

    command = arguments.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("no program to run")
    if shutil.which(command[0]) is None:
        parser.error("%s is not on the path" % command[0])

    record(arguments.name, command, arguments.lines, arguments.columns, arguments.term)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    main()
