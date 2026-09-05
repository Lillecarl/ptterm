"""
A terminal draws what the program in it drew.

prompt_toolkit marks up the characters a person cannot otherwise see,
the way a text editor does. `Char` swaps the character for a stand-in
and attaches a style class: a non-breaking space becomes an underlined
yellow space, and a control character becomes "^@" in blue.

That is right for a prompt somebody is typing into. It is wrong for a
pane, because the program in the pane already decided what its screen
says, and nothing in a pane is a character the person is about to edit.

Claude Code is what found it. It writes "\\u276f\\u00a0Try ..." for its
prompt, and every cell of that non-breaking space came out of pymux
with an underline under it. `checks.pymux-pictures` measured five
pixels, in xterm and in foot alike.
"""
import pytest
from prompt_toolkit.layout.screen import Char

from ptterm.placeholders import PLACEHOLDER
from ptterm.terminal import _visible_char


def drawn(char):
    "The cell that a pane makes for this character: (char, style)."
    cell = Char(_visible_char(char), "", apply_display_mappings=False)
    return cell.char, cell.style


# ----------------------------------------------------------------------
# The non-breaking space.


def test_a_non_breaking_space_reaches_the_screen_as_itself():
    "The program wrote one on purpose. A terminal draws what it drew."
    assert drawn("\xa0") == ("\xa0", "")


def test_prompt_toolkit_would_change_it_without_the_flag():
    """
    What a pane used to draw: a plain space with `class:nbsp`, which is
    `underline ansiyellow` in the default style. Claude Code writes a
    non-breaking space after its prompt arrow, and every one of them
    came out of pymux underlined.
    """
    marked = Char("\xa0", "")
    assert marked.char == " "
    assert "nbsp" in marked.style


# ----------------------------------------------------------------------
# Every other character prompt_toolkit would mark.


@pytest.mark.parametrize("char", sorted(Char.display_mappings))
def test_no_character_reaches_the_screen_marked_up(char):
    assert "class:" not in drawn(char)[1]


@pytest.mark.parametrize(
    "char", sorted(set(Char.display_mappings) - {"\xa0"})
)
def test_a_control_character_is_drawn_as_a_blank(char):
    """
    It should never be in a cell: the parser consumes those. One that
    is there must not reach the terminal of the user, which would read
    it as a control of its own.
    """
    assert _visible_char(char) == " "


# ----------------------------------------------------------------------
# What still goes through.


@pytest.mark.parametrize(
    "char", [" ", "a", "❯", "─", "你", "é", "·", "\xa0"]
)
def test_an_ordinary_character_is_drawn_as_it_is(char):
    assert drawn(char) == (char, "")


def test_a_placeholder_still_becomes_a_blank():
    "The cell of an image. The embedder draws the image over it."
    assert _visible_char(PLACEHOLDER + "̅̅") == " "
