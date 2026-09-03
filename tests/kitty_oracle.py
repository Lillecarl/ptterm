"""
Compare the screen of ptterm against the screen of kitty.

kitty carries its terminal emulator as a python extension, so the same
bytes can go into both and the result can be compared cell by cell.
kitty is the terminal that pymux runs inside, which makes it the right
reference: what it shows is what the user sees outside pymux.

`PTTERM_KITTY` names the directory that holds the `kitty` package. The
tests skip when it is not set.
"""
import os
import sys
import unicodedata
from typing import List, NamedTuple, Optional, Tuple

from prompt_toolkit.output.vt100 import _256_colors as _256_colors_table

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream

__all__ = [
    "as_seen",
    "as_text",
    "Cell",
    "kitty_is_available",
    "ptterm_cells",
    "kitty_cells",
    "differences",
]

#: The names that prompt_toolkit gives the first sixteen colours.
ANSI_COLOR_NAMES = [
    "ansiblack",
    "ansired",
    "ansigreen",
    "ansiyellow",
    "ansiblue",
    "ansimagenta",
    "ansicyan",
    "ansigray",
    "ansibrightblack",
    "ansibrightred",
    "ansibrightgreen",
    "ansibrightyellow",
    "ansibrightblue",
    "ansibrightmagenta",
    "ansibrightcyan",
    "ansiwhite",
]

_INDEX_BY_ANSI_NAME = {name: index for index, name in enumerate(ANSI_COLOR_NAMES)}

#: The colour that every number of the palette stands for. This is the
#: table that ptterm resolves a number above fifteen with.
_256_COLORS = _256_colors_table.colors


class Cell(NamedTuple):
    "One cell of a screen, in a form that both sides can produce."
    char: str
    fg: Optional[Tuple]
    bg: Optional[Tuple]
    bold: bool
    italic: bool
    underline: bool
    reverse: bool


def kitty_is_available() -> bool:
    path = os.environ.get("PTTERM_KITTY")
    if not path:
        return False
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import kitty.fast_data_types  # noqa: F401
    except Exception:
        return False
    return True


def _color_of_style(style: str, prefix: str) -> Optional[Tuple]:
    """
    The colour that a prompt_toolkit style string names.

    `None` means the default colour. A name of the first sixteen gives
    `("index", n)`, and anything else gives `("rgb", r, g, b)`.
    """
    for part in style.split():
        if prefix and not part.startswith(prefix):
            continue
        if not prefix and ":" in part:
            continue
        value = part[len(prefix) :]
        if not value.startswith("#"):
            continue
        name = value[1:]
        if name in _INDEX_BY_ANSI_NAME:
            return ("index", _INDEX_BY_ANSI_NAME[name])
        if len(name) == 6:
            return ("rgb", int(name[0:2], 16), int(name[2:4], 16), int(name[4:6], 16))
    return None


def ptterm_cells(data: str, lines: int, columns: int) -> List[List[Cell]]:
    "Feed `data` to ptterm and read the screen back."
    screen = BetterScreen(lines, columns, write_process_input=lambda answer: None)
    stream = BetterStream(screen)
    stream.attach(screen)
    stream.feed(data)

    buffer = screen.pt_screen.data_buffer
    offset = screen.line_offset
    rows = []
    for y in range(offset, offset + lines):
        row = buffer[y]
        cells = []
        for x in range(columns):
            cell = row[x]
            style = cell.style
            char = cell.char
            cells.append(
                Cell(
                    char=" " if char == "" else char,
                    fg=_color_of_style(style, ""),
                    bg=_color_of_style(style, "bg:"),
                    bold="bold" in style,
                    italic="italic" in style,
                    underline="underline" in style,
                    reverse="reverse" in style,
                )
            )
        rows.append(cells)
    return rows


def _kitty_color(value: int) -> Optional[Tuple]:
    """
    The colour that kitty stores in a cell.

    kitty keeps the kind in the low byte: one for a number out of the
    palette, two for a colour of its own. Zero is the default.

    A number above fifteen becomes the colour it stands for. The style
    of prompt_toolkit can name the first sixteen, which a terminal
    paints from the theme of the user, but it has no way to carry a
    number of the cube. ptterm therefore resolves those itself, out of
    the same table that this uses.
    """
    kind = value & 0xFF
    if kind == 1:
        index = value >> 8
        if index < len(ANSI_COLOR_NAMES):
            return ("index", index)
        red, green, blue = _256_COLORS[index]
        return ("rgb", red, green, blue)
    if kind == 2:
        rgb = value >> 8
        return ("rgb", (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF)
    return None


def kitty_cells(data: str, lines: int, columns: int) -> List[List[Cell]]:
    "Feed `data` to kitty and read the screen back."
    from kitty.fast_data_types import Screen

    screen = Screen(None, lines, columns, 100, 10, 20, 0, None)
    raw = data.encode("utf-8")
    buffer = screen.test_create_write_buffer()
    screen.test_commit_write_buffer(raw, buffer)
    screen.test_parse_written_data()

    rows = []
    for y in range(lines):
        line = screen.line(y)
        texts = screen.cpu_cells(y)
        cells = []
        for x in range(columns):
            cursor = line.cursor_from(x)
            char = texts[x]["text"]
            if char.startswith("\t"):
                # kitty keeps a tab as a tab and paints a blank. ptterm
                # keeps the blank. Both show the same thing.
                char = " "
            cells.append(
                Cell(
                    char=" " if char in ("", "\0") else char,
                    fg=_kitty_color(cursor.fg),
                    bg=_kitty_color(cursor.bg),
                    bold=bool(cursor.bold),
                    italic=bool(cursor.italic),
                    underline=bool(cursor.decoration),
                    reverse=bool(cursor.reverse),
                )
            )
        _split_a_double_cell(cells)
        rows.append(cells)
    return rows


def _is_a_mark(char: str) -> bool:
    "A character of no width of its own, which shares the cell before it."
    return unicodedata.combining(char) != 0 or unicodedata.category(char) in (
        "Mn",
        "Me",
        "Cf",
    )


def _split_a_double_cell(row: List[Cell]) -> None:
    """
    Move a second character out of a cell that holds two.

    A cell holds one character and the marks that belong to it. kitty
    puts a second character of its own in there in one case, which
    `test_known_deviations` writes down. A reader sees two cells either
    way, so the comparison reads them as two.
    """
    for index in range(len(row) - 1):
        text = row[index].char
        if len(text) < 2:
            continue
        for position in range(1, len(text)):
            if _is_a_mark(text[position]):
                continue
            # kitty holds one cell fewer than it draws, so what follows
            # moves one cell to the right, up to the first blank. That
            # blank goes away and nothing is lost.
            blank = next(
                (
                    column
                    for column in range(index + 1, len(row))
                    if row[column].char == " "
                ),
                None,
            )
            if blank is None:
                break
            tail = row[index]._replace(char=text[position:])
            row[index] = row[index]._replace(char=text[:position])
            row[index + 1 : blank + 1] = [tail] + row[index + 1 : blank]
            break


def as_seen(cell: Cell) -> Cell:
    """
    The cell with everything dropped that a reader cannot see.

    A blank cell shows its background and nothing else, so the
    foreground and the weight of a blank do not matter. Reverse video
    and an underline do make a blank visible, so those cells keep
    everything.

    ptterm and kitty differ here on purpose: ptterm lets an erased cell
    go away, which keeps the screen sparse, while kitty keeps the
    colours of the moment on it. Both draw the same thing.
    """
    if cell.char == " " and not cell.reverse and not cell.underline:
        return cell._replace(fg=None, bold=False, italic=False)
    return cell


def as_text(cell: Cell) -> Cell:
    "Only the character of a blank cell, with every style dropped."
    if cell.char == " ":
        return Cell(" ", None, None, False, False, False, False)
    return cell


def differences(
    data: str,
    lines: int = 6,
    columns: int = 20,
    strict: bool = False,
    blank_style: bool = True,
) -> List[str]:
    """
    Every cell where ptterm and kitty do not agree, as readable lines.

    An empty answer means the two screens look the same. `strict` also
    reports a difference that nobody can see. `blank_style` off drops
    the style of a blank cell, which leaves the characters and where
    they sit; the hunt uses that, because the two sides disagree on
    purpose about the style that a new blank takes.
    """
    ours = ptterm_cells(data, lines, columns)
    theirs = kitty_cells(data, lines, columns)
    if strict:
        keep = lambda cell: cell  # noqa: E731
    elif blank_style:
        keep = as_seen
    else:
        keep = as_text

    reported = []
    for y in range(lines):
        for x in range(columns):
            mine, other = keep(ours[y][x]), keep(theirs[y][x])
            if mine == other:
                continue
            reported.append(
                "cell %d,%d: ptterm %r, kitty %r" % (y, x, mine, other)
            )
    return reported
