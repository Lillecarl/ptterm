"""
Speak the protocol of libvterm's test harness, with ptterm behind it.

libvterm keeps its suite in `t/`: 43 files in a plain text language,
driven by `t/run-test.pl`. The runner takes `--executable`, so it drives
whatever program is given to it over a pipe. libvterm's own program is
`t/harness.c`. This is the same program, with ptterm inside it.

Nothing in libvterm changes: not the runner, not one test file. That is
the property that makes a foreign suite worth having, and it is the same
one that `drive_with_esctest.py` relies on.

The protocol is one line at a time.

- A command is in capitals. The harness does it, writes whatever it
  emitted, and then writes "DONE". A line it does not know gets "?".
- An assertion starts with "?". The harness answers with exactly one
  line, and writes no "DONE".

The runner does the quoting, so this file never reads the test language.
`PUSH "ABC"` arrives as `PUSH 414243`, and `?screen_row 0 = "ABC"`
arrives as `?screen_chars 0` with the answer wanted as comma separated
hex.

**This harness reports no callbacks.** libvterm tells its embedder what
it drew and what it had to redraw: `putglyph`, `damage`, `scrollrect`,
`moverect`. ptterm writes into a screen and the embedder reads the
screen, so there is nothing to report and no honest thing to say. A test
file that expects those lines is left out by name in
`drive_with_vterm.py`, with the reason written down.

What it does answer is the state: the nine `?` forms, which is what
ptterm holds. `drive_with_vterm.py` says which files that covers.

Run it through the check, not by hand:

    nix build --file . checks.ptterm-vterm
"""
import codecs
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from kitty_oracle import (  # noqa: E402
    ANSI_COLOR_NAMES,
    _color_of_style,
    _underline_of_style,
)

from ptterm.screen import BetterScreen, DoubleHeight, TerminalChar  # noqa: E402
from ptterm.stream import BetterStream  # noqa: E402

#: The screen that libvterm's `INIT` makes.
ROWS, COLUMNS = 25, 80

#: The colours that libvterm starts with, which its own harness never
#: changes. The foreground is a 90% grey, so that pure white is brighter
#: than plain text; `src/pen.c` says so.
#:
#: ptterm holds "the default", with no colour behind it, because the
#: terminal that draws a pane owns the palette. Naming the numbers here
#: is what an embedder of libvterm does with
#: `vterm_state_set_default_colors`, and `SETDEFAULTCOL` changes them.
#: The content of the answer is the flag that says "this is the
#: default"; the numbers are the ones this embedder declared.
DEFAULT_FOREGROUND = (240, 240, 240)
DEFAULT_BACKGROUND = (0, 0, 0)

#: The style that a hyperlink adds. It is not a rendition, and libvterm
#: has no cell attribute for it, so it comes off before a comparison.
_LINK = "class:hyperlink"


class Harness:
    """
    One screen, and the answers about it.

    A single object, because the protocol is a single session: `INIT`
    makes the screen and everything after it reads or writes that one.
    """

    def __init__(self) -> None:
        self.screen: BetterScreen | None = None
        self.stream: BetterStream | None = None
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.default_foreground = DEFAULT_FOREGROUND
        self.default_background = DEFAULT_BACKGROUND

    # -- the screen -----------------------------------------------------

    def make(self, rows: int, columns: int) -> None:
        "Build a screen of this size, with nothing on it."
        # A pane cannot resize itself and writes its answers to a pty.
        # Neither has anywhere to go here: the runner drives the screen
        # directly, and the suite reads it back through this harness.
        self.screen = BetterScreen(
            rows, columns, write_process_input=lambda answer: None
        )
        self.stream = BetterStream(self.screen)
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def cell(self, row: int, column: int):
        "The cell at a place on the visible screen."
        assert self.screen is not None
        buffer = self.screen.pt_screen.data_buffer
        return buffer[self.screen.line_offset + row][column]

    # -- the commands ---------------------------------------------------

    def command(self, line: str) -> bool:
        """
        Do one command. False means this harness does not know it.

        `WANTPARSER`, `WANTSTATE` and `WANTSCREEN` say which callbacks
        libvterm should report. This harness reports none, so it takes
        them and does nothing. A file that needs the reports is left out
        by name, so taking them quietly here costs nothing.
        """
        screen = self.screen

        if line == "INIT":
            if screen is None:
                self.make(ROWS, COLUMNS)
            return True

        if line == "WANTPARSER" or line.split(" ")[0] in (
            "WANTSTATE",
            "WANTSCREEN",
            "WANTENCODING",
            "DAMAGEMERGE",
            "DAMAGEFLUSH",
        ):
            return True

        if line.startswith("UTF8 "):
            # ptterm reads unicode and has no other encoding to be in.
            return True

        if line == "RESET":
            assert screen is not None
            screen.reset()
            return True

        if line.startswith("RESIZE "):
            assert screen is not None
            rows, columns = (int(number) for number in line[7:].split(","))
            screen.resize(rows, columns)
            return True

        if line.startswith("PUSH "):
            assert self.stream is not None
            data = bytes.fromhex(line[5:].strip())
            self.stream.feed(self.decoder.decode(data))
            return True

        if line.startswith("SETDEFAULTCOL "):
            rest = line[14:].strip()
            foreground, _space, background = rest.partition(" ")
            self.default_foreground = _read_colour(foreground)
            if background.strip():
                self.default_background = _read_colour(background.strip())
            return True

        return False

    # -- the assertions -------------------------------------------------

    def assertion(self, line: str) -> str:
        "The one line that answers one `?` form."
        name, _space, argument = line.partition(" ")
        argument = argument.strip()
        answer = {
            "?cursor": self.cursor,
            "?pen": self.pen,
            "?lineinfo": self.lineinfo,
            "?screen_chars": self.screen_chars,
            "?screen_text": self.screen_text,
            "?screen_cell": self.screen_cell,
            "?screen_eol": self.screen_eol,
            "?screen_attrs_extent": self.screen_attrs_extent,
        }.get(name)
        if answer is None:
            # What libvterm's own harness writes for a form it does not
            # know. The runner reads it as one answer and fails the
            # assertion, which is the honest result.
            return "?"
        return answer(argument)

    def cursor(self, argument: str) -> str:
        """
        The row and the column that the cursor stands on.

        A character in the last column leaves ptterm's cursor one column
        further, where it waits to wrap. libvterm keeps the wait in a
        flag of its own and never reports a column past the last one.
        `reported_column` is the same fold, and it is the column that
        ptterm gives a program that asks with DSR. So this answers what
        a program reads, in both models.
        """
        screen = self.screen
        assert screen is not None
        row = screen.pt_cursor_position.y - screen.line_offset
        return "%d,%d" % (row, screen.reported_column)

    def pen(self, argument: str) -> str:
        "One attribute of the style that the next character takes."
        screen = self.screen
        assert screen is not None
        attrs = screen._attrs

        if argument == "bold":
            return _switch(attrs.bold)
        if argument == "italic":
            return _switch(attrs.italic)
        if argument == "blink":
            return _switch(attrs.blink)
        if argument == "reverse":
            return _switch(attrs.reverse)
        if argument == "underline":
            return str(_underline_of_style(screen._rendition_str))
        if argument == "foreground":
            return self._colour(attrs.color, self.default_foreground, "fg")
        if argument == "background":
            return self._colour(attrs.bgcolor, self.default_background, "bg")
        # A font of its own, a smaller glyph and a raised or lowered
        # baseline are three things ptterm does not hold. It says so by
        # answering the value of a terminal that has none.
        if argument == "font":
            return "0"
        if argument == "small":
            return "off"
        if argument == "baseline":
            return "normal"
        return "?"

    def _line_attribute(self, row: int):
        "The DEC line attribute of one row of the visible screen, or None."
        screen = self.screen
        assert screen is not None
        return screen.line_attributes.get(screen.line_offset + row)

    def lineinfo(self, argument: str) -> str:
        """
        What a whole line carries: a double size, and a continuation.

        libvterm prints the three words in this order, and prints the
        double height without saying which half. `?screen_cell` is the
        one that says the half.

        `wrapped_lines` holds the index of each line that a wrap
        started, which is libvterm's `continuation` for the same line.
        """
        screen = self.screen
        assert screen is not None
        row = int(argument.split(",")[0])

        words = []
        attribute = self._line_attribute(row)
        if attribute is not None:
            if attribute.double_width:
                words.append("dwl")
            if attribute.double_height:
                words.append("dhl")
        if screen.line_offset + row in screen.wrapped_lines:
            words.append("cont")
        return " ".join(words)

    def screen_chars(self, argument: str) -> str:
        "Every character in a rectangle, as comma separated hex."
        characters = self._characters(argument)
        if not characters:
            return ""
        return ",".join("0x%02x" % ord(one) for one in characters)

    def screen_text(self, argument: str) -> str:
        "The same rectangle, as the bytes of its UTF-8."
        text = "".join(self._characters(argument))
        if not text:
            return ""
        return ",".join("0x%02x" % byte for byte in text.encode("utf-8"))

    def screen_cell(self, argument: str) -> str:
        "Everything one cell holds, in libvterm's own spelling."
        row, column = (int(number) for number in argument.split(",")[:2])
        cell = self.cell(row, column)
        style = _rendition_of(cell)

        characters = cell.char if isinstance(cell, TerminalChar) else ""
        inside = ",".join("0x%x" % ord(one) for one in characters)

        attributes = ""
        if "bold" in style:
            attributes += "B"
        underline = _underline_of_style(style)
        if underline:
            attributes += "U%d" % underline
        if "italic" in style:
            attributes += "I"
        if "blink" in style:
            attributes += "K"
        if "reverse" in style:
            attributes += "R"

        # The DEC line attributes of the line the cell is on. libvterm
        # copies them onto every cell of the line, and prints them
        # between the attributes and the colours.
        size = ""
        attribute = self._line_attribute(row)
        if attribute is not None:
            if attribute.double_width:
                size += "dwl "
            if attribute.double_height == DoubleHeight.TOP:
                size += "dhl-top "
            elif attribute.double_height == DoubleHeight.BOTTOM:
                size += "dhl-bottom "

        foreground = self._rgb(_color_of_style(style, ""), self.default_foreground)
        background = self._rgb(_color_of_style(style, "bg:"), self.default_background)
        return "{%s} width=%d attrs={%s} %sfg=%s bg=%s" % (
            inside,
            cell.width or 1,
            attributes,
            size,
            foreground,
            background,
        )

    def screen_eol(self, argument: str) -> str:
        "One when nothing is written from here to the end of the line."
        screen = self.screen
        assert screen is not None
        row, column = (int(number) for number in argument.split(",")[:2])
        for x in range(column, screen.columns):
            if isinstance(self.cell(row, x), TerminalChar):
                return "0"
        return "1"

    def screen_attrs_extent(self, argument: str) -> str:
        """
        How far the style of one cell reaches, left and right.

        libvterm counts the last column of the run and not the one after
        it, so a run that reaches the right edge of an eighty column
        screen ends at seventy nine.
        """
        screen = self.screen
        assert screen is not None
        row, column = (int(number) for number in argument.split(",")[:2])
        style = _rendition_of(self.cell(row, column))

        first = column
        while first > 0 and _rendition_of(self.cell(row, first - 1)) == style:
            first -= 1
        last = column
        while (
            last + 1 < screen.columns
            and _rendition_of(self.cell(row, last + 1)) == style
        ):
            last += 1
        return "%d,%d-%d,%d" % (row, first, row + 1, last)

    # -- what the three rectangle forms share ---------------------------

    def _characters(self, argument: str):
        """
        The characters of a rectangle, the way libvterm reads them out.

        An erased cell holds no character. libvterm counts one and puts
        a space there only when a cell that holds something comes after
        it, so the blanks at the end of a line go away and the blanks
        between two words stay. A space that a program wrote is a
        character, and it is kept.

        The second half of a double width character is a gap, and it
        gives nothing. `src/screen.c` holds all three rules.
        """
        screen = self.screen
        assert screen is not None
        numbers = [int(one) for one in argument.split(",") if one.strip()]
        if len(numbers) >= 4:
            first_row, first_column, end_row, end_column = numbers[:4]
        else:
            first_row = numbers[0]
            end_row = first_row + 1
            first_column, end_column = 0, screen.columns

        out = []
        for row in range(first_row, end_row):
            padding = 0
            for column in range(first_column, end_column):
                cell = self.cell(row, column)
                if cell.char == "":
                    continue
                if not isinstance(cell, TerminalChar):
                    padding += 1
                    continue
                out.extend(" " * padding)
                padding = 0
                out.extend(cell.char)
            if row < end_row - 1:
                out.append("\n")
        return out

    # -- colours --------------------------------------------------------

    def _colour(self, value, default, side: str) -> str:
        """
        What `?pen foreground` and `?pen background` answer.

        A style that names no colour is the default, and libvterm says
        which default it is. "SGR 39" and "SGR 49" put the default back
        by naming it, so the style then holds "#ansidefault", which
        stands for no colour as much as an empty style does.
        """
        colour = _read_style_colour(value) if value else None
        if colour is None:
            return "rgb(%d,%d,%d,is_default_%s)" % (default + (side,))
        return _spell(colour)

    def _rgb(self, colour, default) -> str:
        """
        What `?screen_cell` answers, which is always a real colour.

        libvterm turns a number of the palette into the colour it stands
        for before it prints a cell, and it drops the mark that says the
        colour was the default.
        """
        if colour is None:
            return "rgb(%d,%d,%d)" % default
        if colour[0] == "rgb":
            return "rgb(%d,%d,%d)" % tuple(colour[1:])
        return "rgb(%d,%d,%d)" % _ANSI_RGB[colour[1]]


def _switch(value) -> str:
    "How libvterm spells a flag that is on or off."
    return "on" if value else "off"


def _rendition_of(cell) -> str:
    "The style of a cell, without the hyperlink that is not a style."
    return " ".join(
        part for part in cell.style.split() if not part.startswith(_LINK)
    )


def _read_style_colour(value: str):
    "The colour that one style word names, as `_color_of_style` gives it."
    return _color_of_style(value if value.startswith("#") else "#" + value, "")


def _spell(colour) -> str:
    "A colour in the spelling that libvterm prints."
    if colour is None:
        return "invalid(0)"
    if colour[0] == "index":
        return "idx(%d)" % colour[1]
    return "rgb(%d,%d,%d)" % tuple(colour[1:])


def _read_colour(text: str):
    "The `rgb(r,g,b)` that `SETDEFAULTCOL` names."
    inside = text[text.index("(") + 1 : text.rindex(")")]
    return tuple(int(number) for number in inside.split(","))


#: The colour that libvterm paints each of the first sixteen numbers.
#: `?screen_cell` asks for a real colour, and this is the table it
#: converts with. `src/pen.c` builds the same one.
_ANSI_RGB = [
    (0, 0, 0),
    (224, 0, 0),
    (0, 224, 0),
    (224, 224, 0),
    (0, 0, 224),
    (224, 0, 224),
    (0, 224, 224),
    (224, 224, 224),
    (128, 128, 128),
    (255, 64, 64),
    (64, 255, 64),
    (255, 255, 64),
    (64, 64, 255),
    (255, 64, 255),
    (64, 255, 255),
    (255, 255, 255),
]

assert len(_ANSI_RGB) == len(ANSI_COLOR_NAMES)


def main() -> int:
    """
    Answer line after line until the runner closes the pipe.

    A failure inside one line goes to the standard error and the line
    still gets an answer. The runner dies when the pipe closes, and it
    then says nothing about the rest of the file, so one broken
    assertion must not take the file with it.
    """
    harness = Harness()

    for raw in sys.stdin:
        line = raw.rstrip("\n")
        if not line:
            continue

        if line.startswith("?"):
            try:
                answer = harness.assertion(line)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                answer = "!"
            sys.stdout.write(answer + "\n")
            sys.stdout.flush()
            continue

        try:
            known = harness.command(line)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            known = False
        sys.stdout.write("DONE\n" if known else "?\n")
        sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
