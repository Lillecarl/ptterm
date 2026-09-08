"""
Compare the screen of ptterm against the screen of kitty.

kitty carries its terminal emulator as a python extension, so the same
bytes can go into both and the result can be compared cell by cell.
kitty is the terminal that pymux runs inside, which makes it the right
reference: what it shows is what the user sees outside pymux.

`PTTERM_KITTY` names the directory that holds the `kitty` package. The
tests skip when it is not set.
"""

import base64
import os
import re
import sys
import unicodedata
from typing import Dict, List, NamedTuple, Optional, Tuple

from prompt_toolkit.styles import palette_color_number

from pyte.screen import Screen
from pyte.streams import Stream
from ptterm.style import style_of

__all__ = [
    "as_seen",
    "as_text",
    "without_a_baseline",
    "Cell",
    "HISTORY",
    "kitty_is_available",
    "number_the_links",
    "ptterm_cells",
    "kitty_cells",
    "differences",
]

#: How many rows of history every judge keeps, ptterm included.
#:
#: A resize needs one. Widening a screen pulls rows back from history,
#: and a judge with none answers "blank" and agrees with every other
#: judge that has none, which is a tally about how the judges were built
#: and not about the emulators. So the number is the same everywhere and
#: it is written here.
#:
#: It is the number kitty was already built with. No probe comes near
#: it: a screen of eight rows that scrolls twice uses two.
HISTORY = 100

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


class Cell(NamedTuple):
    "One cell of a screen, in a form that both sides can produce."

    char: str
    fg: Optional[Tuple]
    bg: Optional[Tuple]
    bold: bool
    italic: bool
    #: The shape of the underline, as kitty numbers it: none, single,
    #: double, curly, dotted, dashed.
    underline: int
    reverse: bool
    #: The colour of the underline itself, or None for the colour of
    #: the text.
    underline_color: Optional[Tuple] = None
    #: The target of the link that this cell belongs to, or None. It is
    #: the text that the program wrote, so it compares as it stands.
    hyperlink: Optional[str] = None
    #: Which link this cell belongs to, as a number of this screen: 1
    #: for the first link the reader meets, 2 for the next.
    #:
    #: An emulator names a link its own way and no two of those names
    #: compare. What compares is the shape: which runs of cells are one
    #: link. `number_the_links` writes the numbers, as the last step of
    #: every reader. Until it runs the field holds the name that the
    #: emulator gave.
    hyperlink_id: Optional[int] = None
    #: Where the glyph sits, as libvterm numbers it: 0 on the baseline,
    #: 1 raised ("SGR 73"), 2 lowered ("SGR 74"). WezTerm numbers its
    #: own enum the same way.
    #:
    #: A judge that does not hold it answers 0, the way libvterm
    #: answers no hyperlink. The projection of such a judge drops the
    #: field, so a raised glyph makes it abstain rather than agree.
    baseline: int = 0


#: The word that a style string of prompt_toolkit gives each shape,
#: against the number that kitty gives it.
UNDERLINE_NUMBERS = {
    "underline": 1,
    "underdouble": 2,
    "undercurl": 3,
    "underdotted": 4,
    "underdashed": 5,
}


def _give_kitty_its_settings() -> None:
    """
    Hand kitty the settings that it ships with.

    kitty keeps one settings struct for the whole process, and a screen
    reads it. Nothing fills it in until somebody calls `set_options`, so
    a screen made without that call runs on a struct of zeros: every
    setting off, whatever the shipped value is.

    `allow_hyperlinks` is one of them, and it is on by default. With the
    struct of zeros kitty drops every "OSC 8", so it holds no link and
    cannot vote on one. The rest of the panel runs its emulator as it
    comes, so kitty runs as it comes too.
    """
    from kitty.fast_data_types import set_options
    from kitty.options.types import defaults

    set_options(defaults)


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
    global _settings_are_given
    if not _settings_are_given:
        _give_kitty_its_settings()
        _settings_are_given = True
    return True


#: The settings go in once. A second call would build them again for
#: nothing, and this runs before every comparison.
_settings_are_given = False


#: The pieces of style that carry a hyperlink: its target and its id.
#: Both are base64, which can hold the letters of a rendition, so they
#: go away before the style is read.
_HYPERLINK = re.compile(r"\[hyperlink(-id)?:([^\]]*)\]")


def _link_of_style(style: str) -> Tuple[Optional[str], str]:
    """
    The target of the link that a style string carries, and its name.

    ptterm writes the target and the id of the link into the style, each
    in base64. The two together are what ptterm calls one link: a
    program that opens the same target under a second id opens a second
    link.
    """
    target = None
    link_id = ""
    for is_id, value in _HYPERLINK.findall(style):
        text = base64.b64decode(value).decode("utf-8", "replace")
        if is_id:
            link_id = text
        else:
            target = text
    if target is None:
        return None, ""
    return target, "%s\x00%s" % (link_id, target)


def number_the_links(rows: List[List[Cell]]) -> List[List[Cell]]:
    """
    Turn the name that an emulator gives a link into a number.

    Every emulator names a link its own way. kitty numbers it out of a
    pool that it keeps, Alacritty mints a name from a counter of the
    process, WezTerm holds the target and the parameters, and ptterm
    carries the target and the id that the program wrote. No two of
    those compare, and Alacritty's is not even the same twice.

    What compares is the shape: which runs of cells are one link. So
    each distinct name of a screen becomes 1, 2, 3, in the order the
    reader meets it. Two judges then agree when they group the cells
    the same way.
    """
    numbers: Dict[str, int] = {}
    return [
        [
            cell
            if cell.hyperlink_id is None
            else cell._replace(
                hyperlink_id=numbers.setdefault(cell.hyperlink_id, len(numbers) + 1)
            )
            for cell in row
        ]
        for row in rows
    ]


def _color_of_style(style: str, prefix: str) -> Optional[Tuple]:
    """
    The colour that a prompt_toolkit style string names.

    `None` means the default colour. A number of the palette gives
    `("index", n)`, by one of the sixteen names or by a number, and a
    colour of its own gives `("rgb", r, g, b)`.
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
        number = palette_color_number(name)
        if number is not None:
            return ("index", number)
        if len(name) == 6:
            return ("rgb", int(name[0:2], 16), int(name[2:4], 16), int(name[4:6], 16))
    return None


def _underline_of_style(style: str) -> int:
    "The shape of the underline that a style string names."
    for part in style.split():
        number = UNDERLINE_NUMBERS.get(part)
        if number is not None:
            return number
    return 0


#: The word that a style string of prompt_toolkit gives each baseline,
#: against the number that libvterm gives it.
BASELINE_NUMBERS = {
    "superscript": 1,
    "subscript": 2,
}


def _baseline_of_style(style: str) -> int:
    "Where the glyph sits, as the style string names it."
    for part in style.split():
        number = BASELINE_NUMBERS.get(part)
        if number is not None:
            return number
    return 0


def ptterm_cells(
    data: str, lines: int, columns: int, resize: Optional[Tuple[int, int]] = None
) -> List[List[Cell]]:
    "Feed `data` to ptterm and read the screen back."
    return ptterm_cells_in_pieces([data], lines, columns, resize)


def ptterm_cells_in_pieces(
    pieces: List[str],
    lines: int,
    columns: int,
    resize: Optional[Tuple[int, int]] = None,
) -> List[List[Cell]]:
    """
    Feed ptterm one piece at a time, and read the screen back.

    A pty hands over what it has when it has it, so a sequence arrives
    in two reads as often as in one. The screen has to be the same
    either way.

    `resize` is a new size to take after the last piece. The screen that
    comes back is that size, and the rows it holds are what the reflow
    made of the ones before.
    """
    screen = Screen(
        lines,
        columns,
        write_process_input=lambda answer: None,
        get_history_limit=lambda: HISTORY,
    )
    stream = Stream(screen)
    for piece in pieces:
        stream.feed(piece)
    if resize is not None:
        lines, columns = resize
        screen.resize(lines, columns)

    buffer = screen.page.data_buffer
    offset = screen.line_offset
    rows = []
    for y in range(offset, offset + lines):
        row = buffer[y]
        cells = []
        for x in range(columns):
            cell = row[x]
            spelled = style_of(cell.appearance)
            target, name = _link_of_style(spelled)
            style = _HYPERLINK.sub("", spelled)
            char = cell.char
            cells.append(
                Cell(
                    char=" " if char == "" else char,
                    fg=_color_of_style(style, ""),
                    bg=_color_of_style(style, "bg:"),
                    bold="bold" in style,
                    italic="italic" in style,
                    underline=_underline_of_style(style),
                    reverse="reverse" in style,
                    underline_color=_color_of_style(style, "ul:"),
                    hyperlink=target,
                    hyperlink_id=name or None,
                    baseline=_baseline_of_style(style),
                )
            )
        rows.append(cells)
    return number_the_links(rows)


def _kitty_color(value: int) -> Optional[Tuple]:
    """
    The colour that kitty stores in a cell.

    kitty keeps the kind in the low byte: one for a number out of the
    palette, two for a colour of its own. Zero is the default.

    A number stays a number, at every value. The terminal of the user
    paints the palette from its own theme, so nothing here turns a
    number into red, green and blue.
    """
    kind = value & 0xFF
    if kind == 1:
        return ("index", value >> 8)
    if kind == 2:
        rgb = value >> 8
        return ("rgb", (rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF)
    return None


def kitty_cells(
    data: str, lines: int, columns: int, resize: Optional[Tuple[int, int]] = None
) -> List[List[Cell]]:
    "Feed `data` to kitty and read the screen back."
    from kitty.fast_data_types import Screen

    screen = Screen(None, lines, columns, HISTORY, 10, 20, 0, None)
    raw = data.encode("utf-8")
    buffer = screen.test_create_write_buffer()
    screen.test_commit_write_buffer(raw, buffer)
    screen.test_parse_written_data()
    if resize is not None:
        lines, columns = resize
        screen.resize(lines, columns)

    rows = []
    for y in range(lines):
        line = screen.line(y)
        texts = screen.cpu_cells(y)
        # kitty numbers a link out of a pool that it keeps, and the pool
        # is keyed on the id and the target together. Zero is no link.
        link_numbers = line.hyperlink_ids()
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
                    underline=int(cursor.decoration),
                    reverse=bool(cursor.reverse),
                    # kitty keeps the colour of a line that it does not
                    # draw. Nobody sees that, so it goes away.
                    underline_color=(
                        _kitty_color(cursor.decoration_fg)
                        if cursor.decoration
                        else None
                    ),
                    hyperlink=(screen.hyperlink_at(x, y) if link_numbers[x] else None),
                    hyperlink_id=str(link_numbers[x]) if link_numbers[x] else None,
                )
            )
        _split_a_double_cell(cells)
        rows.append(cells)
    return number_the_links(rows)


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
        return cell._replace(fg=None, bold=False, italic=False, baseline=0)
    return cell


def as_text(cell: Cell) -> Cell:
    "Only the character of a blank cell, with every style dropped."
    if cell.char == " ":
        return Cell(" ", None, None, False, False, 0, False, None, None, None)
    return cell


def without_a_baseline(cell: Cell) -> Cell:
    """
    The cell, with the baseline dropped.

    kitty and Alacritty have no "SGR 73", so every glyph of theirs sits
    on the line. An emulator that answered 0 with no projection would
    agree with a screen that raised a glyph, which is an answer it
    cannot give.

    It lives here and not in `panel.py` because both hunts need it. The
    panel hunt reads it through the projection of each judge; the hunt
    against kitty alone reads it through `differences`, which is right
    below. A drop that only one of them knows about makes the other
    fail at random. Lillecarl/pymux#105.
    """
    return cell._replace(baseline=0)


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

    The baseline goes in every case, `strict` included. kitty cannot
    hold one at all, so a raised glyph is not a difference it reports:
    it is a field it does not have.
    """
    ours = ptterm_cells(data, lines, columns)
    theirs = kitty_cells(data, lines, columns)
    if strict:
        keep = without_a_baseline
    elif blank_style:
        keep = lambda cell: without_a_baseline(as_seen(cell))  # noqa: E731
    else:
        keep = lambda cell: without_a_baseline(as_text(cell))  # noqa: E731

    reported = []
    for y in range(lines):
        for x in range(columns):
            mine, other = keep(ours[y][x]), keep(theirs[y][x])
            if mine == other:
                continue
            reported.append("cell %d,%d: ptterm %r, kitty %r" % (y, x, mine, other))
    return reported
