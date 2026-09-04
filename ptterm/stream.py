"""
Improvements on Pyte.
"""
from pyte.escape import NEL
from pyte.streams import Stream

__all__ = ("BetterStream",)


class BetterStream(Stream):
    """
    Extension to the Pyte `Stream` class that also handles "Esc]<num>...BEL"
    sequences. This is used by xterm to set the terminal title.
    """

    escape = Stream.escape.copy()
    escape.update(
        {
            # Call next_line instead of line_feed. We always want to go to the left
            # margin if we receive this, unlike \n, which goes one row down.
            # (Except when LNM has been set.)
            NEL: "next_line",
            # DECBI ("ESC 6") and DECFI ("ESC 9"): move the cursor one
            # column, and move the scrolling region when the cursor
            # stands on a margin. pyte has neither.
            "6": "back_index",
            "9": "forward_index",
            # SPA ("ESC V") and EPA ("ESC W"): mark the cells that a
            # program draws next, so that an erase leaves them alone.
            "V": "start_protected_area",
            "W": "end_protected_area",
        }
    )

    csi = Stream.csi.copy()
    csi.update(
        {
            # The kitty keyboard protocol: push/pop/set/query the progressive
            # enhancement flags. (Parsing the ">", "<" and "=" private
            # markers requires the matching pyte patches.)
            "u": "report_kitty_keyboard",
            # Window manipulation. Only the size reports are answered.
            "t": "report_window",
            # XTVERSION ("CSI > q"): the name and the version of the
            # terminal. A plain "CSI Ps q" is DECLL, which we ignore.
            "q": "report_version",
            # DECRQM ("CSI ? Ps $ p"): is this mode set? (The "$" is an
            # intermediate byte, and needs the matching pyte patch.)
            "$p": "report_mode",
            # DECSCA ("CSI Ps " q"): mark the cells that a program
            # draws next, so that a selective erase leaves them alone.
            # ("\"" is an intermediate byte.)
            '"q': "set_character_protection",
            # DECSTR ("CSI ! p"): a soft reset. It keeps the screen and
            # puts the settings back. ("!" is an intermediate byte.)
            "!p": "soft_reset",
            # DECRQCRA ("CSI Pid ; Pp ; Pt ; Pl ; Pb ; Pr * y"): the
            # checksum of a rectangle. A conformance suite reads the
            # screen back with it, so it is the instrument that judges
            # the rest.
            "*y": "report_checksum",
            # DECSCUSR ("CSI Ps SP q"): the shape of the cursor. It is
            # remembered, so that DECRQSS can report it back.
            " q": "set_cursor_style",
            # HPA ("CSI Ps `"): the column of the screen. pyte gives it
            # to the handler of CHA, and the two differ: CHA counts
            # from the left margin in origin mode, and HPA does not.
            "`": "cursor_to_absolute_column",
            # CHT and CBT: move over tab stops, forward and back. pyte
            # has neither.
            "I": "cursor_to_next_tab",
            "Z": "cursor_to_previous_tab",
            # DECSLRM ("CSI Pl ; Pr s"): the columns of the scrolling
            # region. It answers only while private mode 69 is set;
            # the same final byte names SCOSC otherwise.
            "s": "set_left_right_margins",
            # DECIC ("CSI Pn ' }") and DECDC ("CSI Pn ' ~"): insert and
            # delete columns of the scrolling region. ("'" is an
            # intermediate byte.)
            "'}": "insert_columns",
            "'~": "delete_columns",
            # DECFRA ("CSI Pch ; Pt ; Pl ; Pb ; Pr $ x"): fill a
            # rectangle with one character. ("$" is an intermediate
            # byte.)
            "$x": "fill_rectangle",
            # SU and SD: move the lines of the scrolling region, without
            # moving the cursor. pyte has neither.
            "S": "scroll_up",
            "T": "scroll_down",
            # Kitty's unscroll. The intermediate space is part of the
            # name, so this is not CUB. (It needs the matching pyte
            # patch, which keeps intermediate bytes.)
            " D": "unscroll",
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

        for d in ("define_charset", "set_icon_name", "set_title", "draw", "debug"):
            assert hasattr(self.listener, name), "Screen is missing %r" % name
