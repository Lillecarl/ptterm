"""
Improvements on Pyte.
"""
from enum import StrEnum

from pyte.escape import NEL as _NEL
from pyte.streams import Stream

__all__ = ("BetterStream",)


class Escape(StrEnum):
    """
    The byte that follows ESC, for the sequences ptterm adds.

    A member is a string, so pyte can look one up with the raw byte it
    read.
    """

    #: Next line. pyte gives it to the handler of LF, and the two
    #: differ: NEL always goes to the left margin.
    NEL = _NEL

    #: Back index. It moves the cursor one column to the left, and
    #: moves the scrolling region instead when the cursor stands on
    #: the left margin. pyte has neither this nor DECFI.
    DECBI = "6"

    #: Forward index, the other way round.
    DECFI = "9"

    #: Start of a protected area. It marks the cells a program draws
    #: next, so that an erase leaves them alone.
    SPA = "V"

    #: End of a protected area.
    EPA = "W"


class Csi(StrEnum):
    """
    The final byte of a CSI sequence, with its intermediate bytes in
    front of it.

    A CSI sequence ends with one final byte and can carry intermediate
    bytes before it. pyte joins the two into one key, so " q" is
    DECSCUSR and "q" on its own is something else. The matching pyte
    patch is what keeps the intermediate bytes.

    `ptterm/screen.py` holds the parameters of each sequence, in the
    docstring of the handler.
    """

    #: Cursor backward tabulation: move back over tab stops. pyte has
    #: neither this nor CHT.
    CBT = "Z"

    #: Cursor horizontal forward tabulation.
    CHT = "I"

    #: Copy rectangular area: copy a rectangle to another place.
    DECCRA = "$v"

    #: Delete column: take columns out of the scrolling region.
    DECDC = "'~"

    #: Erase rectangular area.
    DECERA = "$z"

    #: Fill rectangular area: write one character over a rectangle.
    DECFRA = "$x"

    #: Insert column, the other way round from DECDC.
    DECIC = "'}"

    #: Request checksum of a rectangular area. A conformance suite
    #: reads the screen back with it, so it is the instrument that
    #: judges the rest.
    DECRQCRA = "*y"

    #: Request mode: is this mode set?
    DECRQM = "$p"

    #: Select character protection attribute. It marks the cells a
    #: program draws next, so that a selective erase leaves them alone.
    DECSCA = '"q'

    #: Set cursor style. ptterm remembers it, so that DECRQSS can
    #: report it back.
    DECSCUSR = " q"

    #: Selective erase rectangular area: erase a rectangle, and leave
    #: the cells that DECSCA marked alone.
    DECSERA = "${"

    #: Set left and right margin. It answers only while private mode
    #: 69 is set, because the same final byte names SCOSC otherwise.
    DECSLRM = "s"

    #: Soft terminal reset. It keeps the screen and puts the settings
    #: back.
    DECSTR = "!p"

    #: Horizontal position absolute: the column of the screen. pyte
    #: gives it to the handler of CHA, and the two differ: CHA counts
    #: from the left margin in origin mode, and HPA does not.
    HPA = "`"

    #: Scroll down: move the lines of the scrolling region, without
    #: moving the cursor. pyte has neither this nor SU.
    SD = "T"

    #: Scroll up.
    SU = "S"

    #: The kitty keyboard protocol: push, pop, set or query the
    #: progressive enhancement flags. Parsing its ">", "<" and "="
    #: private markers needs the matching pyte patches.
    KITTY_KEYBOARD = "u"

    #: kitty's unscroll: bring lines back from the history. The
    #: intermediate space is part of the name, so this is not CUB.
    KITTY_UNSCROLL = " D"

    #: The name and the version of the terminal. A plain "CSI Ps q" is
    #: DECLL, which ptterm ignores.
    XTVERSION = "q"

    #: Window manipulation. Only the size and title reports are
    #: answered.
    XTWINOPS = "t"


class BetterStream(Stream):
    """
    Extension to the Pyte `Stream` class that also handles "Esc]<num>...BEL"
    sequences. This is used by xterm to set the terminal title.
    """

    escape = Stream.escape.copy()
    escape.update(
        {
            Escape.NEL: "next_line",
            Escape.DECBI: "back_index",
            Escape.DECFI: "forward_index",
            Escape.SPA: "start_protected_area",
            Escape.EPA: "end_protected_area",
        }
    )

    csi = Stream.csi.copy()
    csi.update(
        {
            Csi.CBT: "cursor_to_previous_tab",
            Csi.CHT: "cursor_to_next_tab",
            Csi.DECCRA: "copy_rectangle",
            Csi.DECDC: "delete_columns",
            Csi.DECERA: "erase_rectangle",
            Csi.DECFRA: "fill_rectangle",
            Csi.DECIC: "insert_columns",
            Csi.DECRQCRA: "report_checksum",
            Csi.DECRQM: "report_mode",
            Csi.DECSCA: "set_character_protection",
            Csi.DECSCUSR: "set_cursor_style",
            Csi.DECSERA: "selective_erase_rectangle",
            Csi.DECSLRM: "set_left_right_margins",
            Csi.DECSTR: "soft_reset",
            Csi.HPA: "cursor_to_absolute_column",
            Csi.SD: "scroll_down",
            Csi.SU: "scroll_up",
            Csi.KITTY_KEYBOARD: "report_kitty_keyboard",
            Csi.KITTY_UNSCROLL: "unscroll",
            Csi.XTVERSION: "report_version",
            Csi.XTWINOPS: "report_window",
        }
    )

    def __init__(self, screen) -> None:
        super().__init__()
        self.listener = screen
        self._validate_screen()

    def _validate_screen(self) -> None:
        """
        Check whether our Screen class has all the required callbacks.
        (We want to verify this statically, before feeding content to the
        screen.)
        """
        for d in [self.basic, self.escape, self.sharp, self.csi]:
            for name in d.values():
                assert hasattr(self.listener, name), "Screen is missing %r" % name

        for name in ("define_charset", "set_icon_name", "set_title", "draw", "debug"):
            assert hasattr(self.listener, name), "Screen is missing %r" % name
