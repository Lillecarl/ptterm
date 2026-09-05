"""
Run libvterm's own test suite against ptterm, and compare the result
with a recorded list.

libvterm is the emulator that Vim and Neovim carry. `ptterm-panel`
already uses it as a judge: the same bytes go into both and the two
screens are compared. This is the other direction. libvterm keeps 43
test files in `t/`, written in a plain text language, and `t/run-test.pl`
drives them against whatever program `--executable` names. So their
runner drives ours, and nothing in libvterm changes.

`vterm_harness.py` is that program: it speaks the protocol of
`t/harness.c` with ptterm behind it. This file runs the suite one test
file at a time and judges the result.

**A file is the unit that can be left out.** The runner compares the
lines a harness emits against the lines a file expects, in order. A
harness that stays quiet where libvterm reports `putglyph` fails; it
cannot skip. So a file that expects libvterm's callbacks is left out by
name before it runs, with the reason written down.

What is left is the state: 16 files and 274 assertions about where the
cursor is, what the screen holds and what style the next character
takes. That is what ptterm has.

Run it:

    nix build --file . checks.ptterm-vterm

Narrow it to one file while hunting one failure. A narrowed run is
judged too, and it makes no claim about the files it did not choose.

    PTTERM_VTERM_INCLUDE=movecursor nix build --file . checks.ptterm-vterm

Every run writes the list it saw and the log that says why, whatever the
verdict, because the run of a check does not fail when the suite fails:

    nix build --file . checks.ptterm-vterm.run
    less result/vterm.log
    cp result/failures.txt ptterm/tests/vterm-failures.txt

Three variables reach this file from `ptterm/nix/checks.nix`.
`PTTERM_VTERM` names the directory that holds `run-test.pl` and the test
files, and the check does nothing when it is not set.
`PTTERM_VTERM_INCLUDE` is the regular expression of file names to run.
`PTTERM_VTERM_OUT` names the directory to write the list and the log
into.
"""
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent

#: The program that answers libvterm's protocol with ptterm behind it.
HARNESS = HERE / "vterm_harness.py"

#: The assertions that fail today, one per line.
BASELINE = HERE / "vterm-failures.txt"

#: How long one test file may take, in seconds. The longest of them
#: pushes a hundred thousand characters through the screen and still
#: takes a few seconds, so this only catches a harness that hangs.
FILE_TIMEOUT = 120

#: The test files this terminal has no business running, and the reason
#: for each. A file whose name matches one of these is never run.
#:
#: Leaving a file out is not the same as recording its failures. A
#: recorded failure says "ptterm answers this differently from libvterm,
#: and DEVIATIONS.md says why". Leaving a file out says the question
#: does not apply to a terminal of this shape, so there is nothing to
#: record and nothing to decide.
#:
#: Two guards keep the list honest. A pattern that matches no file fails
#: the check, because an exclusion nobody can see is how a suite quietly
#: stops covering something. A file that is left out and also named in
#: the recorded list fails the check, because the two contradict each
#: other.
NOT_OURS = (
    (
        r"^(10state_putglyph|14state_encoding|16state_resize|20state_wrapping"
        r"|21state_tabstops|28state_dbl_wh|31state_rep)\.test$",
        "libvterm reports every glyph it lays down, and the file is a "
        "list of those reports. ptterm writes into a screen and the "
        "embedder reads the screen, so there is no glyph to report.",
    ),
    (
        r"^(12state_scroll|13state_edit|15state_mode|27state_reset"
        r"|60screen_ascii|62screen_damage|63screen_resize"
        r"|69screen_sb_clear)\.test$",
        "the file says how libvterm chose to redraw: which rectangle it "
        "damaged, scrolled or moved, and which line it pushed into the "
        "scrollback. ptterm has no redraw to report, and none of it is a "
        "property of the screen that a program can read.",
    ),
    (
        r"^(02parser|29state_fallback)\.test$",
        "the file reads the parser, not the terminal: each CSI, OSC, DCS "
        "and string sequence as libvterm hands it to an embedder. pyte "
        "parses for ptterm and reports nothing, so this needs a second "
        "harness on the parser. It is worth having later.",
    ),
    (
        r"^03encoding_utf8\.test$",
        "the file reads libvterm's own encoder, which turns key presses "
        "into bytes. ptterm has no such thing: prompt_toolkit encodes "
        "the keys of a pane.",
    ),
    (
        r"^(17state_mouse|18state_termprops|22state_save|25state_input"
        r"|26state_query|64screen_pen|68screen_termprops"
        r"|92lp1640917)\.test$",
        "the file reads what libvterm writes back to the program and "
        "which terminal properties it changed. ptterm does write "
        "replies, so a later harness could report them; it reports "
        "nothing today.",
    ),
    (
        r"^40state_selection\.test$",
        "the file reads the clipboard of libvterm. ptterm hands a "
        "selection sequence to whoever embeds it and keeps no clipboard "
        "of its own. DEVIATIONS.md entry 19.",
    ),
)


class Failed(AssertionError):
    pass


def read_baseline() -> Counter:
    """
    The assertions that are known to fail, counted.

    A count and not a set: `$SEQ` and `$REP` turn one line of a test
    file into many assertions, and every one of them reports the same
    line number. A set would hide a fix that mends nine of ten.
    """
    found: Counter = Counter()
    for line in BASELINE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            found[line] += 1
    return found


def test_files(directory: Path):
    "Every test file libvterm ships, by name, in a stable order."
    return sorted(path.name for path in directory.glob("*.test"))


def left_out(name: str) -> bool:
    "True when `NOT_OURS` keeps this file from running."
    return any(re.search(pattern, name) for pattern, _ in NOT_OURS)


def run_one(directory: Path, name: str):
    """
    Run one test file and return what the runner printed.

    The runner starts the harness itself and talks to it over a pipe.
    `-e` takes one string, so the interpreter and the file go in
    together and perl hands the pair to a shell.
    """
    command = [
        "perl",
        str(directory / "run-test.pl"),
        "-e",
        "%s %s" % (sys.executable, HARNESS),
        str(directory / name),
    ]
    try:
        done = subprocess.run(
            command,
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=FILE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise Failed("%s did not end in %d seconds" % (name, FILE_TIMEOUT))
    return done.stdout, done.stderr


#: What the runner prints for an assertion whose answer was wrong. The
#: name carries its arguments, so two assertions on the same line of the
#: same file are told apart.
_ASSERT = re.compile(r"^# line (\d+): Assert (.+) failed:$", re.MULTILINE)

#: What it prints when the lines a harness emitted are not the lines the
#: file expected. Every file that reaches this driver expects none, so
#: one of these is a fault in the harness and not a deviation.
_EMITTED = re.compile(r"^# line (\d+): Test failed$", re.MULTILINE)

#: What python writes when the harness raises. The runner writes to the
#: same stream, and its own warnings about the test language are not a
#: fault of ours.
_RAISED = "Traceback (most recent call last)"


def failures_in(name: str, output: str) -> Counter:
    "The assertions of one file that failed, counted."
    found: Counter = Counter()
    for line, assertion in _ASSERT.findall(output):
        found["%s:%s %s" % (name, line, assertion)] += 1
    return found


def keep(directory: Path, failed: Counter, log: str) -> None:
    """
    Keep the list of failures and the log that says why.

    Every run writes both, whatever the verdict. The log matters as much
    as the list: a run happens in the build sandbox, and a name alone
    does not say what the answer was.
    """
    directory.mkdir(parents=True, exist_ok=True)
    lines = []
    for name in sorted(failed):
        lines.extend([name] * failed[name])
    (directory / "failures.txt").write_text(
        "# The libvterm assertions that failed in this run. Each line names\n"
        "# the test file, the line in it, and the assertion, and each one is\n"
        "# a real difference between ptterm and libvterm.\n"
        "#\n"
        "# A line can appear more than once: \"$SEQ\" and \"$REP\" in a test\n"
        "# file turn one line into many assertions.\n"
        "#\n"
        "# This is what the run saw. To make it what the check expects:\n"
        "#     nix build --file . checks.ptterm-vterm.run\n"
        "#     cp result/failures.txt ptterm/tests/vterm-failures.txt\n"
        + "".join(line + "\n" for line in lines)
    )
    (directory / "vterm.log").write_text(log)


def report(failed: Counter, ran, include: str) -> int:
    """
    Compare the run with the recorded list. Returns the exit status.

    A difference in either direction is a failure, and the message says
    how to write the list again.

    `include` is the regular expression that chose which files ran. An
    entry for a file it did not choose was never going to run, so it is
    not missing. Without that, every narrowed run would fail for every
    file it left out.
    """
    known = read_baseline()
    chosen = Counter(
        {
            entry: count
            for entry, count in known.items()
            if re.search(include, entry.split(":")[0])
        }
    )

    new = sorted((failed - chosen).elements())
    fixed = sorted((chosen - failed).elements())

    for entry in new:
        print("vterm: FAILS NOW, and did not before: " + entry)
    for entry in fixed:
        print("vterm: PASSES NOW, so the list is out of date: " + entry)

    if new or fixed:
        print(
            "\nvterm: %s no longer describes the run. Write it again with:\n"
            "    nix build --file . checks.ptterm-vterm.run\n"
            "    cp result/failures.txt ptterm/tests/%s\n"
            "and read result/vterm.log for what each answer was."
            % (BASELINE.name, BASELINE.name)
        )
        return 1

    print("vterm: the run matches %s." % BASELINE.name)
    return 0


def check_the_exclusions(names, include: str) -> int:
    """
    Say whether `NOT_OURS` still describes the suite.

    A narrowed run chooses too few files to say, so it says nothing.
    """
    if include != ".*":
        return 0

    status = 0
    known = read_baseline()
    out = [name for name in names if left_out(name)]

    for pattern, reason in NOT_OURS:
        matched = sorted(name for name in names if re.search(pattern, name))
        print("vterm: left out %s," % (", ".join(matched) or "nothing"))
        print("vterm:     because %s" % reason)
        if not matched:
            print("vterm: NOT_OURS leaves out %r, and no file has that name."
                  % pattern)
            status = 1

    both = sorted({entry.split(":")[0] for entry in known} & set(out))
    for name in both:
        print("vterm: left out, and named in the list as well: " + name)
        status = 1

    if status:
        print("\nvterm: NOT_OURS in %s no longer describes the suite."
              % Path(__file__).name)
    return status


def main() -> int:
    directory = os.environ.get("PTTERM_VTERM", "")
    if not directory:
        print("vterm: PTTERM_VTERM is not set, so there is nothing to run.")
        return 0

    suite = Path(directory)
    include = os.environ.get("PTTERM_VTERM_INCLUDE", ".*")

    names = test_files(suite)
    if not names:
        raise Failed("no test file in %s" % suite)

    failed: Counter = Counter()
    ran = []
    pieces = []
    broken = []

    for name in names:
        if left_out(name) or not re.search(include, name):
            continue
        output, errors = run_one(suite, name)
        ran.append(name)
        failed += failures_in(name, output)
        pieces.append("=== %s ===\n%s" % (name, output))
        if errors.strip():
            # The harness and the runner share this stream. A traceback
            # is the harness: it answers the line anyway, so the file
            # finishes and the log holds the reason. Everything else is
            # perl warning about the test language, which says nothing
            # about ptterm.
            pieces.append("--- what the run wrote to stderr ---\n" + errors)
            if _RAISED in errors:
                broken.append(name)
        if _EMITTED.search(output):
            broken.append(name)

    log = "\n".join(pieces)

    # Keep the list and the log first, and judge afterwards. The run of
    # this check does not fail because the suite failed, so what it
    # leaves is there to read either way.
    out = os.environ.get("PTTERM_VTERM_OUT", "")
    if out:
        keep(Path(out), failed, log)

    total = sum(failed.values())
    print("vterm: %d files ran, %d assertions failed" % (len(ran), total))

    if not ran:
        print("vterm: no file ran at all")
        return 1

    status = check_the_exclusions(names, include)

    for name in sorted(set(broken)):
        print("vterm: %s expected lines the harness cannot emit, or the "
              "harness raised. Read the log: this is a fault here and not "
              "a deviation." % name)
        status = 1

    return report(failed, ran, include) or status


if __name__ == "__main__":
    sys.exit(main())
