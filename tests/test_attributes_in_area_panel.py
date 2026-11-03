"""
What the panel does with DECCARA. Lillecarl/pymux#895.

kitty is the one judge that implements it, and it draws what ptterm
draws in every case here, blanks painted in a stream included. WezTerm,
Alacritty, libvterm, Ghostty and xterm.js leave the screen unchanged.
No judge has DECRARA, so xterm's source (`ScrnMarkRectangle`) is the
reference for it, and `pyte/tests/test_attributes_in_area.py` holds it.
"""

from __future__ import annotations

import pytest
from panel import report

ESC = "\x1b"
TEXT = "".join(ESC + "[%dH" % row + "abcdefgh" for row in range(1, 5))

CASES = {
    "stream bold": TEXT + ESC + "[2;6;3;2;1$r",
    "rectangle bold": TEXT + ESC + "[2*x" + ESC + "[2;3;3;5;1$r",
    "stream colour": TEXT + ESC + "[1;1;2;3;41;38;2;1;2;3$r",
    "blank background in a rectangle": ESC + "[2*x" + ESC + "[5;1;6;8;44$r",
    "blank background in a stream": ESC + "[5;1;6;8;44$r",
}


@pytest.mark.parametrize("name", CASES)
def test_kitty_draws_what_ptterm_draws(name):
    assert report(CASES[name], lines=6, columns=8, strict=True)["kitty"] == []
