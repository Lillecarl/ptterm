"""
Compare the screen of ptterm against libvterm.

libvterm is the emulator that Vim and Neovim carry, and it draws the
terminal window of every editor that embeds them. It has no display of
its own, so the same bytes go into it and the cells come back out.

It is the second opinion. kitty is the terminal that pymux runs inside;
libvterm leans towards xterm. Where the two agree and ptterm differs,
ptterm is wrong and nobody has to decide anything. Where the two
disagree, the difference is a real choice, which is what
`test_known_deviations.py` holds.

`PTTERM_LIBVTERM` names the shared library. The tests skip when it is
not set.

The shape of a cell, and the readers that turn a screen into cells,
live in `kitty_oracle`. This adds one more reader.
"""
import ctypes
import os
from typing import List, Optional, Tuple

from kitty_oracle import (
    ANSI_COLOR_NAMES,
    Cell,
    _256_COLORS,
    as_seen,
    as_text,
    ptterm_cells,
)

__all__ = [
    "libvterm_is_available",
    "vterm_cells",
    "vterm_differences",
    "three_way",
]

#: How many code points libvterm keeps in one cell.
MAX_CHARS_PER_CELL = 6

#: The bits of `VTermColor.type`.
_COLOR_INDEXED = 0x01
_COLOR_DEFAULT_FG = 0x02
_COLOR_DEFAULT_BG = 0x04

#: What libvterm puts in the second half of a double width character.
_WIDE_CHARACTER_FILLER = 0xFFFFFFFF


class _Attrs(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint, width)
        for name, width in [
            ("bold", 1),
            ("underline", 2),
            ("italic", 1),
            ("blink", 1),
            ("reverse", 1),
            ("conceal", 1),
            ("strike", 1),
            ("font", 4),
            ("dwl", 1),
            ("dhl", 2),
            ("small", 1),
            ("baseline", 2),
        ]
    ]


class _Color(ctypes.Structure):
    "The tagged union of libvterm, read as its four bytes."
    _fields_ = [
        ("type", ctypes.c_uint8),
        ("first", ctypes.c_uint8),
        ("second", ctypes.c_uint8),
        ("third", ctypes.c_uint8),
    ]


class _Cell(ctypes.Structure):
    _fields_ = [
        ("chars", ctypes.c_uint32 * MAX_CHARS_PER_CELL),
        ("width", ctypes.c_char),
        ("attrs", _Attrs),
        ("fg", _Color),
        ("bg", _Color),
    ]


class _Pos(ctypes.Structure):
    _fields_ = [("row", ctypes.c_int), ("col", ctypes.c_int)]


_library = None


def libvterm_is_available() -> bool:
    "True when `PTTERM_LIBVTERM` names a library that loads."
    global _library
    if _library is not None:
        return True
    path = os.environ.get("PTTERM_LIBVTERM")
    if not path:
        return False
    try:
        library = ctypes.CDLL(path)
    except OSError:
        return False

    library.vterm_new.restype = ctypes.c_void_p
    library.vterm_new.argtypes = [ctypes.c_int, ctypes.c_int]
    library.vterm_free.argtypes = [ctypes.c_void_p]
    library.vterm_set_utf8.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.vterm_obtain_screen.restype = ctypes.c_void_p
    library.vterm_obtain_screen.argtypes = [ctypes.c_void_p]
    library.vterm_screen_reset.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.vterm_input_write.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    library.vterm_screen_get_cell.argtypes = [
        ctypes.c_void_p,
        _Pos,
        ctypes.POINTER(_Cell),
    ]
    _library = library
    return True


def _color(value: _Color, background: bool) -> Optional[Tuple]:
    """
    The colour that libvterm holds, in the form that `kitty_oracle`
    uses.

    `None` is the default colour. A number of the first sixteen keeps
    its number, because a terminal paints those from the theme of the
    user; anything above becomes the colour it stands for, the way
    ptterm resolves it.
    """
    default = _COLOR_DEFAULT_BG if background else _COLOR_DEFAULT_FG
    if value.type & default:
        return None
    if value.type & _COLOR_INDEXED:
        index = value.first
        if index < len(ANSI_COLOR_NAMES):
            return ("index", index)
        if index < len(_256_COLORS):
            red, green, blue = _256_COLORS[index]
            return ("rgb", red, green, blue)
        return None
    return ("rgb", value.first, value.second, value.third)


def vterm_cells(data: str, lines: int, columns: int) -> List[List[Cell]]:
    "Feed `data` to libvterm and read the screen back."
    assert libvterm_is_available(), "PTTERM_LIBVTERM names no library"
    library = _library

    term = library.vterm_new(lines, columns)
    try:
        library.vterm_set_utf8(term, 1)
        screen = library.vterm_obtain_screen(term)
        library.vterm_screen_reset(screen, 1)
        raw = data.encode("utf-8")
        library.vterm_input_write(term, raw, len(raw))

        rows = []
        for y in range(lines):
            cells = []
            for x in range(columns):
                cell = _Cell()
                library.vterm_screen_get_cell(screen, _Pos(y, x), ctypes.byref(cell))
                text = "".join(
                    chr(point)
                    for point in cell.chars
                    if point and point != _WIDE_CHARACTER_FILLER
                )
                cells.append(
                    Cell(
                        char=text or " ",
                        fg=_color(cell.fg, background=False),
                        bg=_color(cell.bg, background=True),
                        bold=bool(cell.attrs.bold),
                        italic=bool(cell.attrs.italic),
                        underline=bool(cell.attrs.underline),
                        reverse=bool(cell.attrs.reverse),
                    )
                )
            rows.append(cells)
        return rows
    finally:
        library.vterm_free(term)


def _keeper(strict: bool, blank_style: bool):
    if strict:
        return lambda cell: cell
    return as_seen if blank_style else as_text


def vterm_differences(
    data: str,
    lines: int = 6,
    columns: int = 20,
    strict: bool = False,
    blank_style: bool = True,
) -> List[str]:
    "Every cell where ptterm and libvterm do not agree, as readable lines."
    ours = ptterm_cells(data, lines, columns)
    theirs = vterm_cells(data, lines, columns)
    keep = _keeper(strict, blank_style)

    reported = []
    for y in range(lines):
        for x in range(columns):
            mine, other = keep(ours[y][x]), keep(theirs[y][x])
            if mine != other:
                reported.append(
                    "cell %d,%d: ptterm %r, libvterm %r" % (y, x, mine, other)
                )
    return reported


def three_way(
    data: str,
    lines: int = 6,
    columns: int = 20,
    strict: bool = False,
    blank_style: bool = True,
) -> str:
    """
    What the three screens say about one program.

    - "agree": all three draw the same thing.
    - "ptterm-wrong": kitty and libvterm agree with each other and not
      with ptterm. Nobody has to decide anything; this is a bug.
    - "split": the two others disagree, so the difference is a choice.

    A vote is worth more than a comparison: it tells a deviation that
    has to be fixed apart from one that has to be decided.
    """
    from kitty_oracle import kitty_cells, kitty_is_available

    # The check is what puts the package of kitty on the path.
    assert kitty_is_available(), "PTTERM_KITTY names no kitty"

    keep = _keeper(strict, blank_style)
    ours = ptterm_cells(data, lines, columns)
    kitty = kitty_cells(data, lines, columns)
    vterm = vterm_cells(data, lines, columns)

    def rows(screen):
        return [[keep(cell) for cell in row] for row in screen]

    ours, kitty, vterm = rows(ours), rows(kitty), rows(vterm)
    if kitty != vterm:
        return "split"
    return "agree" if ours == kitty else "ptterm-wrong"
