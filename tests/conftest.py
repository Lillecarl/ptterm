"""
Which group a test file belongs to, and why the groups exist.

The suite is one thing to a reader and three things to a build. About
forty of these files need nothing but python. Eighteen need the judge
panel, which means kitty, libvterm, a Rust build of two more emulators,
a C build against libghostty and a node tarball. One needs an X server
and the real Xlib.

Run as one derivation, a change to any test pays for all of it. So
`nix/checks.nix` runs three, and `PTTERM_GROUP` says which one this is:

    unit    nothing but python, and ncurses for the terminfo entry
    panel   the six emulators that ptterm is judged against
    xcms    Xvfb and libX11, for the colour specs

**A file is not listed anywhere.** A list would be forgotten the first
time somebody adds a test. The group comes from what the file imports:
a module that reads an oracle needs that oracle. So a new test lands in
the right group by writing the import it needs, and in `unit` when it
needs nothing.

**The decision is made on the text, not on the import.** pytest imports
every module it collects, before any mark can deselect it. In the unit
run there is no kitty and no node, so importing `panel` would fail.
`pytest_ignore_collect` runs before the import and reads the source.
"""
import os
import re
from pathlib import Path

#: The modules that speak to another terminal emulator.
PANEL_ORACLES = (
    "panel",
    "line_judge",
    "kitty_oracle",
    "vterm_oracle",
    "rust_oracle",
    "ghostty_oracle",
    "xterm_oracle",
)

#: The module that reads a colour with the real Xlib.
XCMS_ORACLES = ("xlib_oracle",)

#: Which group this run is. Empty means every group, which is what a
#: run outside the build does.
GROUP = os.environ.get("PTTERM_GROUP", "")

GROUPS = ("unit", "panel", "xcms")


def _imports(source: str, names) -> bool:
    "True when the source imports any of these modules by name."
    for name in names:
        if re.search(r"^\s*(?:from|import)\s+%s\b" % re.escape(name), source, re.M):
            return True
    return False


def group_of(path: Path) -> str:
    "The group that this test file belongs to."
    source = path.read_text(errors="replace")
    if _imports(source, XCMS_ORACLES):
        return "xcms"
    if _imports(source, PANEL_ORACLES):
        return "panel"
    return "unit"


def pytest_ignore_collect(collection_path, config):
    """
    Leave out the files that belong to another group.

    Returning `None` says nothing, which is what a run with no group
    set does: it collects everything, the way it always did.
    """
    if not GROUP:
        return None
    if GROUP not in GROUPS:
        raise ValueError(
            "PTTERM_GROUP is %r, and the groups are %s"
            % (GROUP, ", ".join(GROUPS))
        )
    if collection_path.suffix != ".py":
        return None
    if not collection_path.name.startswith("test_"):
        return None
    return group_of(collection_path) != GROUP
