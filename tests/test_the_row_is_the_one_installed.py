"""
The widget, and the copy mode over it, hold the row that is installed.

`checks.ptterm-rs-unit` runs this suite with `pyte_rs.install()` in
`conftest.py`, and a green run there says something only if the widget
really held Rust rows. Without `PYTE_RS` it holds the dict. pyte has the
same test for its own suite. Lillecarl/pymux#470.
"""

from __future__ import annotations

import os

from no_backend import NoBackend

from ptterm.terminal import Terminal


def test_a_copy_holds_the_row_that_is_installed():
    expected = "pyte_rs" if os.environ.get("PYTE_RS", "") not in ("", "0") else "pyte.page"
    terminal = Terminal(backend=NoBackend())
    control = terminal.terminal_control
    control.create_content(20, 4)
    control.stream.feed("".join("row %d\r\n" % number for number in range(10)))
    view = terminal.enter_copy_mode()

    assert {type(row).__module__ for row in control.screen.page.data_buffer.values()} == {expected}
    assert {type(row).__module__ for row in view.page.data_buffer.values()} == {expected}
