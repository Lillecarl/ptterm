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

    #: Identify terminal. It is the older way to ask what DA asks, and
    #: a terminal answers it the same way. A VT100 had it; xterm keeps
    #: it, so a program written for one still gets an answer.
    DECID = "Z"


class Sharp(StrEnum):
    """
    The byte that follows "ESC #", for the sequences ptterm adds.

    These are the DEC line attributes of a VT100. They belong to the
    line the cursor stands on, and not to a cell. pyte names only
    DECALN, "ESC # 8".
    """

    #: Double height line, top half.
    DECDHL_TOP = "3"

    #: Double height line, bottom half. A program writes the same text
    #: on both halves, and the terminal draws each half of it.
    DECDHL_BOTTOM = "4"

    #: Single width, single height. The plain line, and what a reset
    #: leaves.
    DECSWL = "5"

    #: Double width, single height.
    DECDWL = "6"


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

    #: Select attribute change extent: what DECCARA and DECRARA reach.
    DECSACE = "*x"

    #: Select active status display: send the output to the status
    #: line, or to the screen.
    DECSASD = "$}"

    #: Set conformance level: which DEC terminal this one answers as.
    DECSCL = '"p'

    #: Set number of lines per screen.
    DECSNLS = "*|"

    #: Select status display type: what the status line holds.
    DECSSDT = "$~"

    #: Set left and right margin. It answers only while private mode
    #: 69 is set, because the same final byte names SCOSC otherwise.
    DECSLRM = "s"

    #: Soft terminal reset. It keeps the screen and puts the settings
    #: back.
    DECSTR = "!p"

    #: Horizontal position absolute: the column of the line. pyte gives
    #: it to the handler of CHA, and xterm moves the two alike, so
    #: ptterm keeps its own name for it and serves both the same way.
    HPA = "`"

    #: Horizontal position backward: columns to the left. It is the
    #: fourth of the position family, and the only one of the four that
    #: pyte does not name. ECMA-48 8.3.58 moves the cursor backward
    #: along the character path, which on this terminal is CUB.
    HPB = "j"

    #: Vertical position backward: rows up. ECMA-48 8.3.159, and the
    #: same relation to CUU that HPB has to CUB.
    VPB = "k"

    #: Repeat the last character that was drawn. It saves a program
    #: the bytes of a run of one character.
    REP = "b"

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
            Escape.DECID: "report_device_attributes",
        }
    )

    sharp = Stream.sharp.copy()
    sharp.update(
        {
            Sharp.DECDHL_TOP: "double_height_top",
            Sharp.DECDHL_BOTTOM: "double_height_bottom",
            Sharp.DECSWL: "single_width",
            Sharp.DECDWL: "double_width",
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
            Csi.DECSACE: "set_attribute_extent",
            Csi.DECSASD: "set_active_display",
            Csi.DECSCL: "set_conformance_level",
            Csi.DECSCUSR: "set_cursor_style",
            Csi.DECSERA: "selective_erase_rectangle",
            Csi.DECSNLS: "set_lines_per_screen",
            Csi.DECSSDT: "set_status_line_type",
            Csi.DECSLRM: "set_left_right_margins",
            Csi.DECSTR: "soft_reset",
            Csi.HPA: "cursor_to_absolute_column",
            # HPB and VPB move the way CUB and CUU move, so they go to
            # the same handlers. libvterm serves them from the same two
            # lines of arithmetic as well.
            Csi.HPB: "cursor_back",
            Csi.VPB: "cursor_up",
            Csi.REP: "repeat_last_character",
            Csi.SD: "scroll_down",
            Csi.SU: "scroll_up",
            Csi.KITTY_KEYBOARD: "report_kitty_keyboard",
            Csi.KITTY_UNSCROLL: "unscroll",
            Csi.XTVERSION: "report_version",
            Csi.XTWINOPS: "report_window",
        }
    )

    def __init__(self, screen) -> None:
        # `attach` is what builds the parser, so the screen goes to it
        # and not to `self.listener`. Setting the listener by hand
        # leaves a stream that raises on the first byte it reads.
        super().__init__(screen)
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
