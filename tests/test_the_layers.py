"""
Which module may import what.

**ptterm is one layer now: the prompt_toolkit front end.** Everything
under it belongs to another package, and getting there is the whole of
Lillecarl/pymux#11:

- `pyte` parses and holds the screen. That was `ptterm.screen` and
  eleven modules beside it, and it left so that a second front end can
  use it without taking prompt_toolkit on behind it.
- `ptyhost` runs the program on a pty. That was `ptterm.process` and
  `ptterm.backends`, and it left for the same reason (#85).
- `txterm` is this layer again, for Textual (#82). It has a copy of this
  file, and neither package may reach the other.

**This file is the boundary, and grep is not.** A single
`from prompt_toolkit import ...` back in the screen would put the split
where it started with nothing to say so. The import that breaks a layer
fails here instead. `pyte/tests/test_the_layers.py` is the other half:
it holds the pure layer to importing no toolkit at all.
"""
import ast
from pathlib import Path

import pytest

import ptterm

#: The package as it is installed, and not as it sits beside this file.
#: A check runs the tests against what it built.
PACKAGE = Path(ptterm.__file__).parent

#: What this package takes from the pure layer.
#:
#: Four modules, and `txterm` takes almost the same four. A front end
#: draws cells and sends keys, so what it needs is the screen, the
#: parser that feeds it, and the two tables that say what a cell holds.
PURE_LAYER = {
    "pyte.colors",
    "pyte.images",
    "pyte.placeholders",
    "pyte.screen",
    "pyte.streams",
}

#: The toolkit this package draws with, and the one it may never touch.
DRAWS_WITH = "prompt_toolkit"
NEVER = "textual"


def _name_of(path: Path) -> str:
    "The module name of one file, inside the package."
    relative = path.relative_to(PACKAGE).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "__init__"


def _modules():
    "Every module of the package, by name."
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        found[_name_of(path)] = path
    return found


MODULES = _modules()


def _imports(path: Path):
    """
    The outside modules that one file imports, by their full name.

    A relative import names something inside this package, and the rules
    here are about what comes from outside it.
    """
    outside = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                outside.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            outside.add(node.module or "")
    return outside


def _root(name: str) -> str:
    return name.split(".")[0]


@pytest.mark.parametrize("name", sorted(MODULES))
def test_nothing_imports_the_other_front_end(name):
    """
    The two widgets draw the same screen and never reach each other. A
    cell that carried one toolkit's spelling is what made a second front
    end impossible in the first place.
    """
    assert NEVER not in {_root(module) for module in _imports(MODULES[name])}


@pytest.mark.parametrize("name", sorted(MODULES))
def test_only_the_pure_layer_of_pyte_is_used(name):
    """
    A module of `pyte` that is not in `PURE_LAYER` is either something
    upstream left behind, or a piece of the screen that nobody wrote
    down here.
    """
    taken = {
        module for module in _imports(MODULES[name]) if _root(module) == "pyte"
    }
    assert taken <= PURE_LAYER, (
        "%s imports %s from pyte; add it to PURE_LAYER"
        % (name, sorted(taken - PURE_LAYER))
    )


def test_the_list_is_what_the_package_really_needs():
    """
    And the other way round: a name in the list that nothing imports is
    a name that says the front end is bigger than it is.

    This is also the guard on the reading. A reader that found no import
    anywhere would pass both tests above and say nothing at all.
    """
    taken = set()
    for path in MODULES.values():
        taken |= {
            module for module in _imports(path) if _root(module) == "pyte"
        }
    assert taken == PURE_LAYER


def test_the_widget_draws_with_prompt_toolkit():
    "The guard on the reading, from the other side."
    outside = {_root(module) for module in _imports(MODULES["terminal"])}
    assert DRAWS_WITH in outside


def test_only_the_widget_runs_a_program():
    """
    `ptyhost` is the package that starts a program on a pty, and
    `terminal.py` is the only thing here that reaches for it: it is the
    widget, so it is what starts the program and hands the bytes to a
    screen. Lillecarl/pymux#85.
    """
    reaching = sorted(
        name
        for name in MODULES
        if any(_root(module) == "ptyhost" for module in _imports(MODULES[name]))
    )
    assert reaching == ["terminal"]
