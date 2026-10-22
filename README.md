# ptterm

> This repository is a copy. Work on ptterm happens in
> [pyterm](https://github.com/Lillecarl/pyterm), which exports its `ptterm/`
> directory here on every push. Send changes there, and issues to
> [Lillecarl/pymux](https://github.com/Lillecarl/pymux/issues).
> The docs are at <https://lillecarl.github.io/ptterm/>.

<!-- The lines above are pyterm's nix/shared/readme-head.md, written by sync-sources. -->

A terminal widget for [prompt_toolkit]. It runs a program on a pty and
draws what the program writes.

```python
import anyio
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout

from ptterm import Terminal


async def main():
    def done():
        application.exit()

    term = Terminal(done_callback=done)
    application = Application(layout=Layout(container=term), full_screen=True)
    async with anyio.create_task_group() as task_group:
        await term.start(task_group)
        await application.run_async()
        # The application is gone, and the program may not be: leaving
        # the scope waits for its tasks, so end them.
        task_group.cancel_scope.cancel()


anyio.run(main)
```

`examples/` holds more: two terminals side by side, a terminal in a
dialog, and one over SSH.

## What is in it

- `Terminal` — the widget. It owns a pyte screen and a ptyhost process,
  sizes both, draws the rows, and sends the keys.
- `style.py` — how prompt_toolkit spells a cell.

Everything else lives a layer down: the screen and the parser in
`pyte`, the pty in `ptyhost`. `tests/test_the_layers.py` names every
module of `pyte` this package imports.

## What judges it

The panel in `tests/panel.py` runs kitty, WezTerm, Alacritty, libvterm,
Ghostty and xterm.js on the same bytes, and the conformance suites
(esctest2, vttest and libvterm's) run against a real fork. A test here
judges how ptterm spells a cell, so the suites that read a cell back
through a widget live here and not in `pyte`.

## Thanks

- [pyte](https://github.com/selectel/pyte), for the VT100 emulator this
  started from.
- [Jonathan Slenders](https://github.com/jonathanslenders), who wrote
  prompt_toolkit and the first ptterm.

[prompt_toolkit]: https://github.com/prompt-toolkit/python-prompt-toolkit

<!-- The lines below are pyterm's nix/shared/readme-tail.md, written by sync-sources. -->

## Building

    nix build github:Lillecarl/ptterm    # from this repository alone
    nix build --file . ptterm            # in a checkout of pyterm

The suites that judge it run in pyterm, as `checks.ptterm-*`.

## The collection

ptterm is one source of [pyterm](https://github.com/Lillecarl/pyterm), and
each source claims one job:

| source | job |
| --- | --- |
| [pyte](https://lillecarl.github.io/pyte/) | parse, and hold a screen |
| [ptyhost](https://lillecarl.github.io/ptyhost/) | run a program on a pty, and carry its bytes |
| [ptterm](https://lillecarl.github.io/ptterm/) | draw one terminal, with prompt-toolkit |
| [txterm](https://lillecarl.github.io/txterm/) | draw one terminal, with Textual |
| [pymux](https://lillecarl.github.io/pymux/) | arrange several of them |
| [pysmithay](https://lillecarl.github.io/pysmithay/) | a headless Wayland compositor, for a GUI program in a pane |
| [pyterm-pytest](https://lillecarl.github.io/pyterm-pytest/) | the test equipment the suites share |
| [deferimport](https://lillecarl.github.io/deferimport/) | make imports lazy, without a keyword |
| [ptkhx](https://lillecarl.github.io/ptkhx/) | Helix's modal editing, for a prompt_toolkit buffer |

[pyterm's site](https://lillecarl.github.io/pyterm/) holds every source's
docs.
