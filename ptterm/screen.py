"""
Custom `Screen` class for the `pyte` library.

Changes compared to the original `Screen` class:
    - We store the layout in a prompt_toolkit.layout.screen.Screen instance.
      This allows fast rendering in a prompt_toolkit user control.
    - 256 colour and true color support.
    - CPR support and device attributes.
"""
import base64
from collections import defaultdict, namedtuple
from enum import IntEnum, IntFlag, StrEnum
from typing import Callable, DefaultDict, Dict, List, Tuple

from prompt_toolkit.cache import FastDictCache
from prompt_toolkit.layout.screen import Char, Screen
from prompt_toolkit.output.vt100 import BG_ANSI_COLORS, FG_ANSI_COLORS
from prompt_toolkit.output.vt100 import _256_colors as _256_colors_table
from prompt_toolkit.styles import Attrs
from pyte import charsets as cs
from pyte import modes as mo
from pyte.screens import Margins

from .graphics import (
    ASSUMED_CELL_HEIGHT,
    ASSUMED_CELL_WIDTH,
    GraphicsState,
)
from .osc import (
    DEFAULT_COLORS,
    DYNAMIC_COLOR_CODES,
    DYNAMIC_COLOR_RESET_OFFSET,
    FIRST_SPECIAL_COLOR,
    MAX_POINTER_SHAPES,
    PALETTE,
    SPECIAL_COLOR_NAMES,
    Color,
    parse_color,
    parse_hyperlink,
    parse_kitty_color_query,
    pointer_shape_name,
)
from .placeholders import PlaceholderRun, merge_runs, runs_in_line
from .sixel import decode_sixel

__all__ = ("BetterScreen",)


#: OSC sequences that a pane cannot answer by itself. They ask the
#: terminal of the user for the clipboard (52), a desktop notification
#: (99) or the shape of the pointer (22). `BetterScreen.osc_func`
#: receives them; a ptterm without such a function consumes them.
class Osc(StrEnum):
    """
    The OSC codes that a pane reads.

    An OSC names its code in text, not in a parameter, so the code is
    a string here as well.
    """

    #: "OSC 8": the hyperlink that the cells after it carry.
    HYPERLINK = "8"
    #: "OSC 4": one entry of the palette, by index.
    PALETTE_COLOR = "4"
    #: "OSC 5": one colour that a rendition asks for by name.
    SPECIAL_COLOR = "5"
    #: "OSC 21": the colours, in the form that kitty reads.
    KITTY_COLORS = "21"
    #: "OSC 22": the shape of the pointer over the pane.
    POINTER_SHAPE = "22"
    #: "OSC 52": the clipboard of the user.
    CLIPBOARD = "52"
    #: "OSC 99": a desktop notification.
    NOTIFICATION = "99"
    #: "OSC 104": put palette entries back to their defaults.
    RESET_PALETTE_COLOR = "104"
    #: "OSC 105": put special colours back to their defaults.
    RESET_SPECIAL_COLOR = "105"


#: OSC sequences that a pane cannot answer by itself. `FORWARDED_OSC`
#: above says what each one asks for.
FORWARDED_OSC = frozenset([
    Osc.POINTER_SHAPE,
    Osc.CLIPBOARD,
    Osc.NOTIFICATION,
])

#: What XTVERSION ("CSI > q") answers. ptterm draws the pane, so ptterm
#: is what the program in it talks to.
TERMINAL_VERSION = "ptterm(0.2)"

class CursorShape(IntEnum):
    """
    The shape of the cursor, as DECSCUSR ("CSI Ps SP q") names it.

    One number carries the shape and the blinking together. The
    blinking shapes are the odd numbers, and the steady one of a pair
    is the number after it. Private mode 12 writes the blinking alone,
    so both sequences write this one value.
    """

    BLINKING_BLOCK = 1
    STEADY_BLOCK = 2
    BLINKING_UNDERLINE = 3
    STEADY_UNDERLINE = 4
    BLINKING_BAR = 5
    STEADY_BAR = 6


#: The shape that a terminal starts with.
DEFAULT_CURSOR_STYLE = CursorShape.BLINKING_BLOCK


class PrivateMode(IntEnum):
    """
    A private mode, by the number that "CSI ? Ps h" carries.

    pyte shifts a private mode five bits to the left, to tell it from a
    mode that carries no marker, and `self.mode` holds the shifted
    value. `flag` is that value, and the member itself is the number
    that a program writes. `pyte.modes` carries the modes that pyte
    knows about, already shifted, under its own names; these are the
    ones it does not carry.
    """

    #: DECCKM: the cursor keys send application codes.
    APPLICATION_CURSOR_KEYS = 1

    #: DECCOLM: 132 columns instead of 80.
    COLUMNS_132 = 3

    #: DECSCLM: scroll slowly. A pane draws as fast as it can, so this
    #: one is kept and not acted on.
    SLOW_SCROLL = 4

    #: DECSCNM: reverse video over the whole screen.
    REVERSE_VIDEO = 5

    #: DECOM: the cursor is placed from the margins, not the screen.
    ORIGIN = 6

    #: DECAWM: a character past the last column wraps to the next line.
    AUTOWRAP = 7

    #: att610: does the cursor blink? DECSCUSR names the shape and the
    #: blinking in one number, and this mode names only the blinking,
    #: so both of them write `cursor_style`.
    CURSOR_BLINK = 12

    #: DECPFF: send a form feed after a print. There is no printer.
    PRINT_FORM_FEED = 18

    #: DECPEX: a print takes the page, not the scrolling region. There
    #: is no printer.
    PRINT_EXTENT = 19

    #: DECTCEM: is the cursor drawn?
    SHOW_CURSOR = 25

    #: DECHEBM: the Hebrew keyboard.
    HEBREW_KEYBOARD = 35

    #: DECNRCM: the national replacement character sets.
    NATIONAL_CHARSETS = 42

    #: A backspace in the first column goes back to the line above,
    #: but only when that line was reached by wrapping. It undoes what
    #: the typing did, and no more.
    REVERSE_WRAP = 45

    #: The alternate screen, on its own. A program that predates
    #: "?1049" sends this one.
    ALTERNATE_SCREEN = 47

    #: DECHCCM: the cursor is coupled to the horizontal scroll. No
    #: terminal that anybody uses carries it.
    HORIZONTAL_CURSOR_COUPLING = 60

    #: DECNKM: the keypad sends application codes.
    APPLICATION_KEYPAD = 66

    #: DECBKM: the backarrow key sends a backspace, not a delete.
    BACKARROW_IS_BACKSPACE = 67

    #: DECLRMM: may DECSLRM set a left and a right margin? The mode
    #: alone changes nothing. It says whether "CSI Pl ; Pr s" names the
    #: margins, and resetting it takes the margins away.
    LEFT_RIGHT_MARGIN = 69

    #: Report the position of the mouse.
    MOUSE_REPORTING = 1000

    #: Report the mouse the way SGR writes it.
    SGR_MOUSE = 1006

    #: Report the mouse the way urxvt writes it.
    URXVT_MOUSE = 1015

    #: A backspace in the first column goes back to the line above,
    #: whether that line was wrapped or not, and from the first line
    #: to the last. This is what "?45" did before xterm 383 split the
    #: two apart.
    REVERSE_WRAP_ANYWHERE = 1045

    #: The alternate screen. The same screen as "?47", under the
    #: number that came later.
    ALTERNATE_SCREEN_AGAIN = 1047

    #: Save the cursor on a set, and bring it back on a reset. It is
    #: the pair of "ESC 7" and "ESC 8" written as one mode. "?1049"
    #: holds this mode and the alternate screen together.
    SAVE_CURSOR = 1048

    #: The alternate screen, with the cursor and a clear. This is the
    #: one a program sends today.
    ALTERNATE_SCREEN_WITH_CURSOR = 1049

    #: Wrap a paste in "ESC [ 200 ~" and "ESC [ 201 ~", so that a
    #: program can tell a paste from typing.
    BRACKETED_PASTE = 2004

    #: Report a resize in the input of the program, instead of only
    #: through SIGWINCH.
    INBAND_RESIZE = 2048

    @property
    def flag(self) -> int:
        "The value that `self.mode` holds while this mode is set."
        return self.value << 5


class AttributeExtent(IntEnum):
    """
    What DECCARA and DECRARA reach, as DECSACE ("CSI Ps * x") sets it.

    A stream runs from the first corner to the second, the way a
    program reads a page. A rectangle takes the columns between them
    on every row.

    Zero and one both name the stream. A terminal reports back the one
    it was given, so the two are kept apart here.
    """

    DEFAULT = 0
    STREAM = 1
    RECTANGLE = 2


class StatusDisplay(IntEnum):
    "Where the output goes, as DECSASD (\"CSI Ps $ }\") sets it."

    MAIN = 0
    STATUS_LINE = 1


class StatusLineType(IntEnum):
    """
    What the status line holds, as DECSSDT ("CSI Ps $ ~") sets it.

    A terminal draws the indicator itself. A host status line holds
    what the program writes to it, after DECSASD sends the output
    there.
    """

    NONE = 0
    INDICATOR = 1
    HOST_WRITABLE = 2


class ConformanceLevel(IntEnum):
    """
    The level DECSCL ("CSI Ps ; Ps " p") names.

    Each one is the level of one DEC terminal, and a higher level takes
    every sequence of the levels below it.
    """

    VT100 = 61
    VT200 = 62
    VT300 = 63
    VT400 = 64
    VT500 = 65


#: The level ptterm reports until a program names another one. It
#: answers the sequences of a VT500, so it says so.
DEFAULT_CONFORMANCE_LEVEL = ConformanceLevel.VT500


class AnsiMode(IntEnum):
    """
    A mode that "CSI Ps h" carries, with no private marker.

    These come from the ANSI standard. `pyte.modes` names the two that
    pyte acts on, IRM and LNM, and holds them unshifted; these are the
    rest. Nearly all of them come from a time of block mode terminals,
    and no terminal that anybody uses today acts on one.
    """

    #: GATM: transfer the guarded areas as well.
    GUARDED_AREA_TRANSFER = 1

    #: KAM: lock the keyboard.
    KEYBOARD_LOCKED = 2

    #: SRTM: report a status change on its own.
    STATUS_REPORT_TRANSFER = 5

    #: VEM: an insert moves the lines up, not down.
    VERTICAL_EDITING = 7

    #: HEM: an insert moves the characters left, not right.
    HORIZONTAL_EDITING = 10

    #: PUM: the unit of a position is a millimetre, not a cell.
    POSITIONING_UNIT = 11

    #: SRM: echo what the keyboard sends.
    LOCAL_ECHO = 12

    #: FEAM: a format effector acts on the store, not the screen.
    FORMAT_EFFECTOR_ACTION = 13

    #: FETM: transfer the format effectors as well.
    FORMAT_EFFECTOR_TRANSFER = 14

    #: MATM: transfer every selected area, not only one.
    MULTIPLE_AREA_TRANSFER = 15

    #: TTM: a transfer stops at the end of the selected area.
    TRANSFER_TERMINATION = 16

    #: SATM: transfer the whole screen, not the selected area.
    SELECTED_AREA_TRANSFER = 17

    #: TSM: a tab stop belongs to one line, not to the screen.
    TABULATION_STOP = 18

    #: EBM: an edit stops at the end of the screen, not the area.
    EDITING_BOUNDARY = 19


class ModeReport(IntEnum):
    """
    What DECRQM ("CSI Ps $ p") answers about a mode.

    Zero says that the terminal never heard of the mode, and a program
    that reads it falls back to what it knows. Four says that the mode
    exists and can never be on, which is what a program needs to stop
    asking.
    """

    UNKNOWN = 0
    SET = 1
    RESET = 2
    PERMANENTLY_SET = 3
    PERMANENTLY_RESET = 4


class WindowOp(IntEnum):
    "The operations of \"CSI Ps t\" that a pane can answer."

    REPORT_TEXT_AREA_PIXELS = 14
    REPORT_CELL_SIZE_PIXELS = 16
    REPORT_TEXT_AREA_CHARS = 18
    REPORT_ICON_LABEL = 20
    REPORT_WINDOW_TITLE = 21
    PUSH_TITLE = 22
    POP_TITLE = 23

    #: "CSI 4 ; Ph ; Pw t": as many cells as fit the given pixels.
    RESIZE_PIXELS = 4

    #: "CSI 8 ; Ph ; Pw t": that many rows and columns.
    RESIZE_CHARS = 8


#: "CSI Ps t" with a Ps of this or more is DECSLPP, and asks for a page
#: of Ps lines. Below it, Ps names one of the `WindowOp` operations.
FIRST_PAGE_LENGTH = 24


class TitlePart(IntEnum):
    "Which title a push or a pop of \"CSI 22 t\" and \"CSI 23 t\" names."

    BOTH = 0
    ICON = 1
    WINDOW = 2

#: The names that prompt_toolkit gives the first sixteen colours of the
#: palette, in the order that "CSI 38 ; 5 ; n m" numbers them.
PALETTE_NAMES = [
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


#: The name of the terminfo entry that describes a pane. A program
#: reads it with the "TN" capability.
TERMINAL_NAME = "pymux"

#: What a pane can do, in the form that XTGETTCAP answers.
#:
#: A program asks over the wire instead of reading a database, which is
#: the only way it can learn what a pane can do: `TERM` names an entry
#: that may not be installed where the program runs, and over ssh it
#: is the only way at all.
#:
#: `True` is a capability that a terminal either has or does not. A
#: string is a value, and one that holds "%" travels as the source
#: text, the way terminfo writes it.
#:
#: Nothing goes in here that a pane does not really do. A capability
#: that is claimed and not served is worse than one that is missing:
#: the program stops asking and draws what it cannot draw.
CAPABILITIES: Dict[str, object] = {
    # The name of the entry.
    "TN": TERMINAL_NAME,
    "name": TERMINAL_NAME,
    # Automatic margins, and the wrap that waits in the last column.
    "am": True,
    "xenl": True,
    # An erased cell takes the background that is set.
    "bce": True,
    # 24 bit colour, under both names that a program looks for.
    "RGB": True,
    "Tc": True,
    # The shape and the colour of an underline.
    "Su": True,
    "Smulx": r"\E[4:%p1%dm",
    "Setulc": r"\E[58:2:%p1%{65536}%/%d:%p1%{256}%/%{255}%&%d:%p1%{255}%&%d%;m",
    # The keyboard protocol of kitty.
    "fullkbd": True,
    # The clipboard, which a pane may write.
    "Ms": r"\E]52;%p1%s;%p2%s\E\\",
    # A number is a number here, so that one table can answer a
    # query and describe an entry of terminfo.
    # The size of the palette, under both names. A program reads this
    # to learn where the special colours start, so it must be the size
    # of the table that answers "OSC 4".
    "colors": len(PALETTE),
    "Co": len(PALETTE),
    "pairs": 32767,
}

#: The shape of the line that each sub-parameter of "SGR 4" draws.
#: Zero draws none. An empty name is the single line that a plain
#: "SGR 4" draws, and prompt_toolkit reads it as such.
UNDERLINE_SHAPES = {
    0: "",
    1: "",
    2: "double",
    3: "curly",
    4: "dotted",
    5: "dashed",
}

#: The word that a style string gives each shape.
UNDERLINE_WORDS = {
    "": "underline",
    "double": "underdouble",
    "curly": "undercurl",
    "dotted": "underdotted",
    "dashed": "underdashed",
}

#: The sub-parameter of "SGR 4" that each shape answers with.
UNDERLINE_PARAMETERS = {
    "": "4",
    "double": "4:2",
    "curly": "4:3",
    "dotted": "4:4",
    "dashed": "4:5",
}


def _rgb_components(color: str | None) -> Tuple[int, int, int] | None:
    "The three components of a '#rrggbb' colour, or None for anything else."
    if not color:
        return None
    text = color.lstrip("#")
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def _reads_the_clipboard(param: str) -> bool:
    """
    True for a clipboard query, e.g. "OSC 52 ; c ; ?". The payload of
    OSC 52 names a selection and then the data; a question mark asks
    for the content instead of setting it.
    """
    _selection, _semicolon, data = param.partition(";")
    return data.strip() == "?"


#: The first and the last column of the scrolling region, counted from
#: zero. DECSLRM ("CSI Pl ; Pr s") names them. `pyte.screens.Margins`
#: names the first and the last row, and this is the other pair.
HorizontalMargins = namedtuple("HorizontalMargins", "left right")


class CursorPosition:
    "Mutable CursorPosition."

    def __init__(self, x: int = 0, y: int = 0) -> None:
        self.x = x
        self.y = y

    def __repr__(self) -> str:
        return f"pymux.CursorPosition(x={self.x!r}, y={self.y!r})"


class _UnicodeInternDict(Dict[str, str]):
    """
    Intern dictionary for interning unicode strings. This should save memory
    and make our cache faster.
    """

    def __missing__(self, value: str) -> str:
        self[value] = value
        return value


_unicode_intern_dict = _UnicodeInternDict()


class ErasedChar(Char):
    """
    The blank that an erase leaves behind.

    It draws as a space, and it holds no character. The difference
    matters for one thing: a combining mark that arrives next has
    nothing to hang on, so the mark goes away. A space that a program
    draws is a character, and a mark does hang on that.

    kitty and WezTerm both draw the line in that place. ptterm gave two
    answers for the same program before this. An erase with no
    background drops the cell, so the mark went away. An erase with a
    background wrote a space, so the mark stayed.
    """

    __slots__ = ()


class TerminalChar(Char):
    """
    One cell of a pane, holding what the program wrote.

    prompt_toolkit shows a no-break space as a space that is underlined
    in yellow, so that a reader of a widget can see one. A pane is not
    a widget: "tree" draws its indentation with no-break spaces, and
    every emulator keeps them as they are. So does this.
    """

    __slots__ = ()

    def __init__(self, char: str = " ", style: str = "") -> None:
        if char == "\xa0":
            # Skip the mapping of the parent, and keep the character.
            self.char = char
            self.style = style
            self.width = 1
        else:
            super().__init__(char, style)


class Protection(IntFlag):
    """
    The marks that hold an erase away from a cell.

    A cell can carry both, because the two commands that set them are
    not the same command and neither one takes the other away.
    """

    NONE = 0

    #: SPA ("ESC V") sets it. ED, EL and ECH read it.
    ISO = 1

    #: DECSCA ("CSI 1 " q") sets it. The selective erases, DECSED and
    #: DECSEL, read it.
    DEC = 2


class ProtectedChar(TerminalChar):
    """
    One cell that an erase may have to leave alone.

    Two commands mark a cell, and each one holds a different erase
    away from it. `protection` carries both marks, because a cell can
    hold either or both.
    """

    __slots__ = ("protection",)

    def __init__(
        self, char: str = " ", style: str = "", protection: int = 0
    ) -> None:
        super().__init__(char, style)
        self.protection = protection


def protection_of(cell: Char) -> int:
    "The marks that a cell carries. A plain cell carries none."
    return getattr(cell, "protection", 0)


def _four(params: Tuple[int, ...], first: int) -> Tuple[int, int, int, int]:
    """
    Four parameters, counting from `first`, with zero for a missing one.

    A sender drops the parameters it leaves at the default, so a
    command that names four corners can arrive with fewer. Zero is what
    an empty parameter gives, so the two read the same way.
    """
    read = params[first : first + 4]
    return tuple(read) + (0,) * (4 - len(read))  # type: ignore[return-value]


# Cache for Char objects.
_CHAR_CACHE: FastDictCache[Tuple[str, str], Char] = FastDictCache(
    TerminalChar, size=1000 * 1000
)

#: The same for the cells that carry a mark. Nearly no program marks
#: one, so this one stays small.
_PROTECTED_CHAR_CACHE: FastDictCache[Tuple[str, str, int], Char] = FastDictCache(
    ProtectedChar, size=10 * 1000
)


# Custom Savepoint that also stores the Attrs.
_Savepoint = namedtuple(
    "_Savepoint",
    [
        "cursor_x",
        # The row within the screen, not within the buffer.
        "cursor_y",
        "g0_charset",
        "g1_charset",
        "charset",
        "origin",
        "attrs",
        "style_str",
        # The marks that SPA and DECSCA set. They belong to the cursor,
        # the way the rendition does, so a save remembers them.
        "protection",
    ],
)


class BetterScreen:
    """
    Custom screen class. Most of the methods are called from a vt100 Pyte
    stream.

    The data buffer is stored in a :class:`prompt_toolkit.layout.screen.Screen`
    class, because this way, we can send it to the renderer without any
    transformation.
    """

    #: The state that the alternate screen keeps for itself. The
    #: scrolling region is not in the list: it belongs to the terminal,
    #: so a region set on one screen holds on the other. xterm and
    #: kitty both work that way.
    swap_variables = [
        "mode",
        "charset",
        # The cursor that "ESC 7" saves belongs to one screen. A
        # restore on the alternate screen may not read the one that the
        # first screen holds.
        "savepoints",
        "g0_charset",
        "g1_charset",
        "tabstops",
        "pointer_shapes",
        "data_buffer",
        "pt_cursor_position",
        # The wait to wrap belongs to the cursor, so it travels with it.
        "pending_wrap",
        "max_y",
        # The kitty keyboard protocol keeps separate flag stacks for the
        # main and the alternate screen. (Immutable tuple: safe to swap.)
        "kitty_flags_stack",
        # The graphics state is swapped by reference: the alternate
        # screen gets a fresh GraphicsState, the main screen one is
        # restored when leaving the alternate screen.
        "graphics",
    ]

    def __init__(
        self,
        lines: int,
        columns: int,
        write_process_input: Callable[[str], None],
        bell_func: Callable[[], None] | None = None,
        get_history_limit: Callable[[], int] | None = None,
        osc_func: Callable[[str, str], None] | None = None,
        resize_func: Callable[[int | None, int | None], None] | None = None,
    ) -> None:
        bell_func = bell_func or (lambda: None)
        get_history_limit = get_history_limit or (lambda: 2000)
        osc_func = osc_func or (lambda code, param: None)
        # A pane cannot resize itself: it sits in a layout that somebody
        # else owns. So the ask goes out, and the embedder decides. With
        # no embedder the ask goes nowhere, which is the old answer.
        resize_func = resize_func or (lambda lines, columns: None)

        self._history_cleanup_counter = 0

        self.savepoints: List[_Savepoint] = []
        self.lines = lines
        self.columns = columns
        self.write_process_input = write_process_input
        self.bell_func = bell_func
        self.get_history_limit = get_history_limit
        self.osc_func = osc_func
        self.resize_func = resize_func

        # Stack of kitty keyboard protocol flags. ("CSI > flags u" pushes,
        # "CSI < number u" pops. See `report_kitty_keyboard`.)
        self.kitty_flags_stack: Tuple[int, ...] = ()

        # What the terminal that feeds this pane its keys can report,
        # in the same flags. The host sets it; zero means a terminal
        # that speaks the legacy encoding only. It belongs to the host
        # and not to the screen, so a reset leaves it alone.
        self.keyboard_source_flags: int = 0

        # Whether to make up the halves of a key event that such a
        # terminal cannot send. With it, a pane gets what it asked for
        # from any keyboard; without it, a pane hears that it does not
        # have it. The host sets this one as well.
        self.synthesize_key_events: bool = True

        # The shapes of the pointer that "OSC 22" pushed. The last one
        # is the shape now. Each screen keeps its own, the way kitty
        # does.
        self.pointer_shapes: List[str] = []

        # Kitty graphics protocol state: transmitted images and their
        # placements. (Reset and alternate screen switching replace the
        # whole state; see `reset` and `set_mode`.)
        self.graphics = GraphicsState()

        self.reset()

    @property
    def in_application_mode(self) -> bool:
        """
        True when we are in application mode. This means that the process is
        expecting some other key sequences as input. (Like for the arrows.)
        """
        # Not in cursor mode.
        return PrivateMode.APPLICATION_CURSOR_KEYS.flag in self.mode

    @property
    def mouse_support_enabled(self) -> bool:
        "True when mouse support has been enabled by the application."
        return PrivateMode.MOUSE_REPORTING.flag in self.mode

    @property
    def urxvt_mouse_support_enabled(self) -> bool:
        return PrivateMode.URXVT_MOUSE.flag in self.mode

    @property
    def sgr_mouse_support_enabled(self) -> bool:
        "Xterm Sgr mouse support."
        return PrivateMode.SGR_MOUSE.flag in self.mode

    @property
    def bracketed_paste_enabled(self) -> bool:
        return PrivateMode.BRACKETED_PASTE.flag in self.mode

    @property
    def kitty_keyboard_flags(self) -> int:
        """
        The currently effective kitty keyboard protocol flags. (The top of
        the flag stack, or zero when the stack is empty.)
        """
        return self.kitty_flags_stack[-1] if self.kitty_flags_stack else 0

    #: The kitty keyboard protocol flags that need a terminal that
    #: speaks the protocol. The event type of a key needs a key
    #: release, and the other codes of a key need the layout of the
    #: user. The legacy encoding carries neither of them by itself.
    #: The other three flags are a form to write a key in, so any
    #: terminal serves them.
    kitty_flags_that_need_a_source = 0b110

    @property
    def deliverable_kitty_keyboard_flags(self) -> int:
        """
        The flags that this pane really gets, of the ones it asked for.

        A pane asks the terminal what it does, and the answer has to
        hold. With `synthesize_key_events`, every flag holds: a key
        release that the keyboard never sends is made up, and the
        shifted key of a letter is known. Without it, the answer drops
        what the keyboard cannot serve on its own.
        """
        if self.synthesize_key_events:
            return self.kitty_keyboard_flags
        missing = self.kitty_flags_that_need_a_source & ~self.keyboard_source_flags
        return self.kitty_keyboard_flags & ~missing

    @property
    def has_reverse_video(self) -> bool:
        "The whole screen is set to reverse video."
        return mo.DECSCNM in self.mode

    def reset(self) -> None:
        """Resets the terminal to its initial state.

        * Scroll margins are reset to screen boundaries.
        * Cursor is moved to home location -- ``(0, 0)`` and its
          attributes are set to defaults (see :attr:`default_char`).
        * Screen is cleared -- each character is reset to
          :attr:`default_char`.
        * Tabstops are reset to "every eight columns".

        .. note::

           Neither VT220 nor VT102 manuals mentioned that terminal modes
           and tabstops should be reset as well, thanks to
           :manpage:`xterm` -- we now know that.
        """
        self._reset_screen()

        self.title = ""
        self.icon_name = ""

        # The titles that "CSI 22 t" remembered. A reset empties it,
        # the way it empties everything else that a program set.
        self.title_stack: List[Tuple[str, str]] = []

        # Reset the kitty keyboard protocol flag stack as well. (RIS is a
        # full terminal reset. It also clears all graphics.)
        self.kitty_flags_stack = ()
        self.graphics.clear()

        # The shape of the cursor, as DECSCUSR names it. A reset puts
        # it back to the shape that the terminal starts with.
        self.cursor_style = DEFAULT_CURSOR_STYLE

        # The marks that SPA and DECSCA put on the cells that a
        # program draws next. Nothing is marked to start with.
        self.protection = 0

        # The character that REP repeats. Nothing is drawn yet, so a
        # repeat now draws nothing.
        self.last_character = ""

        # The colours that a program set with "OSC 4", "OSC 5" and
        # "OSC 10". A pane starts with neither table filled and
        # answers a query from the defaults. A set puts an entry here,
        # and "OSC 104", "OSC 105" or "OSC 110" takes it away again.
        #
        # The first table is keyed by the index that "OSC 4" writes,
        # which counts the palette first and the special colours after
        # it. The second is keyed by the code of the sequence itself.
        self.palette_colors: Dict[int, Tuple[int, int, int]] = {}
        self.dynamic_colors: Dict[str, Tuple[int, int, int]] = {}

        # Does the cursor wait to wrap? A character in the last column
        # of the line leaves the cursor one column further, and the
        # next character starts the line below.
        #
        # The place alone does not say so. With a right margin the wait
        # sits one column after the margin, and a program can put the
        # cursor there itself. The two look the same and behave
        # differently, so the wait is a flag and not a place.
        self.pending_wrap = False

        # The settings that a program writes and reads back with
        # DECRQSS. ptterm keeps each one and acts on none of them; the
        # docstring of each handler says what it would do.
        self.attribute_extent = AttributeExtent.STREAM
        self.active_display = StatusDisplay.MAIN
        self.status_line = StatusLineType.NONE
        self.conformance_level = DEFAULT_CONFORMANCE_LEVEL
        self.seven_bit_controls = 1
        self.lines_per_screen = self.lines

        # Reset modes.
        self.mode = {
            mo.DECAWM,  # Autowrap mode. (default: disabled).
            mo.DECTCEM,  # Text cursor enable mode. (default enabled).
        }

        # According to VT220 manual and ``linux/drivers/tty/vt.c``
        # the default G0 charset is latin-1, but for reasons unknown
        # latin-1 breaks ascii-graphics; so G0 defaults to cp437.

        # XXX: The comment above comes from the original Pyte implementation,
        #      it seems for us that LAT1_MAP should indeed be the default, if
        #      not a French version of Vim would incorrectly show some
        #      characters.
        # Has a double width character ever reached the screen? Nearly
        # no pane draws one, and the repair that a broken pair needs
        # costs a lookup for every character. The flag skips it.
        self._wide_chars = False

        # Has a cell that an erase has to leave alone ever reached the
        # screen? Nearly no program marks one, and the flag keeps the
        # erasing of a whole screen from looking at every cell.
        self._protected_chars = False

        # G1 holds ASCII as well until a program names something
        # else. pyte starts it on the line drawing set, and a stray
        # shift out then turned every letter into a box character.
        self.charset = 0
        # self.g0_charset = cs.IBMPC_MAP
        self.g0_charset = cs.LAT1_MAP
        self.g1_charset = cs.LAT1_MAP

        # From ``man terminfo`` -- "... hardware tabs are initially
        # set every `n` spaces when the terminal is powered up. Since
        # we aim to support VT102 / VT220 and linux -- we use n = 8.

        # (We choose to create tab stops until x=1000, because we keep the
        # tab stops when the screen increases in size. The OS X 'ls' command
        # relies on the stops to be there.)
        self.tabstops = set(range(8, 1000, 8))

        # The original Screen instance, when going to the alternate screen.
        self._original_screen: Screen | None = None
        # The alternate screen, while the first one is in front. A
        # terminal keeps one alternate screen for its whole life and
        # hands it back with what it held, so this outlives a visit.
        # `None` means that nothing was ever drawn on it.
        self._alternate_screen: Screen | None = None
        self._alternate_screen_vars: dict = {}

    def soft_reset(self, *params: int, **kwargs) -> None:
        """
        DECSTR ("CSI ! p"): put the settings back, and keep the screen.

        A soft reset leaves the text and the cursor where they are. It
        takes away what a program changed about the terminal, so that
        the next program starts from one that it knows. A program that
        ends sends this, and a program that starts sends it as well.

        The scrolling region goes back to the whole screen, in the rows
        and in the columns, and the cursor that a save remembers goes
        home. Autowrap stays on: the DEC manuals turn it off, and xterm
        keeps it on because programs came to count on it.

        The alternate screen is not a setting of this kind. A soft
        reset on it leaves it in front, the way xterm does.
        """
        self.margins = None
        self.horizontal_margins = None

        alternate = self.mode.intersection(self._ALTERNATE_SCREEN_MODES)
        self.mode = {mo.DECAWM, mo.DECTCEM}
        self.mode.update(alternate)
        self.pt_screen.show_cursor = True

        # A list of its own, because a save writes into the list that
        # is there rather than making a new one.
        self.savepoints = []

        self.charset = 0
        self.g0_charset = cs.LAT1_MAP
        self.g1_charset = cs.LAT1_MAP

        # A soft reset takes the mark off what a program draws next.
        # The cells that carry one already keep it.
        self.protection = 0

        self._reset_rendition()

    def start_protected_area(self) -> None:
        """
        SPA ("ESC V"): mark the cells that a program draws next.

        ED, EL and ECH leave a marked cell alone. The mark comes from
        ISO 6429, and it is not the mark that DECSCA sets: the
        selective erases read both, and these three read only this
        one.
        """
        self.protection |= Protection.ISO

    def end_protected_area(self) -> None:
        "EPA (\"ESC W\"): stop marking the cells that a program draws."
        self.protection &= ~Protection.ISO

    def set_character_protection(self, *params: int, **kwargs) -> None:
        """
        DECSCA ("CSI Ps " q"): mark the cells that a program draws next.

        One marks them, and zero and two take the mark away. DECSED and
        DECSEL leave a marked cell alone, and ED, EL and ECH do not:
        that is the whole difference between the two pairs.
        """
        if (params[0] if params else 0) == 1:
            self.protection |= Protection.DEC
        else:
            self.protection &= ~Protection.DEC

    def _erase_holds(self, cell: Char, selective: bool) -> bool:
        """
        True when an erase has to leave this cell alone.

        A selective erase reads both marks. xterm reads the mark of
        ISO 6429 there as well, for the programs that came before
        DECSCA, and this follows xterm.
        """
        if not self._protected_chars:
            return False

        marks = protection_of(cell)
        if not marks:
            return False
        return True if selective else bool(marks & Protection.ISO)

    def _reset_rendition(self) -> None:
        """
        Draw what comes next plainly, and under no hyperlink.

        A screen carries neither: its cells hold the rendition and the
        link that they were drawn with. Taking a screen therefore
        starts plain, whether the screen is a new one or the one that
        the last visit left.
        """
        self._attrs = Attrs(
            color=None,
            bgcolor=None,
            bold=False,
            dim=False,
            underline=False,
            strike=False,
            italic=False,
            blink=False,
            reverse=False,
            hidden=False,
            underline_style="",
            underline_color="",
        )
        self._style_str = ""
        # The rendition alone, without the hyperlink. The two change
        # apart from each other, so the style of a cell is built from
        # both.
        self._rendition_str = ""
        # The target of the hyperlink that is open ("OSC 8"), and the
        # piece of style that carries it.
        self.hyperlink = ""
        self._hyperlink_str = ""

    def _reset_screen(self) -> None:
        """Reset the Screen content. (also called when switching from/to
        alternate buffer."""
        self.pt_screen = Screen(
            default_char=Char(" ", "")
        )  # TODO: Stop using this Screen class!

        self.pt_screen.show_cursor = True

        self.data_buffer = self.pt_screen.data_buffer
        self.pt_cursor_position = CursorPosition(0, 0)
        self.wrapped_lines: List[int] = []  # List of line indexes that were wrapped.

        self._reset_rendition()

        self.margins = None
        self.horizontal_margins: HorizontalMargins | None = None

        # A list of its own, because the stack is changed in place and
        # the screen this one replaces still holds the old list.
        self.pointer_shapes = []

        self.max_y = 0  # Max 'y' position to which is written.

    def resize(
        self, lines: int | None = None, columns: int | None = None
    ) -> None:
        # Save the dimensions.
        lines = lines if lines is not None else self.lines
        columns = columns if columns is not None else self.columns

        if self.lines != lines or self.columns != columns:
            self.lines = lines
            self.columns = columns

            self._reset_offset_and_margins()

            # If the height was reduced, and there are lines below
            # `cursor_position_y+lines`. Remove them by setting 'max_y'.
            # (If we don't do this. Clearing the screen, followed by reducing
            # the height will keep the cursor at the top, hiding some content.)
            self.max_y = min(self.max_y, self.pt_cursor_position.y + lines - 1)

            self._reflow()

            # A program that asked for it learns the new size in band.
            self.notify_of_resize()

    def notify_of_resize(self) -> None:
        """
        Tell the program in this pane how big the pane is, in band.

        A program that sets private mode 2048 reads the size from its
        own input instead of from SIGWINCH. That is what a program
        behind a multiplexer or an ssh connection needs: the signal
        does not travel, the escape sequence does.

        The pixel size follows the cell that `ptterm.graphics` assumes,
        so it agrees with what "CSI 14 t" and "CSI 16 t" report.
        """
        if PrivateMode.INBAND_RESIZE.flag not in self.mode:
            return

        self.write_process_input(
            "\x1b[48;%i;%i;%i;%it"
            % (
                self.lines,
                self.columns,
                self.lines * ASSUMED_CELL_HEIGHT,
                self.columns * ASSUMED_CELL_WIDTH,
            )
        )

    @property
    def line_offset(self) -> int:
        "Return the index of the first visible line."
        cpos_y = self.pt_cursor_position.y

        # NOTE: the +1 is required because `max_y` starts counting at 0 for the
        #       first line, while `self.lines` is the number of lines, starting
        #       at 1 for one line. The offset refers to the index of the first
        #       visible line.
        #       For instance, if we have: max_y=14 and lines=15. Then all lines
        #       from 0..14 have been used. This means 15 lines are used, and
        #       the first index should be 0.
        return max(0, self.max_y - self.lines + 1)

    def set_margins(
        self, top: int | None = None, bottom: int | None = None
    ) -> None:
        """Selects top and bottom margins for the scrolling region.
        Margins determine which screen lines move during scrolling
        (see :meth:`index` and :meth:`reverse_index`). Characters added
        outside the scrolling region do not cause the screen to scroll.
        :param int top: the smallest line number that is scrolled.
        :param int bottom: the biggest line number that is scrolled.
        """
        if top is None and bottom is None:
            return

        margins = self.margins or Margins(0, self.lines - 1)

        top = margins.top if top is None else top - 1
        bottom = margins.bottom if bottom is None else bottom - 1

        # Arguments are 1-based, while :attr:`margins` are zero based --
        # so we have to decrement them by one. We also make sure that
        # both of them is bounded by [0, lines - 1].
        top = max(0, min(top, self.lines - 1))
        bottom = max(0, min(bottom, self.lines - 1))

        # Even though VT102 and VT220 require DECSTBM to ignore regions
        # of width less than 2, some programs (like aptitude for example)
        # rely on it. Practicality beats purity.
        if bottom - top >= 1:
            self.margins = Margins(top, bottom)

            # The cursor moves to the home position when the top and
            # bottom margins of the scrolling region (DECSTBM) changes.
            self.cursor_position()

    @property
    def left_right(self) -> Tuple[int, int]:
        """
        The first and the last column of the scrolling region.

        Without margins the region is the whole width, so the answer is
        the first and the last column of the screen. Every caller then
        reads one pair and needs no test of its own.
        """
        margins = self.horizontal_margins
        if margins is None:
            return 0, self.columns - 1
        return margins

    @property
    def reported_column(self) -> int:
        """
        The column that the cursor stands on, counted from zero.

        A character in the last column leaves the cursor one column
        further, where it waits to wrap. The cursor still stands on the
        last column, and that is the column that a report names. With a
        right margin the wait sits one column after the margin instead.

        A program can put the cursor on that column itself, and then it
        really stands there. Only the wait folds back, so the flag
        decides and not the place.
        """
        column = self.pt_cursor_position.x
        _left, right = self.left_right
        if self.pending_wrap and column == right + 1:
            return right
        return min(column, self.columns - 1)

    def _cursor_is_between_the_left_and_right_margins(self) -> bool:
        """
        True when the cursor stands in the columns of the region.

        A line feed scrolls the region only from inside it, and the
        commands that insert or delete do nothing from outside it.
        Without margins the answer is always true.
        """
        if self.horizontal_margins is None:
            return True
        left, right = self.horizontal_margins
        return left <= self.pt_cursor_position.x <= right

    def set_left_right_margins(self, *params: int, **kwargs) -> None:
        """
        DECSLRM ("CSI Pl ; Pr s"): the columns of the scrolling region.

        The sequence works only while private mode 69 (DECLRMM) is set.
        Without the mode the same final byte names SCOSC, which saves
        the cursor. So a terminal reads one byte two ways, and the mode
        says which. xterm does the same.

        A region needs two columns, the way the rows of DECSTBM do, and
        the whole width is no region at all. The cursor goes home
        afterwards, which is what DECSTBM does as well.
        """
        if PrivateMode.LEFT_RIGHT_MARGIN.flag not in self.mode:
            # SCOSC. It saves what DECSC saves, and SCORC ("CSI u")
            # brings it back.
            self.save_cursor()
            return

        left = (params[0] if len(params) > 0 else 0) or 1
        right = (params[1] if len(params) > 1 else 0) or self.columns

        left = max(1, min(left, self.columns))
        right = max(1, min(right, self.columns))
        if right - left < 1:
            return

        if left == 1 and right == self.columns:
            self.horizontal_margins = None
        else:
            self.horizontal_margins = HorizontalMargins(left - 1, right - 1)

        self.cursor_position()

    def _reset_offset_and_margins(self) -> None:
        """
        Recalculate offset and move cursor (make sure that the bottom is
        visible.)
        """
        self.margins = None
        self.horizontal_margins = None

    def define_charset(self, code: str, mode: str = "(") -> None:
        """Define the ``G0`` or the ``G1`` charset.

        :param str code: character set code, should be a character
                         from ``"B0UK"`` -- otherwise ignored.
        :param str mode: if ``"("`` ``G0`` charset is set, if
                         ``")"`` -- we operate on ``G1``.

        ``ESC ( 0`` picks the line drawing set of the DEC terminals,
        which is how a program without a Unicode font draws a box.

        .. warning:: User-defined charsets are currently not supported.
        """
        if code in cs.MAPS:
            charset_map = cs.MAPS[code]
            if mode == "(":
                self.g0_charset = charset_map
            elif mode == ")":
                self.g1_charset = charset_map

    def set_mode(self, *modes, **kwargs) -> None:
        # Private mode codes are shifted, to be distingiushed from non
        # private ones.
        if kwargs.get("private"):
            modes = tuple(mode << 5 for mode in modes)

        self.mode.update(modes)

        if PrivateMode.CURSOR_BLINK.flag in modes:
            self.set_cursor_blink(True)

        if PrivateMode.SAVE_CURSOR.flag in modes:
            self.save_cursor()

        # The program asked to be told the size in band. Tell it now,
        # so that it need not ask separately. (kitty answers a repeated
        # set the same way.)
        if PrivateMode.INBAND_RESIZE.flag in modes:
            self.notify_of_resize()

        # When DECOLM mode is set, the screen is erased and the cursor
        # moves to the home position.
        if mo.DECCOLM in modes:
            self.resize(columns=132)
            self.erase_in_display(2)
            self.cursor_position()

        # According to `vttest`, DECOM should also home the cursor, see
        # vttest/main.c:303.
        if mo.DECOM in modes:
            self.cursor_position()

        # Make the cursor visible.
        if mo.DECTCEM in modes:
            self.pt_screen.show_cursor = True

        # On "\e[?1049h", enter alternate screen mode. Backup the current
        # state. "?47" and "?1047" name the same screen; they are what a
        # program that predates "?1049" sends.
        taken_by = self._alternate_screen_modes(modes)
        if taken_by and not self._original_screen:
            # "?1049" saves the cursor of the first screen, the same
            # way "ESC 7" does: the place, the rendition and the
            # character sets all come back with it. The two older modes
            # save nothing.
            if PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag in taken_by:
                self.save_cursor()

            self._original_screen = self.pt_screen
            self._original_screen_vars = {
                v: getattr(self, v) for v in self.swap_variables
            }
            # The scrolling region belongs to the terminal and not to
            # one of its screens, so it survives the switch. xterm and
            # kitty both keep it.
            margins = self.margins
            horizontal_margins = self.horizontal_margins

            # "?1049" clears the screen it takes. The two older modes
            # do not, so they find what the last visit left.
            keeps_the_content = (
                PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag not in taken_by
                and self._alternate_screen is not None
            )
            if keeps_the_content:
                self.pt_screen = self._alternate_screen
                for name, value in self._alternate_screen_vars.items():
                    setattr(self, name, value)
                self._alternate_screen = None
                self._alternate_screen_vars = {}

                # The cursor is not part of what the screen held. Taking
                # the screen puts it home, the same way taking a screen
                # that is cleared does.
                self.pt_cursor_position.y = self.line_offset
                self.pt_cursor_position.x = 0
                self.pending_wrap = False
                # A screen carries no rendition and no link of its own:
                # its cells hold the ones they were drawn with.
                self._reset_rendition()
            else:
                self._reset_screen()
                # A list of its own, because a save writes into the
                # list that is there rather than making a new one.
                self.savepoints = []

                # The alternate screen has its own, empty kitty keyboard
                # flag stack and its own graphics state. (The main screen
                # state is restored by the swap variables when leaving
                # the alternate screen.)
                self.kitty_flags_stack = ()
                self.graphics = GraphicsState()

            self.margins = margins
            self.horizontal_margins = horizontal_margins

    def reset_mode(self, *modes_args, **kwargs) -> None:
        """Resets (disables) a given list of modes.

        :param list modes: modes to reset -- hopefully, each mode is a
                           constant from :mod:`pyte.modes`.
        """
        modes = list(modes_args)

        # Private mode codes are shifted, to be distingiushed from non
        # private ones.
        if kwargs.get("private"):
            modes = [mode << 5 for mode in modes]

        self.mode.difference_update(modes)

        if PrivateMode.CURSOR_BLINK.flag in modes:
            self.set_cursor_blink(False)

        if PrivateMode.SAVE_CURSOR.flag in modes:
            self.restore_cursor()

        # DECLRMM off takes the columns of the region away. The region
        # is the whole width again, and a later DECSLRM does nothing
        # until a program sets the mode again.
        if PrivateMode.LEFT_RIGHT_MARGIN.flag in modes:
            self.horizontal_margins = None

        # Lines below follow the logic in :meth:`set_mode`.
        if mo.DECCOLM in modes:
            self.resize(columns=80)
            self.erase_in_display(2)
            self.cursor_position()

        if mo.DECOM in modes:
            self.cursor_position()

        # Hide the cursor.
        if mo.DECTCEM in modes:
            self.pt_screen.show_cursor = False

        # On "\e[?1049l", restore from alternate screen mode. "?47" and
        # "?1047" give the screen back as well.
        given_back = self._alternate_screen_modes(modes)
        if self._original_screen and given_back:
            restores_the_cursor = (
                PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag in given_back
            )
            row = self.pt_cursor_position.y - self.line_offset
            column = self.pt_cursor_position.x

            # The screen that is given back is kept, not thrown away:
            # a terminal has one alternate screen for its whole life
            # and hands it back with what it held. "?1047" is the
            # exception. xterm clears the alternate screen before it
            # switches back, and libvterm does the same; kitty keeps it.
            if PrivateMode.ALTERNATE_SCREEN_AGAIN.flag in given_back:
                self._alternate_screen = None
                self._alternate_screen_vars = {}
            else:
                self._alternate_screen = self.pt_screen
                self._alternate_screen_vars = {
                    name: getattr(self, name) for name in self.swap_variables
                }

            for k, v in self._original_screen_vars.items():
                setattr(self, k, v)
            self.pt_screen = self._original_screen

            self._original_screen = None
            self._original_screen_vars = {}

            # A link that the program on the alternate screen left open
            # belongs to that screen. Without this, everything the shell
            # writes afterwards is a link to whatever it opened.
            self.set_hyperlink("")

            if restores_the_cursor:
                # The same as "ESC 8". With nothing saved it is the
                # home position, and the character sets of the start.
                self.restore_cursor()
            else:
                # "?47" and "?1047" save no cursor, so the cursor stays
                # where the program that drew the alternate screen left
                # it.
                self.pt_cursor_position.y = row + self.line_offset
                self.pt_cursor_position.x = column
                self.ensure_bounds()

    #: The private modes that name the alternate screen. "?1049" also
    #: saves the cursor; the two older ones do not.
    _ALTERNATE_SCREEN_MODES = (
        PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag,
        PrivateMode.ALTERNATE_SCREEN_AGAIN.flag,
        PrivateMode.ALTERNATE_SCREEN.flag,
    )

    @classmethod
    def _alternate_screen_modes(cls, modes) -> "List[int]":
        "The modes of this list that name the alternate screen."
        return [mode for mode in cls._ALTERNATE_SCREEN_MODES if mode in modes]

    @property
    def in_alternate_screen(self) -> bool:
        return bool(self._original_screen)

    def shift_in(self) -> None:
        "Activates ``G0`` character set."
        self.charset = 0

    def shift_out(self) -> None:
        "Activates ``G1`` character set."
        self.charset = 1

    def repair_wide_char(self, row, column: int) -> None:
        """
        Take away the half of a double width character that an edit at
        `column` leaves on its own.

        A double width character lives in two cells: the character in
        the first and an empty string in the second. An edit that
        touches one of the two leaves half a character behind. No
        terminal draws that, so the other half goes away as well.

        The two cells around `column` are the ones an edit can break:
        the cell before it and the cell itself.
        """
        columns = self.columns
        for position in (column - 1, column):
            if position < 0 or position >= columns:
                continue
            cell = row.get(position)
            if cell is None:
                continue
            if cell.width > 1:
                # The empty second half has to follow.
                after = row.get(position + 1)
                if position + 1 >= columns or after is None or after.char != "":
                    row.pop(position, None)
            elif cell.char == "":
                # The character has to come before.
                before = row.get(position - 1)
                if position == 0 or before is None or before.width < 2:
                    row.pop(position, None)

    def draw(self, chars: str) -> None:
        """
        Draw characters.
        `chars` is supposed to *not* contain any special characters.
        No newlines or control codes.
        """
        # Aliases for variables that are used more than once in this function.
        # Local lookups are always faster.
        # (This draw function is called for every printable character that a
        # process outputs; it should be as performant as possible.)
        pt_screen = self.pt_screen
        data_buffer = pt_screen.data_buffer
        cursor_position = self.pt_cursor_position
        cursor_position_x = cursor_position.x
        cursor_position_y = cursor_position.y

        in_irm = mo.IRM in self.mode
        char_cache = _CHAR_CACHE
        columns = self.columns
        wide_chars = self._wide_chars
        _left, right_margin = self.left_right

        # The marks that SPA and DECSCA put on what comes next. Nearly
        # no program sets one, so the cells stay in the cache that
        # holds no mark and cost nothing.
        protection = self.protection
        if protection:
            char_cache = _PROTECTED_CHAR_CACHE
            key_tail = (self._style_str, protection)
            self._protected_chars = True
        else:
            key_tail = (self._style_str,)

        # What REP repeats. It is kept before the translation, so that
        # a repeat travels the same road the character did.
        if chars:
            self.last_character = chars[-1]

        # Translating a given character.
        if self.charset:
            chars = chars.translate(self.g1_charset)
        else:
            chars = chars.translate(self.g0_charset)

        style = self._style_str

        # The column after the last one a character may take. The loop
        # works it out for each character it draws.
        edge = columns

        # Only the first character of a run can find the cursor waiting
        # to wrap. After that the loop has placed the cursor itself.
        waiting_to_wrap = self.pending_wrap

        for char in chars:
            # Create 'Char' instance.
            pt_char = char_cache[(char,) + key_tail]
            char_width = pt_char.width

            # A character that does not fit in what is left of the line
            # goes to the next line when auto wrap mode is on, and takes
            # the place at the right edge when it is off. A double width
            # character needs two columns, so it moves one column
            # earlier than a narrow one.
            #
            # A right margin is the edge of the line. A cursor that
            # stands right of the margin keeps the edge of the screen,
            # because a program that draws there draws outside the
            # region.
            # The column after the margin is where the wait to wrap
            # sits, so a cursor that waits there counts as inside. A
            # cursor that a program put on that column does not.
            if cursor_position_x <= right_margin or (
                waiting_to_wrap and cursor_position_x == right_margin + 1
            ):
                edge = right_margin + 1
            else:
                edge = columns

            if char_width > 0 and cursor_position_x + char_width > edge:
                if mo.DECAWM in self.mode:
                    # The moves below read the cursor from the screen,
                    # and this loop keeps it in a local. Write it back
                    # first, so that a carriage return finds the column
                    # that the last character left.
                    cursor_position.x = cursor_position_x
                    self.carriage_return()
                    self.linefeed()
                    cursor_position = self.pt_cursor_position
                    cursor_position_x = cursor_position.x
                    cursor_position_y = cursor_position.y

                    self.wrapped_lines.append(cursor_position_y)
                else:
                    cursor_position_x = edge - char_width

            # If Insert mode is set, new characters move old characters to
            # the right, otherwise terminal is in Replace mode and new
            # characters replace old characters at cursor position.
            if in_irm:
                cursor_position.x = cursor_position_x
                self.insert_characters(max(0, char_width))

            row = data_buffer[cursor_position_y]
            if char_width == 1:
                # A write over one half of a double width character
                # leaves the other half on its own. Only a cell that
                # holds a half needs the repair, so the test stays
                # here, and a screen that never saw such a character
                # does not even look.
                if wide_chars:
                    broken = row.get(cursor_position_x)
                    row[cursor_position_x] = pt_char
                    if broken is not None and (
                        broken.char == "" or broken.width > 1
                    ):
                        self.repair_wide_char(row, cursor_position_x)
                        self.repair_wide_char(row, cursor_position_x + 1)
                else:
                    row[cursor_position_x] = pt_char
            elif char_width > 1:  # 2
                # Double width character. Put an empty string in the second
                # cell, because this is different from every character and
                # causes the render engine to clear this character, when
                # overwritten.
                row[cursor_position_x] = pt_char
                row[cursor_position_x + 1] = char_cache[("",) + key_tail]
                self.repair_wide_char(row, cursor_position_x)
                self.repair_wide_char(row, cursor_position_x + 2)
                if not wide_chars:
                    wide_chars = self._wide_chars = True
            elif char_width == 0:
                # A mark of no width of its own belongs to the character
                # before it. See:
                # https://en.wikipedia.org/wiki/Unicode_equivalence
                # The cell before can be the empty second half of a
                # double width character. The character itself then sits
                # one cell further back.
                previous = cursor_position_x - 1
                cell = row.get(previous)
                if cell is not None and cell.char == "":
                    previous -= 1
                    cell = row.get(previous)
                # A cell that an erase left holds no character, so a
                # mark has nothing to hang on and goes away. kitty and
                # WezTerm both drop it there.
                if (
                    previous >= 0
                    and cell is not None
                    and not isinstance(cell, ErasedChar)
                ):
                    # The mark belongs to the cell that is there, so it
                    # keeps the marks of that cell and not the ones
                    # that are set now.
                    marks = protection_of(cell)
                    if marks:
                        row[previous] = _PROTECTED_CHAR_CACHE[
                            cell.char + pt_char.char, cell.style, marks
                        ]
                    else:
                        row[previous] = _CHAR_CACHE[
                            cell.char + pt_char.char, cell.style
                        ]
            else:  # char_width < 0
                # (Should not happen.)
                char_width = 0

            # .. note:: We can't use :meth:`cursor_forward()`, because that
            #           way, we'll never know when to linefeed.
            cursor_position_x += char_width

            # This character filled the edge column, so the next one
            # starts the line below.
            waiting_to_wrap = cursor_position_x >= edge

        # Update max_y. (Don't use 'max()' for comparing only two values, that
        # is less efficient.)
        if cursor_position_y > self.max_y:
            self.max_y = cursor_position_y

        cursor_position.x = cursor_position_x
        # A run that draws nothing leaves the wait as it was.
        if chars:
            self.pending_wrap = waiting_to_wrap

    def _leave_the_pending_wrap(self) -> None:
        """
        Bring a cursor that sits past the last column back onto it.

        A character written in the last column leaves the cursor one
        column further, which is what makes the next character wrap.
        A move of the cursor ends that wait, so the cursor lands on the
        last column and not past it.

        With a right margin the wait sits one column after the margin,
        which is a column of the screen like any other. So the flag
        says where the cursor came from, and the place does not.
        """
        if self.pending_wrap:
            self.pt_cursor_position.x -= 1
            self.pending_wrap = False

    def carriage_return(self) -> None:
        """
        Move the cursor to the beginning of the current line.

        With a left margin the beginning is the margin. A cursor that
        stands left of the margin goes to the first column instead, so
        a program that draws outside the region keeps that column.
        """
        left, _right = self.left_right
        if self.pt_cursor_position.x < left:
            left = 0
        self.pt_cursor_position.x = left
        # A move of the cursor ends the wait to wrap.
        self.pending_wrap = False

    def index(self) -> None:
        """Move the cursor down one line in the same column. If the
        cursor is at the last line, create a new line at the bottom.
        """
        # A character at the right edge leaves the cursor one column
        # past the line, which is where the next one wraps from. A move
        # down takes the cursor out of that place: the column it lands
        # in is the last one.
        self._leave_the_pending_wrap()

        margins = self.margins

        # When scrolling over the full screen height -> keep history.
        # A left or a right margin makes the region narrower than the
        # screen, and a rectangle carries no history.
        if margins is None and self.horizontal_margins is None:
            # Simply move the cursor one position down.
            cursor_position = self.pt_cursor_position
            cursor_position.y += 1
            self.max_y = max(self.max_y, cursor_position.y)

            # Cleanup the history, but only every 100 calls.
            self._history_cleanup_counter += 1
            if self._history_cleanup_counter == 100:
                self._remove_old_lines_from_history()
                self._history_cleanup_counter = 0
        else:
            # Move cursor down, but scroll in the scrolling region.
            top, bottom = margins or Margins(0, self.lines - 1)

            if self.pt_cursor_position.y - self.line_offset != bottom:
                self.cursor_down()
            elif self._cursor_is_between_the_left_and_right_margins():
                self._move_rows(top, bottom, 1)
            # Outside the columns of the region the cursor stays where
            # it is, and nothing scrolls.

    def scroll_up(self, count: int | None = None) -> None:
        """
        SU ("CSI Ps S"): move the lines of the scrolling region up.

        The cursor does not move. This is what a program sends to
        scroll a region without a linefeed.
        """
        self._scroll_region(count or 1)

    def scroll_down(self, count: int | None = None) -> None:
        """
        SD ("CSI Ps T"): move the lines of the scrolling region down.

        The cursor does not move.
        """
        self._scroll_region(-(count or 1))

    def _scroll_region(self, amount: int) -> None:
        """
        Move the lines of the scrolling region by `amount`.

        A positive amount moves them up, which is what SU asks for. The
        lines that come in are empty, and the ones that go out are
        dropped, so this keeps no history.
        """
        top, bottom = self.margins or Margins(0, self.lines - 1)
        self._move_rows(top, bottom, amount)

    def _move_rows(self, top: int, bottom: int, amount: int) -> None:
        """
        Move the rows from `top` to `bottom` by `amount` rows.

        A positive amount moves them up. The rows that come in are
        empty, and the ones that go out are dropped, so this keeps no
        history. The rows are counted from the top of the screen.

        Left and right margins hold the move to the columns between
        them. The cells outside them stay where they are, so the move
        carries a rectangle and not whole lines.
        """
        steps = min(abs(amount), bottom - top + 1)
        if steps == 0:
            return

        if amount > 0:
            rows = range(top, bottom + 1)
            source = steps
        else:
            rows = range(bottom, top - 1, -1)
            source = -steps

        line_offset = self.line_offset
        data_buffer = self.data_buffer
        horizontal = self.horizontal_margins

        for row in rows:
            origin = row + source
            inside = top <= origin <= bottom

            if horizontal is None:
                if inside:
                    data_buffer[row + line_offset] = data_buffer[
                        origin + line_offset
                    ]
                else:
                    self._erase_row(row + line_offset)
            elif inside:
                self._copy_columns(
                    data_buffer[origin + line_offset],
                    data_buffer[row + line_offset],
                    horizontal,
                )
            else:
                self._erase_columns(data_buffer[row + line_offset], horizontal)

        if horizontal is None:
            # Graphics placements scroll with the text. An image sits on
            # whole lines, so it moves only when whole lines move.
            self.graphics.scroll(top + line_offset, bottom + line_offset, amount)

    def _copy_columns(self, source, target, horizontal: HorizontalMargins) -> None:
        "Copy the cells between the margins from one row to another."
        left, right = horizontal
        for column in range(left, right + 1):
            cell = source.get(column)
            if cell is None:
                target.pop(column, None)
            else:
                target[column] = cell

    def _erase_columns(self, row, horizontal: HorizontalMargins) -> None:
        """
        Make the cells between the margins empty.

        They take the background that is set now, the same way an
        erased cell does.
        """
        left, right = horizontal
        style = self.erase_style()

        if style:
            blank = ErasedChar(" ", style)
            for column in range(left, right + 1):
                row[column] = blank
        else:
            for column in range(left, right + 1):
                row.pop(column, None)

    def _remove_old_lines_from_history(self) -> None:
        """
        Remove top from the scroll buffer. (Outside bounds of history limit.)
        """
        remove_above = max(0, self.pt_cursor_position.y - self.get_history_limit())
        data_buffer = self.pt_screen.data_buffer
        for line in list(data_buffer):
            if line < remove_above:
                data_buffer.pop(line, None)
        self.graphics.prune_above(remove_above)

    def clear_history(self) -> None:
        """
        Delete all history from the scroll buffer.
        """
        for line in list(self.data_buffer):
            if line < self.line_offset:
                self.data_buffer.pop(line, None)

    def reverse_index(self) -> None:
        top, bottom = self.margins or Margins(0, self.lines - 1)

        if self.pt_cursor_position.y - self.line_offset != top:
            self.cursor_up()
        elif self._cursor_is_between_the_left_and_right_margins():
            self._move_rows(top, bottom, -1)
        # Outside the columns of the region the cursor stays where it
        # is, and nothing scrolls.

    def linefeed(self) -> None:
        """Performs an index and, if :data:`~pyte.modes.LNM` is set, a
        carriage return.
        """
        self.index()

        if mo.LNM in self.mode:
            self.carriage_return()

    def next_line(self) -> None:
        """When `EscE` has been received. Go to the next line, even when LNM has
        not been set."""
        self.index()
        self.carriage_return()
        self.ensure_bounds()

    def tab(self) -> None:
        """Move to the next tab stop, or to the last column when no stop
        is left on the line.

        The tab stops do not know how wide the screen is, so a stop can
        sit past the last column. The last column stops the cursor: a
        tab never moves it off the line.

        A cursor that already sits past the last column waits to wrap.
        A tab leaves that wait alone, so the next character starts the
        line below. Every other cursor move ends the wait. This one
        does not. kitty, WezTerm, Alacritty and libvterm all agree.
        """
        cursor_position = self.pt_cursor_position
        if self.pending_wrap:
            return

        # With a right margin the tab stops there, and not at the last
        # column. That holds even for a cursor that starts left of the
        # left margin: the DEC terminals stop a tab at the margin, and
        # xterm does the same.
        _left, right = self.left_right
        last = right if cursor_position.x <= right else self.columns - 1
        for stop in sorted(self.tabstops):
            if cursor_position.x < stop:
                column = min(stop, last)
                break
        else:
            column = last

        cursor_position.x = column

    def cursor_to_next_tab(self, count: int | None = None) -> None:
        """
        CHT ("CSI Ps I"): move forward over `count` tab stops.

        pyte has no handler for it. ncurses uses it to reach a column
        without drawing the blanks in between.
        """
        for _ in range(count or 1):
            self.tab()

    def cursor_to_previous_tab(self, count: int | None = None) -> None:
        """
        CBT ("CSI Ps Z"): move back over `count` tab stops.

        The first column stops the cursor, the way the last column
        stops a tab.
        """
        for _ in range(count or 1):
            for stop in sorted(self.tabstops, reverse=True):
                if stop < self.pt_cursor_position.x:
                    column = stop
                    break
            else:
                column = 0
            self.pt_cursor_position.x = column

    def repeat_last_character(self, count: int | None = None) -> None:
        """
        REP ("CSI Pn b"): draw the last character again, `count` times.

        It saves a program the bytes of a run of one character, which
        is what a box or a rule is made of.

        The repeat goes through `draw`, so it wraps at the right
        margin and scrolls at the bottom one exactly the way the
        typing would have. ECMA-48 says nothing about margins; xterm
        reads it this way to match the rest of the terminal, and
        esctest2 asks for it.

        A repeat before anything is drawn draws nothing. There is no
        character to repeat, and a space would be a guess.
        """
        if self.last_character:
            self.draw(self.last_character * (count or 1))

    def backspace(self) -> None:
        """
        Move the cursor one column left.

        In the first column it normally stays where it is. Two private
        modes send it to the end of the line above instead, which lets
        a program rub out a line it wrapped:

        - "?45" goes back only when the line was reached by wrapping.
          A backspace then undoes what the typing did, and stops where
          the typing began.
        - "?1045" goes back from any line, and from the first line of
          the region to the last. xterm did this under "?45" until it
          split the two apart in 2023.

        Both need DECAWM. A terminal that does not wrap forward has
        nothing to unwrap.
        """
        # A cursor that waits to wrap sits one column past the last one
        # it wrote, so leaving the wait is itself a move left. With a
        # reverse wrap mode on, that move is the whole backspace and
        # the cursor stays on the character it wrote. Without one the
        # backspace goes on to the character before it.
        #
        # xterm asks for both: `test_BS_CursorStartsInDoWrapPosition`
        # writes "ab", backspaces and writes "X" for "Xb", and
        # `test_BS_ReverseWrapStartingInDoWrapPosition` does the same
        # with the mode on for "aX".
        if self.pending_wrap:
            self._leave_the_pending_wrap()
            if self._reverse_wrap_mode() is not None:
                return

        if self._backspace_wraps():
            return
        self.cursor_back()

    def _reverse_wrap_mode(self) -> PrivateMode | None:
        """
        The reverse wrap mode that is on, or `None` when neither is.

        Both need DECAWM: a terminal that does not wrap forward has
        nothing to unwrap. The wider mode wins when both are set.
        """
        if mo.DECAWM not in self.mode:
            return None
        if PrivateMode.REVERSE_WRAP_ANYWHERE.flag in self.mode:
            return PrivateMode.REVERSE_WRAP_ANYWHERE
        if PrivateMode.REVERSE_WRAP.flag in self.mode:
            return PrivateMode.REVERSE_WRAP
        return None

    def _backspace_wraps(self) -> bool:
        """
        Send the cursor to the end of the line above, and say whether
        it went.

        The line above ends at the right margin, because that is where
        the wrap that put the cursor here came from.
        """
        mode = self._reverse_wrap_mode()
        if mode is None:
            return False
        anywhere = mode is PrivateMode.REVERSE_WRAP_ANYWHERE

        cursor_position = self.pt_cursor_position
        left, right = self.left_right
        # The left edge counts as well as the margin. A cursor placed
        # left of the margin has nowhere to go but the line above.
        if cursor_position.x > left and cursor_position.x != 0:
            return False

        top, bottom = self.margins or Margins(0, self.lines - 1)
        row = cursor_position.y - self.line_offset
        if row > top:
            if not anywhere and cursor_position.y not in self.wrapped_lines:
                return False  # The typing did not reach this line by wrapping.
            cursor_position.y -= 1
        elif anywhere:
            # From the top of the region back to the bottom of it.
            cursor_position.y = bottom + self.line_offset
        else:
            return False

        cursor_position.x = right
        self.pending_wrap = False
        return True

    def save_cursor(self) -> None:
        """
        Remember the cursor, so that a restore can bring it back.

        A terminal remembers one cursor, not a stack of them: a second
        save replaces the first, and a restore leaves what it read in
        place, so two restores in a row give the same answer. kitty and
        xterm both work that way.
        """
        self.savepoints[:] = [
            _Savepoint(
                self.pt_cursor_position.x,
                # The row within the screen, not within the buffer. A
                # save remembers a place on the screen, so a scroll
                # between the save and the restore must not drag the
                # cursor back into the history.
                self.pt_cursor_position.y - self.line_offset,
                self.g0_charset,
                self.g1_charset,
                self.charset,
                mo.DECOM in self.mode,
                # DECAWM is not here. xterm does not bring the wrap
                # back on a restore, and its own suite asks for that:
                # a save with the wrap on, a reset, and a restore
                # leaves the wrap off.
                self._attrs,
                # The rendition alone. A hyperlink is not part of the
                # cursor that "ESC 7" remembers.
                self._rendition_str,
                self.protection,
            )
        ]

    def restore_cursor(self) -> None:
        """
        Bring back the cursor that a save remembered.

        The saved cursor stays, so a second restore gives the same
        answer as the first.
        """
        if self.savepoints:
            savepoint = self.savepoints[-1]

            self.g0_charset = savepoint.g0_charset
            self.g1_charset = savepoint.g1_charset
            self.charset = savepoint.charset
            self._attrs = savepoint.attrs
            self._rendition_str = savepoint.style_str
            self.protection = savepoint.protection
            self._rebuild_style()

            # Origin mode is part of the cursor, so it comes back the
            # way it was saved. Both ways: a save with the mode off
            # takes the mode off again.
            if savepoint.origin:
                self.set_mode(mo.DECOM)
            else:
                self.reset_mode(mo.DECOM)

            # `line_offset` follows the cursor, so read it before the
            # cursor moves.
            line_offset = self.line_offset

            self.pt_cursor_position.x = savepoint.cursor_x
            self.pt_cursor_position.y = savepoint.cursor_y + line_offset
            # Only the screen bounds hold the cursor here. A restore
            # brings back the place that was saved, which may sit
            # outside the margins that are set now: "CSI r" homes the
            # cursor, so a save from before it is usually above the top
            # margin. kitty and xterm both keep it there.
            self.ensure_bounds()
        else:
            # Nothing was saved, so the restore brings back the state
            # that a terminal starts with: the home position, no origin
            # mode and the character sets of the start. kitty does the
            # same. :todo: DECAWM?
            self.reset_mode(mo.DECOM)
            self.g0_charset = cs.LAT1_MAP
            self.g1_charset = cs.LAT1_MAP
            self.charset = 0
            self.cursor_position()

    def _erase_row(self, row: int) -> None:
        """
        Make the absolute row `row` an empty row.

        A row takes the background that is set now, the same way an
        erased cell does. Without a background the row can go away,
        which keeps the screen sparse.
        """
        data_buffer = self.data_buffer
        style = self.erase_style()

        if not style:
            data_buffer.pop(row, None)
            return

        line: DefaultDict[int, Char] = defaultdict(lambda: Char(" "))
        erased = ErasedChar(" ", style)
        for column in range(self.columns):
            line[column] = erased
        data_buffer[row] = line

    def insert_lines(self, count: int | None = None) -> None:
        """Inserts the indicated # of lines at line with cursor. Lines
        displayed **at** and below the cursor move down. Lines moved
        past the bottom margin are lost.

        :param count: number of lines to delete.
        """
        count = count or 1
        top, bottom = self.margins or Margins(0, self.lines - 1)
        first = self.pt_cursor_position.y - self.line_offset

        # The cursor has to stand inside the region, in both the rows
        # and the columns of it. Outside it, IL does nothing.
        if not top <= first <= bottom:
            return
        if not self._cursor_is_between_the_left_and_right_margins():
            return

        self._move_rows(first, bottom, -count)
        self.carriage_return()

    def delete_lines(self, count: int | None = None) -> None:
        """Deletes the indicated # of lines, starting at line with
        cursor. As lines are deleted, lines displayed below cursor
        move up. Lines added to bottom of screen have spaces with same
        character attributes as last line moved up.

        :param int count: number of lines to delete.
        """
        count = count or 1
        top, bottom = self.margins or Margins(0, self.lines - 1)
        first = self.pt_cursor_position.y - self.line_offset

        # The cursor has to stand inside the region, in both the rows
        # and the columns of it. Outside it, DL does nothing.
        if not top <= first <= bottom:
            return
        if not self._cursor_is_between_the_left_and_right_margins():
            return

        self._move_rows(first, bottom, count)

        # DL moves the cursor to the first column, the same way IL does.
        self.carriage_return()

    def insert_characters(self, count: int | None = None) -> None:
        """Inserts the indicated # of blank characters at the cursor
        position. The cursor does not move and remains at the beginning
        of the inserted blank characters. Data on the line is shifted
        forward.

        :param int count: number of characters to insert.

        A right margin is the edge of the line, and the cells after it
        stay where they are. From outside the margins ICH does nothing.
        """
        count = count or 1
        cursor_x = self.pt_cursor_position.x
        left, right = self.left_right
        if not left <= cursor_x <= right:
            return

        edge = right + 1
        line = self.data_buffer[self.pt_cursor_position.y]

        # Move what sits at and after the cursor to the right. What
        # falls off the right edge is lost.
        moved = {}
        for column in list(line.keys()):
            if column < cursor_x or column > right:
                continue
            cell = line.pop(column)
            if column + count < edge:
                moved[column + count] = cell
        line.update(moved)

        style = self.erase_style()
        if style:
            blank = ErasedChar(" ", style)
            for column in range(cursor_x, min(cursor_x + count, edge)):
                line[column] = blank

        # The cursor and the right edge are where a double width
        # character can lose half of itself.
        self.repair_wide_char(line, cursor_x)
        self.repair_wide_char(line, edge)

    def delete_characters(self, count: int | None = None) -> None:
        """
        DCH ("CSI Ps P"): delete characters at the cursor.

        A right margin is the edge of the line, and the cells after it
        stay where they are. From outside the margins DCH does nothing.
        """
        count = count or 1
        cursor_x = self.pt_cursor_position.x
        left, right = self.left_right
        if not left <= cursor_x <= right:
            return

        edge = right + 1
        line = self.data_buffer[self.pt_cursor_position.y]

        # Move what sits after the deleted characters to the left.
        moved = {}
        for column in list(line.keys()):
            if column < cursor_x or column > right:
                continue
            cell = line.pop(column)
            if column - count >= cursor_x:
                moved[column - count] = cell
        line.update(moved)

        style = self.erase_style()
        if style:
            blank = ErasedChar(" ", style)
            for column in range(max(cursor_x, edge - count), edge):
                line[column] = blank

        self.repair_wide_char(line, cursor_x)
        self.repair_wide_char(line, max(cursor_x, edge - count))

    def cursor_position(
        self, line: int | None = None, column: int | None = None
    ) -> None:
        """Set the cursor to a specific `line` and `column`.

        Cursor is allowed to move out of the scrolling region only when
        :data:`~pyte.modes.DECOM` is reset, otherwise -- the position
        doesn't change.

        :param int line: line number to move the cursor to.
        :param int column: column number to move the cursor to.
        """
        column = (column or 1) - 1
        line = (line or 1) - 1

        # If origin mode (DECOM) is set, line number are relative to
        # the top scrolling margin.
        margins = self.margins

        if margins is not None and mo.DECOM in self.mode:
            line += margins.top

            # Cursor is not allowed to move out of the scrolling region.
            if not (margins.top <= line <= margins.bottom):
                return

        column = self._column_in_origin_mode(column)

        self.pt_cursor_position.x = column
        self.pt_cursor_position.y = line + self.line_offset
        self.ensure_bounds()

    def _column_in_origin_mode(self, column: int) -> int:
        """
        Read a column that a program counted from the left margin.

        In origin mode the region is the whole page that a program
        sees, so column one is the left margin and the right margin
        holds the cursor. Without the mode, or without margins, the
        column is the column of the screen.
        """
        margins = self.horizontal_margins
        if margins is None or mo.DECOM not in self.mode:
            return column
        return min(column + margins.left, margins.right)

    def cursor_to_column(self, column: int | None = None) -> None:
        """
        CHA ("CSI Ps G"): move to a column of the current line.

        The column is counted from the left margin in origin mode.
        HPA names the column of the screen instead, and
        `cursor_to_absolute_column` serves it.

        :param int column: column number to move the cursor to.
        """
        self.pt_cursor_position.x = self._column_in_origin_mode(
            (column or 1) - 1
        )
        self.ensure_bounds()

    def cursor_to_absolute_column(self, column: int | None = None) -> None:
        """
        HPA ("CSI Ps `"): move to a column of the screen.

        Origin mode does not change this one. CHA reads the same
        parameter from the left margin, and HPA reads it from the edge
        of the screen. xterm draws the line that way.

        :param int column: column number to move the cursor to.
        """
        self.pt_cursor_position.x = (column or 1) - 1
        self.ensure_bounds()

    def cursor_to_line(self, line: int | None = None) -> None:
        """Moves cursor to a specific line in the current column.

        :param int line: line number to move the cursor to.
        """
        self.pt_cursor_position.y = (line or 1) - 1 + self.line_offset

        # If origin mode (DECOM) is set, line number are relative to
        # the top scrolling margin.
        margins = self.margins

        if mo.DECOM in self.mode and margins is not None:
            self.pt_cursor_position.y += margins.top

            # FIXME: should we also restrict the cursor to the scrolling
            # region?

        self.ensure_bounds()

    def bell(self, *args) -> None:
        "Bell"
        self.bell_func()

    def cursor_down(self, count: int | None = None) -> None:
        """Moves cursor down the indicated # of lines in same column.
        Cursor stops at bottom margin.

        :param int count: number of lines to skip.
        """
        self._leave_the_pending_wrap()

        cursor_position = self.pt_cursor_position
        margins = self.margins or Margins(0, self.lines - 1)

        # Ensure bounds.
        # (Following code is faster than calling `self.ensure_bounds`.)
        top, bottom = margins
        row = cursor_position.y - self.line_offset
        if row < top or row > bottom:
            # Outside the region the bottom of the screen stops the
            # cursor, not the margin. Below the region the margin would
            # move the cursor up, which a move down never does. Above
            # the region it would stop the cursor too early.
            limit = self.lines - 1
        else:
            limit = bottom
        cursor_position.y = min(
            cursor_position.y + (count or 1), limit + self.line_offset
        )

        self.max_y = max(self.max_y, cursor_position.y)

    def cursor_down1(self, count: int | None = None) -> None:
        """Moves cursor down the indicated # of lines to column 1.
        Cursor stops at bottom margin.

        :param int count: number of lines to skip.
        """
        self.cursor_down(count)
        self.carriage_return()

    def cursor_up(self, count: int | None = None) -> None:
        """Moves cursor up the indicated # of lines in same column.
        Cursor stops at top margin.

        :param int count: number of lines to skip.
        """
        top, bottom = self.margins or Margins(0, self.lines - 1)
        row = self.pt_cursor_position.y - self.line_offset
        outside_the_region = row < top or row > bottom

        self.pt_cursor_position.y -= count or 1

        # Outside the region the top of the screen stops the cursor,
        # not the margin. Above the region the margin would move the
        # cursor down, and below it the margin would stop it too early.
        self.ensure_bounds(use_margins=not outside_the_region)

    def cursor_up1(self, count: int | None = None) -> None:
        """Moves cursor up the indicated # of lines to column 1. Cursor
        stops at bottom margin.

        :param int count: number of lines to skip.
        """
        self.cursor_up(count)
        self.carriage_return()

    def cursor_back(self, count: int | None = None) -> None:
        """Moves cursor left the indicated # of columns. Cursor stops
        at left margin.

        :param int count: number of columns to skip.

        The left margin stops the cursor, but only when the cursor
        starts at or right of it. Left of the margin the first column
        stops it, because the margin would move the cursor right, and
        a move left never does that.
        """
        cursor_position = self.pt_cursor_position
        left, _right = self.left_right
        if cursor_position.x < left:
            left = 0

        cursor_position.x = max(left, cursor_position.x - (count or 1))
        self.ensure_bounds()

    def cursor_forward(self, count: int | None = None) -> None:
        """Moves cursor right the indicated # of columns. Cursor stops
        at right margin.

        :param int count: number of columns to skip.

        The right margin stops the cursor, but only when the cursor
        starts at or left of it. Right of the margin the last column
        stops it.
        """
        cursor_position = self.pt_cursor_position
        _left, right = self.left_right
        if cursor_position.x > right:
            right = self.columns - 1

        cursor_position.x = min(right, cursor_position.x + (count or 1))
        self.ensure_bounds()

    def erase_style(self) -> str:
        """
        The style that an erased cell takes.

        A terminal paints an erased cell with the background that is set
        now. xterm, kitty and tmux all do this, and programs count on
        it: htop draws the header of its table with "CSI K" and expects
        the colour to reach the end of the line.

        Only what a reader can see on a blank carries over: the
        background, reverse video and an underline. An empty answer
        means that the cell can go away instead, which keeps the screen
        sparse.
        """
        attrs = self._attrs
        style = ""

        if attrs.reverse:
            # Reverse video paints the cell with the foreground.
            style += "reverse "
            if attrs.color:
                style += "%s " % attrs.color

        if attrs.bgcolor:
            style += "bg:%s " % attrs.bgcolor

        if attrs.underline:
            style += UNDERLINE_WORDS[attrs.underline_style or ""] + " "
            if attrs.underline_color:
                style += "ul:%s " % attrs.underline_color

        return style

    def erase_characters(self, count: int | None = None) -> None:
        """Erases the indicated # of characters, starting with the
        character at cursor position. Character attributes are set
        cursor attributes. The cursor remains in the same position.

        :param int count: number of characters to erase.

        .. warning::

           Even though *ALL* of the VTXXX manuals state that character
           attributes **should be reset to defaults**, ``libvte``,
           ``xterm`` and ``ROTE`` completely ignore this. Same applies
           too all ``erase_*()`` and ``delete_*()`` methods.
        """
        count = count or 1
        cursor_position = self.pt_cursor_position
        row = self.data_buffer[cursor_position.y]
        style = self.erase_style()
        erased = ErasedChar(" ", style)

        end = min(cursor_position.x + count, self.columns)
        for column in range(cursor_position.x, end):
            # ECH leaves a cell that SPA marked alone.
            cell = row.get(column)
            if cell is not None and self._erase_holds(cell, False):
                continue
            row[column] = erased

        self.repair_wide_char(row, cursor_position.x)
        self.repair_wide_char(row, end)

    def _move_columns(
        self, top: int, bottom: int, left: int, right: int, amount: int
    ) -> None:
        """
        Move the cells between `left` and `right` by `amount` columns.

        Every row from `top` to `bottom` moves, so this carries a
        rectangle. A positive amount moves the cells right, which is
        what DECIC asks for. The cells that come in are empty, and the
        ones that go past a margin are dropped.
        """
        steps = min(abs(amount), right - left + 1)
        if steps == 0:
            return

        if amount > 0:
            columns = range(right, left - 1, -1)
            source = -steps
        else:
            columns = range(left, right + 1)
            source = steps

        line_offset = self.line_offset
        data_buffer = self.data_buffer
        style = self.erase_style()
        blank = ErasedChar(" ", style) if style else None

        for row in range(top, bottom + 1):
            line = data_buffer[row + line_offset]
            for column in columns:
                origin = column + source
                cell = line.get(origin) if left <= origin <= right else None
                if cell is not None:
                    line[column] = cell
                elif blank is None:
                    line.pop(column, None)
                else:
                    line[column] = blank

            # Both edges are where a double width character can lose
            # half of itself.
            self.repair_wide_char(line, left)
            self.repair_wide_char(line, right + 1)

    def _region_holds_the_cursor(self) -> bool:
        "True when the cursor stands inside the scrolling region."
        top, bottom = self.margins or Margins(0, self.lines - 1)
        row = self.pt_cursor_position.y - self.line_offset
        if not top <= row <= bottom:
            return False
        return self._cursor_is_between_the_left_and_right_margins()

    def insert_columns(self, count: int | None = None) -> None:
        """
        DECIC ("CSI Pn ' }"): insert columns at the cursor.

        Every row of the scrolling region moves, and not the row of the
        cursor alone. The cells that go past the right margin are lost.
        From outside the region DECIC does nothing.
        """
        if not self._region_holds_the_cursor():
            return

        top, bottom = self.margins or Margins(0, self.lines - 1)
        _left, right = self.left_right
        self._move_columns(
            top, bottom, self.pt_cursor_position.x, right, count or 1
        )

    def delete_columns(self, count: int | None = None) -> None:
        """
        DECDC ("CSI Pn ' ~"): delete columns at the cursor.

        Every row of the scrolling region moves, the way DECIC moves
        them. From outside the region DECDC does nothing.
        """
        if not self._region_holds_the_cursor():
            return

        top, bottom = self.margins or Margins(0, self.lines - 1)
        _left, right = self.left_right
        self._move_columns(
            top, bottom, self.pt_cursor_position.x, right, -(count or 1)
        )

    def forward_index(self) -> None:
        """
        DECFI ("ESC 9"): move the cursor one column to the right.

        At the right margin the cursor stays, and the region moves one
        column to the left instead. Right of the margin the cursor
        moves on its own until the edge of the screen stops it.

        A cursor that waits to wrap past the last column stands on the
        last column, so it moves the region as well.
        """
        cursor_position = self.pt_cursor_position
        _left, right = self.left_right
        # A cursor that waits to wrap stands on the column before it.
        if self.pending_wrap:
            column = cursor_position.x - 1
        else:
            column = min(cursor_position.x, self.columns - 1)

        if column == right:
            top, bottom = self.margins or Margins(0, self.lines - 1)
            self._move_columns(top, bottom, *self.left_right, -1)
        elif column < self.columns - 1:
            cursor_position.x = column + 1
        self.pending_wrap = False

    def back_index(self) -> None:
        """
        DECBI ("ESC 6"): move the cursor one column to the left.

        At the left margin the cursor stays, and the region moves one
        column to the right instead. Left of the margin the cursor
        moves on its own until the first column stops it.
        """
        cursor_position = self.pt_cursor_position
        left, _right = self.left_right

        if cursor_position.x == left:
            top, bottom = self.margins or Margins(0, self.lines - 1)
            self._move_columns(top, bottom, *self.left_right, 1)
        elif cursor_position.x > 0:
            cursor_position.x -= 1
        self.pending_wrap = False

    def erase_in_line(self, type_of: int = 0, private: bool = False) -> None:
        """Erases a line in a specific way.

        :param int type_of: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of line, including cursor
              position.
            * ``1`` -- Erases from beginning of line to cursor,
              including cursor position.
            * ``2`` -- Erases complete line.
        :param bool private: ``True`` for DECSEL ("CSI ? Ps K"), the
                             selective erase. It leaves a cell that
                             DECSCA marked alone; EL does not.
        """
        data_buffer = self.data_buffer
        pt_cursor_position = self.pt_cursor_position
        style = self.erase_style()

        if type_of == 0:
            columns = range(pt_cursor_position.x, self.columns)
        elif type_of == 1:
            columns = range(0, pt_cursor_position.x + 1)
        else:
            columns = range(0, self.columns)

        line = data_buffer[pt_cursor_position.y]
        holds = self._erase_holds
        erased = ErasedChar(" ", style) if style else None

        for column in columns:
            cell = line.get(column)
            if cell is not None and holds(cell, private is True):
                continue
            if erased is None:
                line.pop(column, None)
            else:
                line[column] = erased

        if erased is None and not line:
            # The line holds nothing, so it can go away and keep the
            # screen sparse.
            data_buffer.pop(pt_cursor_position.y, None)
            return

        self._repair_erased_line(line, columns)

    def _repair_erased_line(self, line, columns: range) -> None:
        "Repair the two ends of a range of cells that an erase took away."
        self.repair_wide_char(line, columns.start)
        self.repair_wide_char(line, columns.stop)

    def erase_in_display(self, type_of: int = 0, private: bool = False) -> None:
        """Erases display in a specific way.

        :param int type_of: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of screen, including
              cursor position.
            * ``1`` -- Erases from beginning of screen to cursor,
              including cursor position.
            * ``2`` -- Erases complete display. All lines are erased
              and changed to single-width. Cursor does not move.
            * ``3`` -- Erase saved lines. (Xterm) Clears the history.
        :param bool private: when ``True`` character attributes aren left
                             unchanged **not implemented**.
        """
        if type_of in (2, 3):
            # Clearing the screen (ED 2) or the history (ED 3) removes
            # all graphics placements. (The image data is kept.)
            self.graphics.remove_all_placements()

        line_offset = self.line_offset
        pt_cursor_position = self.pt_cursor_position
        try:
            max_line = max(self.pt_screen.data_buffer)
        except ValueError:
            # max() called on empty sequence: no line holds a cell yet.
            # There is nothing to take away, but a background still has
            # to reach the whole screen.
            max_line = line_offset - 1

        if type_of == 3:
            # "CSI 3 J" takes the history away and leaves the screen
            # as it is. xterm draws it that way, and a program that
            # wants the screen cleared as well sends "CSI 2 J" first.
            self.clear_history()
        else:
            style = self.erase_style()

            # A line that holds nothing needs no cell, so the erasing
            # stops at the last line in use. A background has to reach
            # the bottom of the screen, though.
            last_line = max(max_line, line_offset + self.lines - 1) if style else max_line

            try:
                interval = (
                    # a) erase from cursor to the end of the display, including
                    # the cursor,
                    range(pt_cursor_position.y + 1, last_line + 1),
                    # b) erase from the beginning of the display to the cursor,
                    # including it,
                    range(line_offset, pt_cursor_position.y),
                    # c) erase the whole display.
                    range(line_offset, last_line + 1),
                )[type_of]
            except IndexError:
                return

            data_buffer = self.data_buffer
            erased = ErasedChar(" ", style) if style else None

            # "CSI 2 J" takes the whole screen, marks and all. Only
            # the two that erase a part of it read the marks, and the
            # selective erase reads them whatever its parameter is.
            # xterm draws it that way, and its own conformance suite
            # clears the screen with "CSI 2 J" between tests.
            reads_the_marks = self._protected_chars and (
                private is True or type_of != 2
            )

            for line in interval:
                if reads_the_marks:
                    # A cell that carries a mark stays, so the row
                    # cannot go away whole.
                    self._erase_row_in_place(
                        data_buffer[line], erased, private is True
                    )
                    continue

                data_buffer[line] = defaultdict(lambda: Char(" "))
                if erased is not None:
                    # A background is set, so the erased cells take it.
                    row = data_buffer[line]
                    for column in range(self.columns):
                        row[column] = erased

            # In case of 0 or 1 we have to erase the line with the cursor.
            if type_of in [0, 1]:
                self.erase_in_line(type_of, private=private)

    def _erase_row_in_place(self, row, erased, selective: bool) -> None:
        "Erase every cell of a row that carries no mark."
        for column in range(self.columns):
            cell = row.get(column)
            if cell is not None and self._erase_holds(cell, selective):
                continue
            if erased is None:
                row.pop(column, None)
            else:
                row[column] = erased

    def _rectangle(
        self, top: int, left: int, bottom: int, right: int
    ) -> Tuple[int, int, int, int] | None:
        """
        Read the four corners that a rectangle command names.

        The numbers count from one. Origin mode counts them from the
        margins, so the corners move with the region and a missing
        corner is a margin. A margin does not hold the rectangle in:
        DECFRA, DECERA, DECSERA and DECCRA all reach the whole screen.

        A corner past the screen stops at the edge. A rectangle that
        ends before it starts is no rectangle, and the answer is None.
        """
        lines, columns = self.lines, self.columns
        in_origin_mode = mo.DECOM in self.mode

        vertical = self.margins
        if in_origin_mode and vertical is not None:
            first_row, last_row = vertical.top, vertical.bottom
        else:
            first_row, last_row = 0, lines - 1

        horizontal = self.horizontal_margins
        if in_origin_mode and horizontal is not None:
            first_column, last_column = horizontal
        else:
            first_column, last_column = 0, columns - 1

        top, left = self._corner(top, left)
        bottom = first_row + bottom - 1 if bottom else last_row
        right = first_column + right - 1 if right else last_column

        # The order is read before the edge of the screen cuts the
        # rectangle down. A rectangle that starts past the screen would
        # otherwise fold onto the last row and fill it.
        if bottom < top or right < left:
            return None
        if top >= lines or left >= columns:
            return None

        return top, left, min(bottom, lines - 1), min(right, columns - 1)

    def _corner(self, top: int, left: int) -> Tuple[int, int]:
        """
        Read the row and the column of one corner of a rectangle.

        The numbers count from one, and origin mode counts them from
        the margins. Nothing here holds the corner on the screen: the
        caller knows what it wants to do with a corner past the edge.
        """
        row = (top or 1) - 1
        column = (left or 1) - 1

        if mo.DECOM in self.mode:
            vertical = self.margins
            if vertical is not None:
                row += vertical.top
            horizontal = self.horizontal_margins
            if horizontal is not None:
                column += horizontal.left

        return row, column

    #: The characters that DECFRA writes. They are the two ranges of a
    #: Latin-1 terminal, and xterm drops a code outside them.
    FILL_RANGES = ((32, 126), (160, 255))

    def fill_rectangle(self, *params: int, **kwargs) -> None:
        """
        DECFRA ("CSI Pch ; Pt ; Pl ; Pb ; Pr $ x"): fill a rectangle
        with one character.

        Pch is the code of the character. Each cell takes the rendition
        that is set now, the way a drawn cell does, so a fill under
        DECSCA carries the mark of DECSCA.

        The cursor does not move.
        """
        code = params[0] if params else 0
        if not any(low <= code <= high for low, high in self.FILL_RANGES):
            return

        corners = self._rectangle(*_four(params, 1))
        if corners is None:
            return
        top, left, bottom, right = corners

        protection = self.protection
        if protection:
            cell = _PROTECTED_CHAR_CACHE[(chr(code), self._style_str, protection)]
            self._protected_chars = True
        else:
            cell = _CHAR_CACHE[(chr(code), self._style_str)]

        data_buffer = self.data_buffer
        line_offset = self.line_offset
        for row in range(top, bottom + 1):
            line = data_buffer[row + line_offset]
            for column in range(left, right + 1):
                line[column] = cell
            self.repair_wide_char(line, left)
            self.repair_wide_char(line, right + 1)

    def erase_rectangle(self, *params: int, **kwargs) -> None:
        """
        DECERA ("CSI Pt ; Pl ; Pb ; Pr $ z"): erase a rectangle.

        Each cell takes the background that is set now, the way every
        other erase leaves a cell. No mark holds DECERA away from a
        cell. DECSERA is the one that reads a mark.

        The cursor does not move.
        """
        self._erase_rectangle(self._rectangle(*_four(params, 0)), False)

    def selective_erase_rectangle(self, *params: int, **kwargs) -> None:
        """
        DECSERA ("CSI Pt ; Pl ; Pb ; Pr $ {"): erase a rectangle, and
        leave the cells that DECSCA marked alone.

        Only the mark of DECSCA holds DECSERA away from a cell. The
        mark of ISO 6429 does not, and that is where DECSERA and DECSEL
        part: DECSEL reads both marks, and xterm's own conformance
        suite asks for each of the two.

        The cursor does not move.
        """
        self._erase_rectangle(self._rectangle(*_four(params, 0)), True)

    def _erase_rectangle(
        self, corners: Tuple[int, int, int, int] | None, selective: bool
    ) -> None:
        "Erase every cell of a rectangle that no mark holds back."
        if corners is None:
            return
        top, left, bottom, right = corners

        style = self.erase_style()
        erased = ErasedChar(" ", style) if style else None
        reads_the_marks = selective and self._protected_chars

        data_buffer = self.data_buffer
        line_offset = self.line_offset
        for row in range(top, bottom + 1):
            line = data_buffer[row + line_offset]
            for column in range(left, right + 1):
                if reads_the_marks:
                    cell = line.get(column)
                    if cell is not None and protection_of(cell) & Protection.DEC:
                        continue
                if erased is None:
                    line.pop(column, None)
                else:
                    line[column] = erased
            self.repair_wide_char(line, left)
            self.repair_wide_char(line, right + 1)

    def copy_rectangle(self, *params: int, **kwargs) -> None:
        """
        DECCRA ("CSI Pts ; Pls ; Pbs ; Prs ; Pps ; Ptd ; Pld ; Ppd $ v"):
        copy a rectangle to another place on the screen.

        The first four parameters name the rectangle to read. The sixth
        and the seventh name the top left corner to write it to, and
        the rectangle that lands there keeps the size of the one that
        was read. Both page numbers are ignored, because ptterm holds
        one page.

        The two rectangles may overlap, so every cell is read before
        any cell is written. A cell that holds nothing clears the cell
        it lands on.

        The cursor does not move.
        """
        corners = self._rectangle(*_four(params, 0))
        if corners is None:
            return
        top, left, bottom, right = corners

        target_top, target_left = self._corner(
            params[5] if len(params) > 5 else 0,
            params[6] if len(params) > 6 else 0,
        )
        if target_top >= self.lines or target_left >= self.columns:
            return

        # A rectangle that would hang over the edge is cut down to what
        # fits, and the rest of it is dropped.
        height = min(bottom - top + 1, self.lines - target_top)
        width = min(right - left + 1, self.columns - target_left)

        data_buffer = self.data_buffer
        line_offset = self.line_offset
        read = [
            [
                data_buffer[top + row + line_offset].get(left + column)
                for column in range(width)
            ]
            for row in range(height)
        ]

        for row in range(height):
            line = data_buffer[target_top + row + line_offset]
            for column, cell in enumerate(read[row]):
                if cell is None:
                    line.pop(target_left + column, None)
                else:
                    line[target_left + column] = cell
            self.repair_wide_char(line, target_left)
            self.repair_wide_char(line, target_left + width)

    def set_attribute_extent(self, *params: int, **kwargs) -> None:
        """
        DECSACE ("CSI Ps * x"): what DECCARA and DECRARA reach.

        ptterm has neither of those two yet, so the setting is kept and
        nothing acts on it. A program writes it and reads it back with
        DECRQSS, and an answer that says nothing sends it to a guess.
        """
        value = params[0] if params else 0
        if value in tuple(AttributeExtent):
            self.attribute_extent = AttributeExtent(value)

    def set_active_display(self, *params: int, **kwargs) -> None:
        """
        DECSASD ("CSI Ps $ }"): send the output to the status line.

        A pane draws no status line of its own, because pymux draws one
        for the whole window. So the setting is kept and the output
        stays on the screen.
        """
        value = params[0] if params else 0
        if value in tuple(StatusDisplay):
            self.active_display = StatusDisplay(value)

    def set_status_line_type(self, *params: int, **kwargs) -> None:
        """
        DECSSDT ("CSI Ps $ ~"): what the status line holds.

        Kept, for the same reason as DECSASD.
        """
        value = params[0] if params else 0
        if value in tuple(StatusLineType):
            self.status_line = StatusLineType(value)

    def set_conformance_level(self, *params: int, **kwargs) -> None:
        """
        DECSCL ("CSI Ps ; Ps " p"): the level this terminal answers at.

        A real DEC terminal drops the sequences above the level it is
        set to, and a hard reset comes with the change. ptterm answers
        every sequence it knows whatever the level says, so it keeps
        the number and changes nothing.

        The second parameter says whether the answers carry seven bit
        controls. ptterm always writes seven bit controls, so that one
        is kept as well.
        """
        level = params[0] if params else 0
        if level in tuple(ConformanceLevel):
            self.conformance_level = ConformanceLevel(level)
        if len(params) > 1:
            self.seven_bit_controls = 1 if params[1] in (0, 1) else 1

    def set_lines_per_screen(self, *params: int, **kwargs) -> None:
        """
        DECSNLS ("CSI Ps * |"): how many lines the screen shows.

        On a VT420 the page can be longer than the screen, and this
        names the part that a reader sees. A pane is its own page, and
        pymux owns how big it is, so ptterm keeps the number and does
        not resize anything.
        """
        self.lines_per_screen = (params[0] if params else 0) or self.lines

    def set_tab_stop(self) -> None:
        "Set a horizontal tab stop at cursor position."
        self.tabstops.add(self.pt_cursor_position.x)

    def clear_tab_stop(self, type_of: int | None = None) -> None:
        """Clears a horizontal tab stop in a specific way, depending
        on the ``type_of`` value:
        * ``0`` or nothing -- Clears a horizontal tab stop at cursor
          position.
        * ``3`` -- Clears all horizontal tab stops.
        """
        if not type_of:
            # Clears a horizontal tab stop at cursor position, if it's
            # present, or silently fails if otherwise.
            self.tabstops.discard(self.pt_cursor_position.x)
        elif type_of == 3:
            self.tabstops = set()  # Clears all horizontal tab stops.

    def ensure_bounds(self, use_margins: bool | None = None) -> None:
        """Ensure that current cursor position is within screen bounds.

        :param bool use_margins: when ``True`` or when
                                 :data:`~pyte.modes.DECOM` is set,
                                 cursor is bounded by top and and bottom
                                 margins, instead of ``[0; lines - 1]``.
        """
        margins = self.margins
        if margins and (use_margins or mo.DECOM in self.mode):
            top, bottom = margins
        else:
            top, bottom = 0, self.lines - 1

        cursor_position = self.pt_cursor_position
        line_offset = self.line_offset

        cursor_position.x = min(max(0, cursor_position.x), self.columns - 1)
        cursor_position.y = min(
            max(top + line_offset, cursor_position.y), bottom + line_offset
        )

        # A move of the cursor ends the wait to wrap. Every command
        # that places the cursor comes through here, so this is the one
        # place that has to say it. A tab is the exception, and it
        # never reaches this.
        self.pending_wrap = False

    def alignment_display(self) -> None:
        """
        DECALN ("ESC # 8"): fill the screen with "E".

        The margins go back to the whole screen and the cursor goes
        home afterwards. The DEC manuals say so and kitty does both;
        libvterm does neither.
        """
        for y in range(0, self.lines):
            line = self.data_buffer[y + self.line_offset]
            for x in range(0, self.columns):
                line[x] = Char("E")
        self.margins = None
        self.horizontal_margins = None
        self.cursor_position()

    # Mapping of the ANSI color codes to their names.
    _fg_colors = {v: "#" + k for k, v in FG_ANSI_COLORS.items()}
    _bg_colors = {v: "#" + k for k, v in BG_ANSI_COLORS.items()}

    # Mapping of the escape codes for 256colors to their '#ffffff' value.
    #
    # The first sixteen keep their name. A program that asks for number
    # one asks for "red", which the terminal of the user paints from
    # its own theme. A number gives that away: kitty with a catppuccin
    # theme would draw the red of xterm instead of its own.
    _256_colors = {}

    for i, (r, g, b) in enumerate(_256_colors_table.colors):
        if i < len(PALETTE_NAMES):
            _256_colors[1024 + i] = "#" + PALETTE_NAMES[i]
        else:
            _256_colors[1024 + i] = f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _color_parameters(parameters: List[int]) -> int:
        """
        How many parameters a colour of "38", "48" or "58" takes.

        Two parameters name a colour of the palette and five name one
        of its own. The count is one more, for the "38" itself.
        """
        if len(parameters) < 2:
            return 3
        if parameters[1] == 5:
            return 3
        if parameters[1] == 2:
            return 5
        return len(parameters)

    def _color_of_parameters(self, parameters: List[int]) -> str | None:
        """
        The colour that "38", "48" or "58" names.

        The parameters arrive with semicolons between them or with
        colons; both forms end up here. The form with colons may name
        the colour space first, which nobody uses, so an extra number
        goes away.
        """
        if len(parameters) < 3:
            return None
        kind = parameters[1]
        values = parameters[2:]

        if kind == 5:
            return self._256_colors.get(1024 + values[0])

        if kind == 2:
            if len(values) > 3:
                values = values[1:]
            if len(values) < 3:
                return None
            return "#{:02x}{:02x}{:02x}".format(*values[:3])

        return None

    def select_graphic_rendition(self, *attrs_tuple: int, private: bool = False) -> None:
        """
        SGR ("CSI Ps m"): the style of the cells that come next.

        A private marker makes another sequence, and none of them is
        SGR. "CSI > Ps m" is XTMODKEYS, which says how xterm encodes a
        key with a modifier; a program sends "CSI > 4 m" to put
        modifyOtherKeys back to where it started. Reading that as SGR
        turns the underline on, and everything the program draws after
        it carries a line it never asked for.
        """
        if private:
            return

        replace: Dict[str, object] = {}

        if not attrs_tuple:
            attrs = [0]
        else:
            attrs = list(attrs_tuple[::-1])

        while attrs:
            attr = attrs.pop()

            # A parameter with colons in it arrives as a tuple, and
            # holds everything the colour needs.
            if isinstance(attr, tuple):
                if attr[0] in (38, 48):
                    color = self._color_of_parameters(list(attr))
                    if color is not None:
                        replace["color" if attr[0] == 38 else "bgcolor"] = color
                elif attr[0] == 58:
                    replace["underline_color"] = (
                        self._color_of_parameters(list(attr)) or ""
                    )
                elif attr[0] == 4:
                    number = attr[1] if len(attr) > 1 else 1
                    shape = UNDERLINE_SHAPES.get(number)
                    if shape is not None:
                        replace["underline"] = number != 0
                        replace["underline_style"] = shape
                continue

            if attr in self._fg_colors:
                replace["color"] = self._fg_colors[attr]
            elif attr in self._bg_colors:
                replace["bgcolor"] = self._bg_colors[attr]
            elif attr == 1:
                replace["bold"] = True
            elif attr == 2:
                replace["dim"] = True
            elif attr == 3:
                replace["italic"] = True
            elif attr == 4:
                replace["underline"] = True
                # A plain "4" draws a single line, whatever shape came
                # before it.
                replace["underline_style"] = ""
            elif attr == 5:
                replace["blink"] = True
            elif attr == 6:
                replace["blink"] = True  # Fast blink.
            elif attr == 7:
                replace["reverse"] = True
            elif attr == 8:
                replace["hidden"] = True
            elif attr == 22:
                replace["bold"] = False
                replace["dim"] = False
            elif attr == 23:
                replace["italic"] = False
            elif attr == 21:
                replace["underline"] = True
                replace["underline_style"] = "double"
            elif attr == 24:
                # The colour of the line stays: a program that turns
                # the line on again writes no colour a second time.
                replace["underline"] = False
            elif attr == 25:
                replace["blink"] = False
            elif attr == 27:
                replace["reverse"] = False
            elif not attr:
                replace = {}
                self._attrs = Attrs(
                    color=None,
                    bgcolor=None,
                    bold=False,
                    dim=False,
                    underline=False,
                    strike=False,
                    italic=False,
                    blink=False,
                    reverse=False,
                    hidden=False,
                    underline_style="",
                    underline_color="",
                )

            elif attr == 59:
                replace["underline_color"] = ""
            elif attr in (38, 48):
                # The colour follows in the parameters that come next.
                parameters = [attr]
                while attrs and len(parameters) < self._color_parameters(parameters):
                    parameters.append(attrs.pop())
                color = self._color_of_parameters(parameters)
                if color is not None:
                    replace["color" if attr == 38 else "bgcolor"] = color

            elif attr == 58:
                parameters = [attr]
                while attrs and len(parameters) < self._color_parameters(parameters):
                    parameters.append(attrs.pop())
                replace["underline_color"] = (
                    self._color_of_parameters(parameters) or ""
                )

        attrs_obj = self._attrs._replace(**replace)  # type:ignore

        # Build style string.
        style_str = ""
        if attrs_obj.color:
            style_str += "%s " % attrs_obj.color
        if attrs_obj.bgcolor:
            style_str += "bg:%s " % attrs_obj.bgcolor
        if attrs_obj.bold:
            style_str += "bold "
        if attrs_obj.dim:
            style_str += "dim "
        if attrs_obj.italic:
            style_str += "italic "
        if attrs_obj.underline:
            style_str += UNDERLINE_WORDS[attrs_obj.underline_style or ""] + " "
            # The colour of a line that nobody draws would travel with
            # every cell for nothing.
            if attrs_obj.underline_color:
                style_str += "ul:%s " % attrs_obj.underline_color
        if attrs_obj.blink:
            style_str += "blink "
        if attrs_obj.reverse:
            style_str += "reverse "
        if attrs_obj.hidden:
            style_str += "hidden "

        self._rendition_str = _unicode_intern_dict[style_str]
        self._attrs = attrs_obj
        self._rebuild_style()

    def _rebuild_style(self) -> None:
        """
        The style that a cell takes: the rendition and the hyperlink.

        A hyperlink is not a rendition. "OSC 8" opens one and "CSI m"
        says nothing about it, so the two are kept apart and joined
        here.
        """
        self._style_str = _unicode_intern_dict[
            self._rendition_str + self._hyperlink_str
        ]

    def set_hyperlink(self, target: str) -> None:
        """
        Open a hyperlink, or close the one that is open.

        Every cell that a program draws from here on carries the
        target, until it sends an empty one.
        """
        if target == self.hyperlink:
            return
        self.hyperlink = target
        if target:
            encoded = base64.b64encode(target.encode("utf-8")).decode("ascii")
            self._hyperlink_str = "[hyperlink:%s] " % encoded
        else:
            self._hyperlink_str = ""
        self._rebuild_style()

    # Colour scheme that a pane is told about ("CSI ? 996 n"). pymux
    # renders a dark background, so a pane that asks gets the dark
    # answer. (One is dark, two is light.)
    color_scheme = 1

    #: What "CSI ? Ps n" answers about a part that this terminal does
    #: not have. Each one has a legal answer that says "no", and a
    #: program that asks has to read one: a query with no answer leaves
    #: the program waiting, and leaves every answer after it one place
    #: out of step.
    _DEVICE_STATUS_ANSWERS = {
        # DSRPrinterPort. 13 is "no printer".
        15: "\x1b[?13n",
        # DSRUDKLocked. 20 is "unlocked". Nothing here defines a key,
        # so nothing can lock one either.
        25: "\x1b[?20n",
        # DSRKeyboard: 27, then the language, the state and the type.
        # 1 is North American, 0 is ready and 5 is a PC keyboard.
        26: "\x1b[?27;1;0;5n",
        # DSRLocatorStatus. 50 is "no locator". DECELR is not here, so
        # there is no locator to report on.
        55: "\x1b[?50n",
        # DSRLocatorId: 57, then the kind of pointing device. 0 is
        # "not known".
        56: "\x1b[?57;0n",
        # DECMSR: the room left for a macro, in bytes. This terminal
        # holds no macro and defines none, so there is no room. The
        # answer carries no private marker, and ends with "* {".
        62: "\x1b[0*{",
        # DSRDataIntegrity. 70 is "no error since the last report".
        75: "\x1b[?70n",
        # DSRMultipleSessionStatus. 83 is "not configured for more
        # than one session". A pane is a session of pymux, not of the
        # terminal.
        85: "\x1b[?83n",
    }

    def report_device_status(
        self, data: int = 0, *args, private=False, **kwargs
    ) -> None:
        """
        Answer a device status report.

        "CSI 5 n" asks whether the terminal is well, "CSI 6 n" asks for
        the cursor position and "CSI ? 6 n" asks for it with the page
        number. "CSI ? 996 n" asks which colour scheme the terminal
        uses.

        The rest of "CSI ? Ps n" asks about a printer, a keyboard, a
        locator or a macro. This terminal has none of those, and each
        one has a legal answer that says so.

        Unknown reports are ignored. The private marker arrives as the
        `private` keyword; it must not raise, or one sequence would
        stop the whole pane.
        """
        if private is True and data == 996:
            self.write_process_input("\x1b[?997;%in" % self.color_scheme)
            return

        if private is True and data == 63:
            # DECCKSR: the checksum of the macros, as "DCS Pid ! ~
            # xxxx ST". No macro is defined, so the sum is zero.
            pid = args[0] if args else 0
            self.write_process_input("\x1bP%i!~0000\x1b\\" % pid)
            return

        if private is True and data in self._DEVICE_STATUS_ANSWERS:
            self.write_process_input(self._DEVICE_STATUS_ANSWERS[data])
            return

        if data == 6:
            y = self.pt_cursor_position.y - self.line_offset + 1
            x = self.reported_column + 1
            if private is True:
                # DECXCPR: the page number comes after the position.
                self.write_process_input("\x1b[?%i;%i;1R" % (y, x))
            else:
                self.write_process_input("\x1b[%i;%iR" % (y, x))
            return

        if data == 5 and private is False:
            # "The terminal is well."
            self.write_process_input("\x1b[0n")

    def unscroll(self, count: int | None = None, *args, **kwargs) -> None:
        """
        Kitty's unscroll ("CSI Ps SP D").

        Move the screen down by `count` lines and bring the lines above
        it back from the scroll buffer. A shell uses it when a
        full-screen program ends: the lines that the program covered
        come back instead of leaving blank space under the prompt.

        The lines that leave the bottom of the screen are dropped, and
        the cursor keeps its position on the screen. Nothing happens
        when there is no history left to pull from.
        """
        count = count or 1
        count = min(count, self.line_offset, self.lines)
        if count <= 0:
            return

        data_buffer = self.data_buffer
        for row in range(self.max_y - count + 1, self.max_y + 1):
            data_buffer.pop(row, None)

        self.max_y -= count
        self.graphics.prune_below(self.max_y)

        cursor_position = self.pt_cursor_position
        cursor_position.y = max(0, cursor_position.y - count)
        self.ensure_bounds()

    def placeholder_runs(
        self, first_row: int, last_row: int
    ) -> List[PlaceholderRun]:
        """
        The unicode placeholder runs between two rows of the scroll
        buffer, for an embedder that draws the images.

        The runs that sit on top of each other come back as one
        rectangle, so a screen full of one image is one run and not one
        per line.

        The answer is empty while the pane holds no virtual placement,
        so a pane that shows no image pays nothing for the scan.
        """
        if not self.graphics.has_virtual_placements:
            return []

        data_buffer = self.pt_screen.data_buffer
        columns = self.columns
        runs: List[PlaceholderRun] = []
        for row in range(first_row, last_row + 1):
            line = data_buffer.get(row)
            if line:
                runs.extend(runs_in_line(line, columns, row))
        return merge_runs(runs)

    def report_version(self, *params: int, private: object = False, **kwargs) -> None:
        """
        XTVERSION ("CSI > q"): the name and the version of the terminal.

        Programs read it to decide which extensions they may use. The
        answer names ptterm, because ptterm draws the pane. A plain
        "CSI Ps q" is DECLL, which loads the keyboard lights of a real
        VT220; it is ignored.
        """
        if private != ">":
            return
        self.write_process_input("\x1bP>|%s\x1b\\" % TERMINAL_VERSION)

    #: The private modes that this screen acts on. DECRQM answers for
    #: these; every other mode is reported as not recognised, so that a
    #: program falls back instead of trusting an answer we invent.
    _known_private_modes = frozenset(
        [
            PrivateMode.APPLICATION_CURSOR_KEYS,
            PrivateMode.COLUMNS_132,
            PrivateMode.CURSOR_BLINK,
            PrivateMode.REVERSE_VIDEO,
            PrivateMode.ORIGIN,
            PrivateMode.AUTOWRAP,
            PrivateMode.SHOW_CURSOR,
            PrivateMode.ALTERNATE_SCREEN,
            PrivateMode.LEFT_RIGHT_MARGIN,
            PrivateMode.MOUSE_REPORTING,
            PrivateMode.SGR_MOUSE,
            PrivateMode.URXVT_MOUSE,
            PrivateMode.ALTERNATE_SCREEN_AGAIN,
            PrivateMode.SAVE_CURSOR,
            PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR,
            PrivateMode.BRACKETED_PASTE,
            PrivateMode.INBAND_RESIZE,
        ]
    )

    #: The same for the modes without a private marker.
    _known_ansi_modes = frozenset([mo.IRM, mo.LNM])

    #: The modes that a terminal knows about and never implements.
    #: DECRQM answers 4 for these, which reads as "permanently reset".
    #:
    #: That is a different answer from 0. A 0 says "I never heard of
    #: this mode", and a program then has to guess. A 4 says "the mode
    #: exists, and it can never be on", which is the truth here and
    #: what a program needs to stop asking.
    #:
    #: These twelve come from the ANSI standard. No terminal that
    #: anybody uses implements one of them, and xterm answers 4 for
    #: every one.
    _permanently_reset_ansi_modes = frozenset(
        [
            AnsiMode.GUARDED_AREA_TRANSFER,
            AnsiMode.STATUS_REPORT_TRANSFER,
            AnsiMode.VERTICAL_EDITING,
            AnsiMode.HORIZONTAL_EDITING,
            AnsiMode.POSITIONING_UNIT,
            AnsiMode.FORMAT_EFFECTOR_ACTION,
            AnsiMode.FORMAT_EFFECTOR_TRANSFER,
            AnsiMode.MULTIPLE_AREA_TRANSFER,
            AnsiMode.TRANSFER_TERMINATION,
            AnsiMode.SELECTED_AREA_TRANSFER,
            AnsiMode.TABULATION_STOP,
            AnsiMode.EDITING_BOUNDARY,
        ]
    )

    #: The same for the modes with a private marker.
    _permanently_reset_private_modes = frozenset(
        [
            PrivateMode.HORIZONTAL_CURSOR_COUPLING,
        ]
    )

    #: The modes that this screen keeps and does not act on.
    #:
    #: A mode here is remembered: a set makes DECRQM answer 1, and a
    #: reset makes it answer 2. Nothing else happens. That is a third
    #: thing, beside a mode this screen acts on and a mode that can
    #: never be on, and the three need three answers.
    #:
    #: The reason to keep one is that a program writes a mode and reads
    #: it back to learn whether the terminal took it. An answer of 0
    #: sends that program to a guess. Every mode here is one that xterm
    #: keeps as well.
    #:
    #: The comment on each line says what the mode would do. Four of
    #: them name real behaviour that ptterm does not have yet, and
    #: `tests/DEVIATIONS.md` carries them.
    _remembered_ansi_modes = frozenset(
        [
            AnsiMode.KEYBOARD_LOCKED,  # :todo: drop the input.
            AnsiMode.LOCAL_ECHO,  # :todo: echo it.
        ]
    )

    #: The same for the modes with a private marker.
    _remembered_private_modes = frozenset(
        [
            # A pane draws as fast as it can, and holds no printer.
            PrivateMode.SLOW_SCROLL,
            PrivateMode.PRINT_FORM_FEED,
            PrivateMode.PRINT_EXTENT,
            # These three name real behaviour. :todo: act on them.
            PrivateMode.HEBREW_KEYBOARD,
            PrivateMode.NATIONAL_CHARSETS,
            PrivateMode.APPLICATION_KEYPAD,
            PrivateMode.BACKARROW_IS_BACKSPACE,
        ]
    )

    def report_mode(self, *params: int, private: object = False, **kwargs) -> None:
        """
        DECRQM ("CSI ? Ps $ p" and "CSI Ps $ p"): is this mode set?

        The answer is "CSI ? Ps ; Pm $ y". Pm is 1 for set, 2 for reset,
        4 for a mode that exists and can never be on, and 0 for a mode
        that this screen never heard of.

        A mode gets 1 or 2 when this screen keeps it, whether it acts
        on the mode or not. A program writes a mode and reads it back
        to learn whether the terminal took it, and a 0 sends that
        program to a guess. `_remembered_ansi_modes` names the ones
        that are kept and not acted on.
        """
        number = params[0] if params else 0
        is_private = private is True

        if is_private:
            permanent = number in self._permanently_reset_private_modes
            known = (
                number in self._known_private_modes
                or number in self._remembered_private_modes
            )
            if number == PrivateMode.CURSOR_BLINK:
                # DECSCUSR writes this one as well, and the alternate
                # screen carries a `mode` of its own. So the answer
                # comes from the shape, which is the one value that
                # both sequences write.
                enabled = self.cursor_blinks
            else:
                enabled = (number << 5) in self.mode
        else:
            permanent = number in self._permanently_reset_ansi_modes
            known = (
                number in self._known_ansi_modes
                or number in self._remembered_ansi_modes
            )
            enabled = number in self.mode

        if permanent:
            state = ModeReport.PERMANENTLY_RESET
        elif not known:
            state = ModeReport.UNKNOWN
        else:
            state = ModeReport.SET if enabled else ModeReport.RESET

        self.write_process_input(
            "\x1b[%s%i;%i$y" % ("?" if is_private else "", number, state)
        )

    def set_cursor_style(self, *params: int, **kwargs) -> None:
        """
        DECSCUSR ("CSI Ps SP q"): the shape of the cursor.

        The shape belongs to the pane. What draws the pane reads
        `cursor_style` and puts the shape on the terminal of the user,
        so a pane that asks for a bar gets one. A program that sets a
        shape also asks for it back, and it reads what it wrote.
        """
        style = params[0] if params else 0
        if style == 0:
            self.cursor_style = DEFAULT_CURSOR_STYLE
        elif style in iter(CursorShape):
            self.cursor_style = CursorShape(style)

    def set_cursor_blink(self, blinking: bool) -> None:
        """
        Turn the blinking of the cursor on or off, and keep its shape.

        Mode 12 says only whether the cursor blinks. DECSCUSR says the
        shape and the blinking together, so this writes the same value:
        the blinking shape of a pair is the odd number, and the steady
        one is the number after it.
        """
        style = self.cursor_style
        if blinking and style % 2 == 0:
            self.cursor_style = CursorShape(style - 1)
        elif not blinking and style % 2 == 1:
            self.cursor_style = CursorShape(style + 1)

    @property
    def cursor_blinks(self) -> bool:
        "True when the cursor of this screen blinks."
        return self.cursor_style % 2 == 1

    def report_setting(self, name: str) -> None:
        """
        DECRQSS ("DCS $ q <name> ST"): the current value of a setting.

        The answer is "DCS 1 $ r <value> <name> ST" for a setting that
        this screen keeps, and "DCS 0 $ r ST" for one that it does not.
        """
        if name == "m":
            value = self._current_rendition()
        elif name == " q":
            value = "%i" % self.cursor_style
        elif name == "r":
            margins = self.margins or Margins(0, self.lines - 1)
            value = "%i;%i" % (margins.top + 1, margins.bottom + 1)
        elif name == "s":
            left, right = self.left_right
            value = "%i;%i" % (left + 1, right + 1)
        elif name == '"q':
            # DECSCA: does a selective erase leave the cells that come
            # next alone?
            value = "1" if self.protection & Protection.DEC else "0"
        elif name == "*x":
            value = "%i" % self.attribute_extent
        elif name == "$}":
            value = "%i" % self.active_display
        elif name == "$~":
            value = "%i" % self.status_line
        elif name == '"p':
            value = "%i;%i" % (self.conformance_level, self.seven_bit_controls)
        elif name == "*|":
            value = "%i" % self.lines_per_screen
        elif name == "t":
            # DECSLPP: the lines of the page. A pane is its own page,
            # so the answer is how tall the pane is.
            #
            # "CSI Ps t" with Ps of 24 or more asks for a page of that
            # many lines, and xterm resizes its window. ptterm does not
            # take it: pymux owns how tall a pane is, and one pane
            # cannot move another one. So the answer is the truth about
            # this pane and not the number a program asked for.
            # `tests/DEVIATIONS.md` carries it.
            value = "%i" % self.lines
        else:
            self.write_process_input("\x1bP0$r\x1b\\")
            return

        self.write_process_input("\x1bP1$r%s%s\x1b\\" % (value, name))

    def report_capabilities(self, query: str) -> None:
        """
        XTGETTCAP ("DCS + q <names> ST"): what this terminal can do.

        The names arrive as hexadecimal, separated by semicolons, and
        each one is answered on its own. "1 + r" carries a capability
        that this terminal has and "0 + r" one that it does not.

        This is what a program asks when the database of the machine
        it runs on says nothing useful, which is every time it runs
        over ssh.
        """
        for encoded in query.split(";"):
            try:
                name = bytes.fromhex(encoded).decode("ascii")
            except ValueError:
                self.write_process_input("\x1bP0+r%s\x1b\\" % encoded)
                continue

            value = CAPABILITIES.get(name)
            if value is None:
                self.write_process_input("\x1bP0+r%s\x1b\\" % encoded)
            elif value is True:
                self.write_process_input("\x1bP1+r%s\x1b\\" % encoded)
            else:
                self.write_process_input(
                    "\x1bP1+r%s=%s\x1b\\"
                    % (encoded, str(value).encode("utf-8").hex())
                )

    def _current_rendition(self) -> str:
        """
        The graphic rendition of this screen, as SGR parameters.

        A colour comes back as its three components, also when the
        program set it by index: the screen keeps the colour, not the
        index. A program that probes for 24 bit colour reads its own
        colour back, which is the answer it looks for.
        """
        attrs = self._attrs
        parts = ["0"]

        for flag, parameter in (
            (attrs.bold, "1"),
            (attrs.dim, "2"),
            (attrs.italic, "3"),
            (attrs.underline, UNDERLINE_PARAMETERS[attrs.underline_style or ""]),
            (attrs.blink, "5"),
            (attrs.reverse, "7"),
            (attrs.hidden, "8"),
            (attrs.strike, "9"),
        ):
            if flag:
                parts.append(parameter)

        for color, number in ((attrs.color, 38), (attrs.bgcolor, 48)):
            components = _rgb_components(color)
            if components is not None:
                parts.append("%i;2;%i;%i;%i" % ((number,) + components))

        components = _rgb_components(attrs.underline_color)
        if attrs.underline and components is not None:
            parts.append("58:2::%i:%i:%i" % components)

        return ";".join(parts)

    def report_window(self, *params: int, **kwargs) -> None:
        """
        Window manipulation ("CSI Ps t").

        The sizes and the titles are answered. A pane has no window of
        its own, so it cannot move, iconify or maximize one, and it
        ignores every operation that asks for that.

        Three of them ask for a size: DECSLPP ("CSI Ps t" with a Ps of
        24 or more), and the two forms of a resize, in cells and in
        pixels. Those go to `resize_func`, and the embedder decides.
        pymux asks the person first, because a pane sits in a layout
        and making one taller makes another shorter.

        A pane that draws images asks for the cell size (16) to work out
        how many cells an image covers. The answer is the size that
        `ptterm.graphics` assumes, so both sides count alike.
        """
        what = params[0] if params else 0
        which = params[1] if len(params) > 1 else 0

        if what >= FIRST_PAGE_LENGTH:
            # DECSLPP: a page of `what` lines, and the columns stay.
            self.resize_func(what, None)
        elif what == WindowOp.RESIZE_CHARS:
            self._resize_in_cells(params)
        elif what == WindowOp.RESIZE_PIXELS:
            self._resize_in_pixels(params)
        elif what == WindowOp.REPORT_ICON_LABEL:
            self.write_process_input("\x1b]L%s\x1b\\" % self.icon_name)
        elif what == WindowOp.REPORT_WINDOW_TITLE:
            self.write_process_input("\x1b]l%s\x1b\\" % self.title)
        elif what == WindowOp.PUSH_TITLE:
            self._push_title()
        elif what == WindowOp.POP_TITLE:
            self._pop_title(which)
        elif what == WindowOp.REPORT_CELL_SIZE_PIXELS:
            # Cell size in pixels: height first, then width.
            self.write_process_input(
                "\x1b[6;%i;%it" % (ASSUMED_CELL_HEIGHT, ASSUMED_CELL_WIDTH)
            )
        elif what == WindowOp.REPORT_TEXT_AREA_CHARS:
            # Size of the text area, in cells.
            self.write_process_input("\x1b[8;%i;%it" % (self.lines, self.columns))
        elif what == WindowOp.REPORT_TEXT_AREA_PIXELS:
            # Size of the text area, in pixels.
            self.write_process_input(
                "\x1b[4;%i;%it"
                % (self.lines * ASSUMED_CELL_HEIGHT, self.columns * ASSUMED_CELL_WIDTH)
            )

    def _resize_in_cells(self, params: Tuple[int, ...]) -> None:
        """
        "CSI 8 ; Ph ; Pw t": ask for Ph rows and Pw columns.

        A zero means "as much as there is", and a missing number means
        "leave this one alone". xterm reads them that way, and a
        program sends "CSI 8 ; 0 ; 80 t" to keep its height.
        """
        self.resize_func(
            self._wanted(params, 1, self.MAX_LINES),
            self._wanted(params, 2, self.MAX_COLUMNS),
        )

    def _resize_in_pixels(self, params: Tuple[int, ...]) -> None:
        """
        "CSI 4 ; Ph ; Pw t": as many cells as fit in Ph by Pw pixels.

        A pane holds no pixels, so it counts them in the cell size that
        `ptterm.graphics` assumes. That is the same size the pane
        reports for a cell, so a program that divides gets back what it
        asked for.
        """
        lines = self._wanted(params, 1, None)
        columns = self._wanted(params, 2, None)
        self.resize_func(
            self.MAX_LINES if lines == 0 else
            None if lines is None else max(1, lines // ASSUMED_CELL_HEIGHT),
            self.MAX_COLUMNS if columns == 0 else
            None if columns is None else max(1, columns // ASSUMED_CELL_WIDTH),
        )

    @staticmethod
    def _wanted(
        params: Tuple[int, ...], index: int, whole: int | None
    ) -> int | None:
        """
        One number of a resize: how many, all of them, or leave it.

        A missing number leaves that side as it is, and None says so. A
        zero asks for the whole screen, and `whole` is what that means.
        """
        if len(params) <= index:
            return None
        value = params[index]
        return whole if value == 0 else value

    #: What "as much as there is" means. Nothing here knows how big the
    #: screen of the person is, so the embedder cuts these down to what
    #: it really has.
    MAX_LINES = 10000
    MAX_COLUMNS = 10000

    #: How many titles "CSI 22 t" remembers. xterm keeps ten, and a
    #: program that pushes and never pops must not grow the pane.
    TITLE_STACK_LIMIT = 10

    def _push_title(self) -> None:
        """
        "CSI 22 ; Ps t": remember the titles that are set now.

        One stack holds both of them, whichever title the parameter
        names. A pop then takes one entry off and writes back the
        title that its own parameter names, so a push of the icon
        label and a pop of the window title read the same entry.
        xterm answers this way, and the conformance suite reads it.
        """
        self.title_stack.append((self.icon_name, self.title))
        del self.title_stack[: -self.TITLE_STACK_LIMIT]

    def _pop_title(self, which: int) -> None:
        """
        "CSI 23 ; Ps t": bring back the titles that a push remembered.

        Zero brings back both, one the icon label and two the window
        title. An empty stack leaves both of them alone.
        """
        if not self.title_stack:
            return

        icon_name, title = self.title_stack.pop()
        if which in (TitlePart.BOTH, TitlePart.ICON):
            self.icon_name = icon_name
        if which in (TitlePart.BOTH, TitlePart.WINDOW):
            self.title = title

    def report_checksum(self, *params: int, **kwargs) -> None:
        """
        DECRQCRA ("CSI Pid ; Pp ; Pt ; Pl ; Pb ; Pr * y"): the checksum
        of a rectangle of the screen.

        The answer is "DCS Pid ! ~ xxxx ST", four hex digits. The value
        is the negated sum of the characters in the rectangle. DEC's own
        terminals answer that, and a conformance suite reads the screen
        back this way, one cell at a time.

        Only the character of a cell counts. A DEC terminal adds bits
        for the attributes of the cell as well, and xterm does again
        since its patch 336, but the two disagree on which bits. Nothing
        reads them here, so the simpler rule stands until something
        does.

        A cell that holds nothing counts as a space. So the sum of one
        cell is never zero, and the answer is never "0000", which a
        caller cannot tell apart from an answer that never came.
        """
        pid = params[0] if params else 0
        top = (params[2] if len(params) > 2 else 0) or 1
        left = (params[3] if len(params) > 3 else 0) or 1
        bottom = (params[4] if len(params) > 4 else 0) or self.lines
        right = (params[5] if len(params) > 5 else 0) or self.columns

        top, bottom = sorted(
            (max(1, min(top, self.lines)), max(1, min(bottom, self.lines)))
        )
        left, right = sorted(
            (max(1, min(left, self.columns)), max(1, min(right, self.columns)))
        )

        line_offset = self.line_offset
        total = 0
        for y in range(top - 1, bottom):
            row = self.data_buffer[y + line_offset]
            for x in range(left - 1, right):
                char = row[x].char
                total += ord(char[0]) if char else ord(" ")

        self.write_process_input("\x1bP%i!~%04X\x1b\\" % (pid, -total & 0xFFFF))

    def report_device_attributes(self, *args, **kwargs) -> None:
        response = "\x1b[>84;0;0c"
        self.write_process_input(response)

    # The kitty keyboard protocol spec says terminals should limit the size
    # of the flag stack to prevent denial-of-service. When the stack is
    # full, pushing evicts the oldest entry.
    kitty_max_flags_stack_size = 64

    def report_kitty_keyboard(self, *params, private=False) -> None:
        """
        Handle the ``CSI u`` sequences of the kitty keyboard protocol:
        push (``CSI > flags u``), pop (``CSI < number u``),
        set (``CSI = flags ; mode u``) and query (``CSI ? u``).

        Requires a ``pyte`` stream that passes the private marker (``>``,
        ``<`` or ``=``) through as the ``private`` keyword argument. With
        an unpatched ``pyte``, the sequences don't reach this method.
        """
        if private is True:
            # Query: reply with the flags that this pane really gets.
            # (Not the ones it asked for: see
            # `deliverable_kitty_keyboard_flags`.)
            self.write_process_input(
                "\x1b[?%iu" % self.deliverable_kitty_keyboard_flags
            )

        elif private == ">":
            # Push flags onto the stack. (Spec: if flags is omitted, it
            # defaults to zero.)
            flags = params[0] if params else 0
            stack = self.kitty_flags_stack + (flags,)
            if len(stack) > self.kitty_max_flags_stack_size:
                stack = stack[-self.kitty_max_flags_stack_size :]
            self.kitty_flags_stack = stack

        elif private == "<":
            # Pop entries off the stack. (Spec: the count defaults to 1.
            # Popping more entries than the stack holds, or popping from
            # an empty stack, resets all flags.)
            count = params[0] if params else 1
            count = max(1, count)
            if self.kitty_flags_stack:
                self.kitty_flags_stack = self.kitty_flags_stack[:-count]

        elif private == "=":
            # Set the current flags. Mode 1 (the default) sets them
            # exactly, mode 2 sets the given bits (OR), and mode 3 resets
            # the given bits (AND NOT).
            flags = params[0] if params else 0
            mode = params[1] if len(params) > 1 else 1

            current = self.kitty_keyboard_flags
            if mode == 1:
                new_flags = flags
            elif mode == 2:
                new_flags = current | flags
            elif mode == 3:
                new_flags = current & ~flags
            else:
                return  # Unknown mode. Ignore.

            if self.kitty_flags_stack:
                # Replace the top of the stack.
                self.kitty_flags_stack = (
                    self.kitty_flags_stack[:-1] + (new_flags,)
                )
            else:
                # No stack: setting acts like a push. (kitty behaves the
                # same way.)
                self.kitty_flags_stack = (new_flags,)

        else:
            # A plain "CSI u" carries no private marker, so it is not
            # part of the protocol at all. It is SCORC, the restore of
            # the SCO console, and xterm reads it that way.
            self.restore_cursor()

    def osc(self, code: str, param: str) -> None:
        """
        An OSC sequence other than the title and the icon name.

        A pane keeps its own colours. A program sets one and reads it
        back, and the answer is what the program set; the defaults
        answer until it sets anything. What the embedder draws with is
        a separate question, and the answer to it is that a pane does
        not paint the terminal of the user.

        A hyperlink ("OSC 8") belongs to the cells that follow it, so
        the screen keeps it and every cell carries it.

        A few sequences ask the terminal of the user for something that
        a pane cannot give: the clipboard, a desktop notification, the
        shape of the pointer. Those go to `osc_func`, and the embedder
        decides what reaches the user.

        Everything else is consumed. It must not raise: one sequence
        may not stop the pane.
        """
        if code == Osc.HYPERLINK:
            target = parse_hyperlink(param)
            if target is not None:
                self.set_hyperlink(target)
        elif code == Osc.POINTER_SHAPE:
            if self._set_pointer_shape(param):
                self._forward_osc(code, param)
        elif code == Osc.PALETTE_COLOR:
            self._palette_colors(code, param, 0)
        elif code == Osc.SPECIAL_COLOR:
            self._palette_colors(code, param, FIRST_SPECIAL_COLOR)
        elif code == Osc.RESET_PALETTE_COLOR:
            self._reset_palette_colors(param, 0, len(PALETTE))
        elif code == Osc.RESET_SPECIAL_COLOR:
            self._reset_palette_colors(
                param, FIRST_SPECIAL_COLOR, len(SPECIAL_COLOR_NAMES)
            )
        elif code in DYNAMIC_COLOR_CODES:
            self._dynamic_colors(code, param)
        elif self._reset_code_of(code) in DYNAMIC_COLOR_CODES:
            self.dynamic_colors.pop(self._reset_code_of(code), None)
        elif code == Osc.KITTY_COLORS:
            self._report_kitty_colors(param)
        elif code in FORWARDED_OSC:
            self._forward_osc(code, param)

    @staticmethod
    def _reset_code_of(code: str) -> str:
        """
        The code that sets what `code` puts back, or the code itself
        when it sets nothing. "OSC 110" gives "10".
        """
        if not code.isdigit():
            return code
        return str(int(code) - DYNAMIC_COLOR_RESET_OFFSET)

    @property
    def pointer_shape(self) -> str:
        """
        The shape of the pointer over this screen.

        An empty string means that the program asked for no shape, and
        that whoever draws the pointer picks one.
        """
        return self.pointer_shapes[-1] if self.pointer_shapes else ""

    def _set_pointer_shape(self, param: str) -> bool:
        """
        "OSC 22": the shape of the pointer over the pane.

        A terminal keeps a stack of shapes. A bare name or "=name"
        replaces the shape now, ">a,b" pushes, "<" pops one, and an
        empty payload takes the shape away. "?names" asks a question,
        which the screen answers itself: a pane has no pointer of its
        own, but a program that asks needs an answer.

        Returns True when the embedder has to look again.
        """
        operation = "="
        if param and param[0] in "><=?":
            operation, param = param[0], param[1:]

        if operation == "?":
            self._report_pointer_shapes(param)
            return False

        if operation == "<":
            if self.pointer_shapes:
                self.pointer_shapes.pop()
                return True
            return False

        changed = False
        for name in param.split(","):
            if not name and operation != "=":
                continue  # A push of nothing pushes nothing.
            shape = pointer_shape_name(name)
            if shape is None:
                continue  # Not a shape that a terminal knows.
            if operation == "=":
                if self.pointer_shapes:
                    self.pointer_shapes[-1] = shape
                else:
                    self.pointer_shapes.append(shape)
            else:
                if len(self.pointer_shapes) >= MAX_POINTER_SHAPES:
                    del self.pointer_shapes[0]  # The oldest goes.
                self.pointer_shapes.append(shape)
            changed = True
        return changed

    def _report_pointer_shapes(self, param: str) -> None:
        """
        Answer "OSC 22 ; ? names".

        A name that the screen takes answers one, a name that nobody
        knows answers zero, and "__current__" answers the shape now, or
        zero when there is none. A pane has no pointer of its own, so
        the default and the grabbed shape are both the plain default.

        kitty answers for the table of CSS names, and takes a few more
        names than it calls valid. This answers for the names it really
        takes, which is what a program asking the question wants to
        know.
        """
        answers = []
        for query in param.split(","):
            if query and pointer_shape_name(query) is not None:
                answers.append("1")
            elif query == "__current__":
                answers.append(self.pointer_shape or "0")
            elif query in ("__default__", "__grabbed__"):
                answers.append("default")
            else:
                answers.append("0")
        self.write_process_input("\x1b]22;%s\x1b\\" % ",".join(answers))

    def _forward_osc(self, code: str, param: str) -> None:
        """
        Hand an OSC sequence to the embedding application.

        A clipboard query is not handed on. It reads what the user
        copied somewhere else, and a program in a pane has no claim on
        that. Writing the clipboard is handed on; reading it is not.
        """
        if code == "52" and _reads_the_clipboard(param):
            return
        self.osc_func(code, param)

    #: The value that asks for a colour instead of setting one.
    QUERY = "?"

    def color_of(self, index: int) -> Color | None:
        """
        The colour that "OSC 4" reports for an index.

        The palette comes first and the special colours follow it. The
        answer is what a program set, or the default when it set
        nothing. `None` is an index that this pane does not hold.
        """
        held = self.palette_colors.get(index)
        if held is not None:
            return held
        if index < len(PALETTE):
            return PALETTE[index]
        # A special colour that nobody set draws in the colour of the
        # text. xterm leaves such a colour unset and paints the text
        # colour, so that is the honest answer.
        if index - FIRST_SPECIAL_COLOR < len(SPECIAL_COLOR_NAMES):
            return DEFAULT_COLORS["foreground"]
        return None

    def _palette_colors(self, code: str, param: str, offset: int) -> None:
        """
        Read "OSC 4" or "OSC 5": the palette and the special colours.

        The payload holds index and value pairs. A value of "?" asks
        for the colour and the others set it. `offset` is what the
        written index needs to reach the table, because "OSC 5"
        numbers the special colours from zero and "OSC 4" numbers them
        after the palette.

        Each query is answered on its own. A program reads one answer
        for each question it asked, so two questions may not come back
        as one.
        """
        parts = param.split(";")
        for index in range(0, len(parts) - 1, 2):
            number, value = parts[index], parts[index + 1]
            if not number.isdigit():
                continue
            entry = int(number) + offset
            if value.strip() == self.QUERY:
                color = self.color_of(entry)
                if color is not None:
                    self.write_process_input(
                        "\x1b]%s;%s;%s\x1b\\" % (code, number, color.spec)
                    )
            else:
                color = parse_color(value)
                if color is not None and self.color_of(entry) is not None:
                    self.palette_colors[entry] = color

    def _reset_palette_colors(
        self, param: str, offset: int, count: int
    ) -> None:
        """
        Read "OSC 104" or "OSC 105": put colours back to the defaults.

        The payload names the indexes to put back. An empty payload
        puts back every colour that the sequence covers, which is the
        palette for one code and the special colours for the other.
        """
        if not param.strip():
            for entry in range(offset, offset + count):
                self.palette_colors.pop(entry, None)
            return
        for number in param.split(";"):
            if number.isdigit():
                self.palette_colors.pop(int(number) + offset, None)

    def _dynamic_colors(self, code: str, param: str) -> None:
        """
        Read "OSC 10" and the codes after it: the colours that a
        terminal names rather than numbers.

        One payload may carry several values, and each one moves on to
        the next code. "OSC 10 ; spec1 ; spec2" sets the foreground and
        then the background. A code that a pane does not hold is
        counted and skipped, so the ones after it still land right.
        """
        for step, value in enumerate(param.split(";")):
            number = str(int(code) + step)
            if number not in DYNAMIC_COLOR_CODES:
                continue
            if value.strip() == self.QUERY:
                color = self.dynamic_colors.get(
                    number, DEFAULT_COLORS[DYNAMIC_COLOR_CODES[number]]
                )
                self.write_process_input(
                    "\x1b]%s;%s\x1b\\" % (number, color.spec)
                )
            else:
                color = parse_color(value)
                if color is not None:
                    self.dynamic_colors[number] = color

    def _named_color(self, name: str) -> Color:
        """
        The colour that a name stands for, as this pane holds it now.

        A dynamic colour that a program set wins over the default. Both
        "OSC 10" and the kitty query read the same colour, so both read
        this.
        """
        for code, named in DYNAMIC_COLOR_CODES.items():
            if named == name and code in self.dynamic_colors:
                return self.dynamic_colors[code]
        return DEFAULT_COLORS[name]

    def _report_kitty_colors(self, param: str) -> None:
        """
        Answer a kitty colour query, e.g. "OSC 21 ; background=?".

        kitty joins its answers into one sequence, which is what its
        own protocol says. The xterm queries answer one at a time.
        """
        keys = parse_kitty_color_query(param)
        if keys is None:
            return

        answers = []
        for key, is_query in keys:
            if not is_query:
                continue
            if key.isdigit() and int(key) < len(PALETTE):
                color = self.color_of(int(key))
                answers.append("%s=%s" % (key, color.spec))
            elif key in DEFAULT_COLORS:
                answers.append("%s=%s" % (key, self._named_color(key).spec))
            else:
                answers.append("%s=" % key)  # Not a colour that we hold.
        if answers:
            self.write_process_input("\x1b]21;%s\x1b\\" % ";".join(answers))

    def set_icon_name(self, param: str) -> None:
        self.icon_name = param

    def set_title(self, param: str) -> None:
        self.title = param

    def apc(self, data: str) -> None:
        """
        APC string sequence (``ESC _ ... ST``).

        Kitty graphics protocol commands arrive here. They are parsed
        and their images and placements are stored; the pixel data is
        not rendered (the embedding application, e.g. the pymux
        multiplexer, decides how to display images).
        """
        if not data.startswith("G"):
            return  # Not the graphics protocol.

        result = self.graphics.handle(data[1:], self)
        if result is not None:
            response, _is_ok = result
            self.write_process_input("\x1b_G" + response + "\x1b\\")

    def dcs(self, data: str) -> None:
        """
        DCS string sequence (``ESC P ... ST``).

        A sixel image arrives here. It is decoded and stored in the
        graphics state, next to the images of the kitty graphics
        protocol, so that one renderer draws both.

        A DECRQSS request ("DCS $ q <name> ST") also arrives here, and
        is answered. Every other DCS sequence is consumed without
        corrupting the screen content.
        """
        if data.startswith("$q"):
            self.report_setting(data[2:])
            return

        if data.startswith("+q"):
            self.report_capabilities(data[2:])
            return

        image = decode_sixel(data)
        if image is None:
            return
        width, height, pixels = image
        self.graphics.add_sixel(width, height, pixels, self)

    def charset_default(self, *a, **kw):
        "Not implemented."

    def charset_utf8(self, *a, **kw):
        "Not implemented."

    def debug(self, *args, **kwargs):
        pass

    def _reflow(self) -> None:
        """
        Reflow the screen using the given width.
        """
        width = self.columns

        data_buffer = self.pt_screen.data_buffer
        new_data_buffer = Screen(default_char=Char(" ", "")).data_buffer
        cursor_position = self.pt_cursor_position
        cy, cx = (cursor_position.y, cursor_position.x)

        cursor_character = data_buffer[cursor_position.y][cursor_position.x].char

        # Ensure that the cursor position is present.
        # (and avoid calling min() on empty collection.)
        data_buffer[cursor_position.y][cursor_position.y]

        # Unwrap all the lines.
        offset = min(data_buffer)
        line: List[Char] = []
        all_lines: List[List[Char]] = [line]

        for row_index in range(min(data_buffer), max(data_buffer) + 1):
            row = data_buffer[row_index]

            row[0]  # Avoid calling max() on empty collection.
            for column_index in range(0, max(row) + 1):
                if cy == row_index and cx == column_index:
                    cy = len(all_lines) - 1
                    cx = len(line)

                line.append(row[column_index])

            # Create new line if the next line was not a wrapped line.
            if row_index + 1 not in self.wrapped_lines:
                line = []
                all_lines.append(line)

        # Remove trailing whitespace (unless it contains the cursor).
        # Also make sure that lines consist of at lesat one character,
        # otherwise we can't calculate `max_y` correctly. (This is important
        # for the `clear` command.)
        for row_index, line in enumerate(all_lines):
            # We do this only if no special styling given.
            while len(line) > 1 and line[-1].char.isspace() and not line[-1].style:
                if row_index == cy and len(line) - 1 == cx:
                    break
                line.pop()

        # Wrap lines again according to the screen width.
        new_row_index = offset
        new_column_index = 0
        new_wrapped_lines = []

        for row_index, line in enumerate(all_lines):
            for column_index, char in enumerate(line):
                # Check for space on the current line.
                if new_column_index + char.width > width:
                    new_row_index += 1
                    new_column_index = 0
                    new_wrapped_lines.append(new_row_index)

                if cy == row_index and cx == column_index:
                    cy = new_row_index
                    cx = new_column_index

                # Add character to new buffer.
                new_data_buffer[new_row_index][new_column_index] = char
                new_column_index += char.width

            new_row_index += 1
            new_column_index = 0

        # TODO: when the window gets smaller, and the cursor is at the top of the screen,
        #       remove lines at the bottom.
        for row_index in range(min(data_buffer), max(data_buffer) + 1):
            if row_index > cy + self.lines:
                del data_buffer[row_index]

        self.pt_screen.data_buffer = new_data_buffer
        self.data_buffer = new_data_buffer
        self.wrapped_lines = new_wrapped_lines

        cursor_position.y, cursor_position.x = cy, cx
        self.pt_cursor_position = cursor_position

        # If everything goes well, the cursor should still be on the same character.
        if (
            cursor_character
            != new_data_buffer[cursor_position.y][cursor_position.x].char
        ):
            # FIXME:
            raise Exception(
                "Reflow failed: {!r} {!r}".format(
                    cursor_character,
                    new_data_buffer[cursor_position.y][cursor_position.x].char,
                )
            )

        self.max_y = max(self.data_buffer)

        self.max_y = min(self.max_y, cursor_position.y + self.lines - 1)
