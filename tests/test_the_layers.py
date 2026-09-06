"""
Which module may import what.

ptterm is three layers, and nothing but a habit kept them apart.
Lillecarl/pymux#11 holds the split, #82 the second front end that
proves it, and #85 the pty layer that has no home yet.

1. **Pure.** The parser, the screen, the colours, the images. No I/O
   and no toolkit. This is what belongs in `pyte`.
2. **The pty.** Runs a program, sizes it, pumps its bytes, records
   them. I/O, and no toolkit. This is `ptyhost` (#85).
3. **The front end.** The prompt_toolkit widget, and the key table it
   needs. `txterm` is the same layer for Textual (#82).

A layer may reach the layers under it and never the ones above.

**This file is the boundary, and grep is not.** Every count in those
issues was a grep somebody ran once, and a single `from prompt_toolkit
import ...` in `screen.py` would put it back where it started with
nothing to say so. The import that breaks a layer fails here instead.
"""
import ast
from pathlib import Path

import pytest

import ptterm

#: The package as it is installed, and not as it sits beside this file.
#: A check runs the tests against what it built.
PACKAGE = Path(ptterm.__file__).parent

#: No I/O and no toolkit. `pyte` is where this goes.
PURE = {
    "cache",
    "colors",
    "graphics",
    "kitty_keys",
    "osc",
    "placeholders",
    "png",
    "screen",
    "sixel",
    "stream",
    "terminfo",
    "xcms",
}

#: Runs a program on a pty. I/O, and no toolkit.
PTY = {
    "process",
    "record",
    "utils",
    "backends",
    "backends.asyncssh",
    "backends.base",
    "backends.darwin",
    "backends.posix",
    "backends.posix_utils",
    "backends.win32",
    "backends.win32_pipes",
}

#: Draws with prompt_toolkit, and turns its keys into bytes.
FRONT_END = {"key_mappings", "style", "terminal"}

#: What the pure layer may take from outside. Data, arithmetic and
#: tables, and the parser that `pyte` already holds.
#:
#: `sys` is here for `sys.maxsize` and `sys.platform`, which say
#: nothing about a file.
PURE_MAY_IMPORT = {
    "array",
    "base64",
    "collections",
    "colorsys",
    "enum",
    "functools",
    "math",
    "re",
    "string",
    "struct",
    "sys",
    "typing",
    "zlib",
    "pyte",
    "wcwidth",
}

#: The toolkits. A layer that may not draw may not import one, and the
#: two front ends may never import each other's.
TOOLKITS = {"prompt_toolkit", "textual", "rich"}


def _name_of(path: Path) -> str:
    "The module name of one file, inside the package."
    relative = path.relative_to(PACKAGE).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _modules():
    "Every module of the package, by name."
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        name = _name_of(path)
        if name:
            found[name] = path
    return found


MODULES = _modules()


def _imports(path: Path):
    """
    What one module imports: the outside packages by their first name,
    and the modules of this package by their own name.

    A relative import counts from the module that writes it, so
    "from .colors import" inside "backends/posix.py" is "backends" and
    not "colors". Nothing here does that, and the arithmetic is the
    same either way.
    """
    outside = set()
    inside = set()
    tree = ast.parse(path.read_text())
    package = _name_of(path).rsplit(".", 1)[0] if "." in _name_of(path) else ""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                outside.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if not node.level:
                outside.add((node.module or "").split(".")[0])
                continue
            # A relative import. One dot is the package this module is
            # in, two is the one above it.
            here = package.split(".") if package else []
            up = node.level - 1
            base = here[: len(here) - up] if up else here
            if node.module:
                # "from .backends import Backend" names the package,
                # and "from ..graphics import X" names a module. Both
                # are in `MODULES` under that name.
                inside.add(".".join(base + [node.module]))
            else:
                # "from . import kitty_keys" names one module per
                # alias.
                for alias in node.names:
                    inside.add(".".join(base + [alias.name]))
    return outside, inside


def _layer_of(name: str) -> str:
    if name in PURE:
        return "pure"
    if name in PTY:
        return "pty"
    if name in FRONT_END:
        return "front end"
    return "unplaced"


def test_every_module_has_a_layer():
    """
    A new module has to say which layer it is in, here, before anything
    else can hold it to a rule.
    """
    unplaced = sorted(
        name for name in MODULES if name and _layer_of(name) == "unplaced"
    )
    assert unplaced == [], (
        "these modules are in no layer: add each one to PURE, PTY or "
        "FRONT_END in this file"
    )


@pytest.mark.parametrize("name", sorted(PURE | PTY))
def test_only_a_front_end_imports_a_toolkit(name):
    "The whole point of the split. Lillecarl/pymux#82."
    outside, _inside = _imports(MODULES[name])
    assert not (outside & TOOLKITS)


def test_the_reading_sees_a_toolkit_where_there_is_one():
    """
    The test above says nothing unless this one passes: a reader that
    finds no import anywhere would pass every module.

    `terminal.py` is the prompt_toolkit widget, and `key_mappings.py`
    holds its key table. Both import it, and both should.
    """
    for name in ("terminal", "key_mappings"):
        outside, _inside = _imports(MODULES[name])
        assert "prompt_toolkit" in outside, name


def test_the_reading_sees_a_module_of_this_package():
    """
    And the same for the layer tests, which read the imports inside the
    package. `screen.py` reaches five modules under it.
    """
    _outside, inside = _imports(MODULES["screen"])
    assert {"cache", "colors", "kitty_keys"} <= inside


@pytest.mark.parametrize("name", sorted(PURE))
def test_the_pure_layer_does_no_input_or_output(name):
    """
    `pyte` is worth having on its own because it opens nothing and
    talks to nobody. A module that imports `os` has left that behind.
    """
    outside, _inside = _imports(MODULES[name])
    assert outside <= PURE_MAY_IMPORT, (
        "%s imports %s, which the pure layer may not"
        % (name, sorted(outside - PURE_MAY_IMPORT))
    )


@pytest.mark.parametrize("name", sorted(PURE))
def test_the_pure_layer_reaches_nothing_above_it(name):
    _outside, inside = _imports(MODULES[name])
    assert all(_layer_of(other) == "pure" for other in inside), (
        "%s imports %s" % (name, sorted(inside))
    )


@pytest.mark.parametrize("name", sorted(PTY))
def test_the_pty_layer_reaches_no_front_end(name):
    """
    `txterm` needs this layer, and it may not drag prompt_toolkit in
    behind it. Lillecarl/pymux#85.
    """
    _outside, inside = _imports(MODULES[name])
    above = sorted(other for other in inside if _layer_of(other) == "front end")
    assert above == [], "%s imports %s" % (name, above)
