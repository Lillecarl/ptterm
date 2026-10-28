"""
Copy mode: one person reading the history of a terminal.

**Each application that draws the terminal has a copy mode of its own**,
and the program goes on running under all of them. A view is a copy of
the buffer as it stood when the person opened it, with their caret,
their selection and their search over it, so a second person watching
the same pane sees it live. tmux does the same: `window_copy_init`
clones the pane's screen into `data->backing` and leaves the pane
running. Lillecarl/pymux#470.

`Terminal` holds the views, one for each application, in a
`PerApplication`, and shows the one of the application that draws.
"""

from __future__ import annotations

from bisect import bisect_right
from functools import cache
from typing import TYPE_CHECKING, override

from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.clipboard import ClipboardData
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_selection, vi_mode
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import ConditionalKeyBindings, DynamicKeyBindings, KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.bindings.basic import load_basic_bindings
from prompt_toolkit.key_binding.bindings.emacs import (
    load_emacs_bindings,
    load_emacs_search_bindings,
    load_emacs_shift_selection_bindings,
)
from prompt_toolkit.key_binding.bindings.page_navigation import load_page_navigation_bindings
from prompt_toolkit.key_binding.bindings.scroll import scroll_page_down
from prompt_toolkit.key_binding.bindings.vi import load_vi_bindings, load_vi_search_bindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import Float, FloatContainer, HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import (
    ConditionalProcessor,
    HighlightIncrementalSearchProcessor,
    HighlightSearchProcessor,
    HighlightSelectionProcessor,
    Processor,
    Transformation,
)
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.selection import SelectionType
from prompt_toolkit.token import KeepWhitespace
from prompt_toolkit.widgets.toolbars import SearchToolbar
from ptkhx import Mode
from ptkhx.bindings import HelixBindings
from pyte.cells import Cell, WrittenCell
from pyte.page import Page, RowMark, TextLine
from pyte.placeholders import PLACEHOLDER

from .style import style_of

if TYPE_CHECKING:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyPressEvent
    from prompt_toolkit.key_binding.key_bindings import Binding, KeyBindingsBase, KeyHandlerCallable

    from .terminal import Terminal

__all__ = ["CopyView", "copy_mode_key_bindings"]


class CopyView:
    """
    One person's copy mode over one terminal.

    It opens on a copy of the buffer, and the copy changes only when
    the person asks: the program writes on under it, and `refresh`
    takes a new copy.
    """

    def __init__(self, terminal: Terminal) -> None:
        self.terminal = terminal

        self.search_toolbar = SearchToolbar(forward_search_prompt="Search down: ", backward_search_prompt="Search up: ")

        # Read-only with tmux's keys. With Helix's a person may edit the
        # copy before copying it, and leaving copy mode drops the edits.
        # Lillecarl/pymux#751.
        self.buffer = _CopyBuffer(self, read_only=Condition(lambda: not self.helix_keys()))
        self.buffer.on_text_changed += self._follow_the_edit
        helix = _helix()
        self.control = _CopyBufferControl(
            self,
            buffer=self.buffer,
            search_buffer_control=self.search_toolbar.control,
            include_default_input_processors=False,
            input_processors=[
                _UseStyledTextProcessor(self),
                _HighlightSelectionWithoutTheWrap(),
                HighlightSearchProcessor(),
                HighlightIncrementalSearchProcessor(),
                # After the styled cells, which it paints over.
                ConditionalProcessor(helix.processor(), _HELIX_KEYS),
            ],
            preview_search=True,  # XXX: not sure why we need twice preview_search.
            key_bindings=merge_key_bindings(
                [
                    ConditionalKeyBindings(_reporting(self._keys()), ~_HELIX_KEYS),
                    # Last, so Helix's keys and copy mode's own over them
                    # win a tie.
                    helix.key_bindings,
                    helix.copy_keys,
                ]
            ),
            append_space=False,
        )

        #: Whether the pane was in reverse video when copy mode opened.
        self.reverse_video = False

        # The document holds the lines a program wrote, so a line that
        # the pane wrapped is one line here. The window wraps it again
        # at the width it has, which is what the pane did, so a person
        # sees the same shape and the copy holds no break that the
        # program did not write. Lillecarl/pymux#135.
        self.window = Window(
            content=self.control,
            wrap_lines=True,
            style=self._style,
        )

        #: The buffer as it stood when copy mode opened. `freeze` says
        #: what it holds.
        self.page = Page()

        #: The screen's count of writes when the copy was taken. Once it
        #: moves on, the corner says the copy is older than the pane.
        #: Lillecarl/pymux#714.
        self.writes = 0

        #: The lines of the document, and the ones of them that have
        #: been styled. `styled_line` says why they are built one at a
        #: time.
        self.lines: list[TextLine] = []
        self._styled_lines: dict[int, StyleAndTextTuples] = {}

        #: The document as `freeze` made it, and the one before the last
        #: edit.
        self._frozen = Document()
        self._before = Document()
        #: For each line of an edited document, the line of `lines` it
        #: still is, or None for a line an edit touched. None for the
        #: whole list while nothing is edited.
        self._origin: list[int | None] | None = None
        #: `refresh` was refused for the edits, and the corner says so.
        self.refresh_refused = False

        self.container = FloatContainer(
            content=HSplit([self.window, self.search_toolbar]),
            floats=[
                Float(
                    top=0,
                    right=0,
                    height=1,
                    content=Window(
                        content=FormattedTextControl(text=self._position_formatted_text),
                        style="class:copy-mode-cursor-position",
                    ),
                )
            ],
        )

    def _keys(self) -> KeyBindings:
        """
        The keys of copy mode.

        **They live with the copy buffer**, because the copy buffer is
        what they drive. pymux held four of them and read a flag that
        nothing had set since copy mode moved here, so `q`, `escape`
        and `v` did nothing at all and only ctrl-c left copy mode.
        Lillecarl/pymux#133.
        """
        kb = KeyBindings()

        @kb.add("c-c")
        @kb.add("q")
        @kb.add("escape")
        @kb.add("enter", filter=~has_selection)
        def _exit(event):
            "Leave copy mode. tmux leaves on all four of these."
            self.terminal.exit_copy_mode()

        @kb.add("space", filter=vi_mode)
        def _start_selection(event):
            "Start a selection here, or start it again from here."
            event.current_buffer.start_selection()

        @kb.add("space", filter=~vi_mode)
        def _page_down(event):
            """
            The page under this one.

            **tmux gives `Space` to a different job in each table.** It
            starts a selection with vi keys, and pages down with emacs
            keys, where `C-Space` is the one that starts a selection.
            Both tables started a selection here, so a person with
            emacs keys paging through their history started one instead
            and every arrow key after that dragged it.
            Lillecarl/pymux#379.

            prompt_toolkit binds `C-Space` to the selection already.
            """
            scroll_page_down(event)

        @kb.add("r")
        def _refresh(event):
            "tmux's `refresh-from-pane`, on the key both its tables give it."
            self.refresh()

        @kb.add("enter", filter=has_selection)
        @kb.add("y", filter=has_selection & vi_mode)
        @kb.add("c-w", filter=has_selection & ~vi_mode)
        @kb.add("escape", "w", filter=has_selection & ~vi_mode)
        def _copy_selection(event):
            """
            Copy the selection and leave copy mode.

            tmux leaves. `Enter` is `copy-pipe-and-cancel` in both of
            its tables, and `y` is what a person with vi keys binds to
            `copy-selection-and-cancel`; tmux itself leaves `y` unbound.
            prompt_toolkit has a `y` of its own, the vi yank operator,
            which fills the clipboard of the application and reaches no
            terminal. Lillecarl/pymux#376.

            `C-w` and `M-w` are the two tmux gives emacs keys, and they
            are the only copy keys such a person knows.
            Lillecarl/pymux#379.
            """
            self.copy_selection()
            self.terminal.exit_copy_mode()

        @kb.add("v", filter=has_selection & ~vi_mode)
        def _toggle_selection_type(event):
            """
            Swap between selecting characters and selecting lines.

            **With vi keys `v` is vi's**, which ends the selection, and
            `V` is the one that selects lines. A person with vi keys
            reads `v` as the key they know, so this takes the other
            half of the keyboard. Lillecarl/pymux#376.
            """
            selection_state = event.current_buffer.selection_state
            if selection_state is None:
                return
            if selection_state.type == SelectionType.CHARACTERS:
                selection_state.type = SelectionType.LINES
            else:
                selection_state.type = SelectionType.CHARACTERS

        return kb

    def helix_keys(self) -> bool:
        "Does the embedder ask for Helix's keys here?"
        keys = self.terminal.helix_keys
        return keys is not None and keys()

    @property
    def edited(self) -> bool:
        return self._origin is not None

    def _follow_the_edit(self, _buffer: Buffer) -> None:
        """
        Carry each line's origin through an edit, so a line the edit did
        not touch still draws with the colours its program gave it.

        The lines both texts start and end with are the same lines; the
        ones between are the edit's. A document back at what `freeze`
        made is not edited at all, whatever happened in between.
        """
        document = self.buffer.document
        before, self._before = self._before, document
        self.refresh_refused = False
        if document.text == self._frozen.text:
            self._origin = None
            return
        old, new = before.lines, document.lines
        limit = min(len(old), len(new))
        prefix = 0
        while prefix < limit and old[prefix] == new[prefix]:
            prefix += 1
        suffix = 0
        while suffix < limit - prefix and old[len(old) - 1 - suffix] == new[len(new) - 1 - suffix]:
            suffix += 1
        origin = self._origin if self._origin is not None else list(range(len(old)))
        self._origin = origin[:prefix] + [None] * (len(new) - prefix - suffix) + origin[len(old) - suffix :]

    def _line_of(self, index: int) -> TextLine | None:
        "The line of the copy that line `index` of the document still is."
        if self._origin is None:
            return self.lines[index] if index < len(self.lines) else None
        source = self._origin[index] if index < len(self._origin) else None
        return None if source is None else self.lines[source]

    def _index_of(self, source: int) -> int | None:
        "Where line `source` of the copy stands in the document now."
        if self._origin is None:
            return source
        try:
            return self._origin.index(source)
        except ValueError:
            return None

    def _position_formatted_text(self) -> str:
        """
        The line of the history the copy cursor is on, and how many there
        are, counted from the top: "[1/N]" is the oldest line.

        Not the window's `render_info.cursor_position`, which is the
        cursor's row on the screen and says nothing of where in the
        history the view stands.
        """
        document = self.buffer.document
        position = f"[{document.cursor_position_row + 1}/{document.line_count}]"
        refresh = "r"
        if _HELIX_KEYS():
            # Copy mode has no status line, and a search typed blind is no use.
            helix = _helix()
            position = f"{helix.pending_of(self.buffer) or helix.mode_of(self.buffer).label} {position}"
            refresh = "A-r"
        if self.refresh_refused:
            return position + " edited: u or y first"
        if self.edited:
            return position + " edited"
        if self.terminal.screen.writes != self.writes:
            return position + f" {refresh} for newer"
        return position

    def _style(self) -> str:
        """
        The style of the whole copy window, blank cells included.

        **The class is what makes a selection visible here.**
        prompt_toolkit marks a selection by reversing it, and `reverse`
        sets rather than toggles (`styles/style.py`), so on a reversed
        pane a selected cell and an unselected one both came out
        reversed and the selection could not be seen. A style rule for
        `reversed-pane selected` turns it back; class names accumulate
        left to right, and the window's style is prepended to every
        cell before a processor appends `class:selected`, so the rule
        matches. Lillecarl/pymux#99.
        """
        return "reverse class:reversed-pane" if self.reverse_video else ""

    def _cell_style(self, char) -> str:
        """
        The style of one cell of the copy buffer, with DECSCNM folded in.

        **The character it decides on is the one the cell holds, not the
        one it draws, and that is on purpose.** A pane blots out what a
        terminal cannot read -- a blank for a control, a blank for the
        image to go over (`style.visible_char`) -- because it has no copy
        to protect and the outer terminal must not be handed a character
        it cannot draw. Copy mode builds the text a person copies, so it
        keeps the program's bytes and lays a stand-in over them instead
        (`cell`). So a blank a program wrote keeps its column with
        `KeepWhitespace`; a cell that only draws as blank is not blank,
        and the document keeps what it holds. Lillecarl/pymux#449.
        """
        style = style_of(char.appearance)
        if self.reverse_video and char.appearance.rendition.reverse:
            style += " noreverse"
        if char.char == " " and isinstance(char, WrittenCell):
            style += " " + KeepWhitespace
        return style

    def cell(self, cell: Cell) -> tuple[str, str]:
        """
        How one cell of the copy buffer draws, and the character it holds.

        **Copy mode copies the characters a program wrote, and draws a
        stand-in for the ones a person cannot read.** A cell keeps the
        character it holds, so a copy takes the program's own bytes.
        prompt_toolkit supplies the stand-ins it knows -- `^A` for a
        control, an underlined blank for a non-breaking space -- and the
        one a cell of an image needs is drawn here. The pane does the
        opposite: it blots such a cell out. Lillecarl/pymux#449.
        """
        style = self._cell_style(cell)
        char = cell.char
        if char.startswith(PLACEHOLDER):
            # A cell of an image, which is a character no font has. The
            # pane draws a blank and the embedder puts the image over
            # it; copy mode has no image, so it draws a blank too,
            # underlined, to say the cell holds something and is not a
            # space the program wrote. The marks that carry the image's
            # row and column stay: a line of the display has to hold as
            # many characters as its line of the document, or
            # prompt_toolkit maps a selection position to the wrong
            # cell. The document keeps the raw cell, so a copy still
            # holds the placeholder.
            return style + " underline", " " + char[len(PLACEHOLDER) :]
        return style, char

    def copy_selection(self) -> None:
        """
        Put the selection on the clipboard of the user, and in the
        clipboard of the application.

        **The clipboard belongs to the terminal of the user**, which
        this widget does not own, so the embedder is handed the text.
        tmux does the same work in the same order -- the copy goes to
        a paste buffer of its own, and `set-clipboard` says whether it
        also goes out. Lillecarl/pymux#376.

        The clipboard of the application is the paste buffer of the
        session, which `paste-buffer` reads. It is written second, so
        that the selection type it carries is the one that stands.
        """
        self.copy(self.buffer.copy_selection())

    def copy(self, data: ClipboardData) -> None:
        "Put `data` on both clipboards, as `copy_selection` says."
        copy_func = self.terminal._copy_func
        if copy_func is not None and data.text:
            copy_func(data.text)

        get_app().clipboard.set_data(data)

    def half_window(self) -> int:
        """
        Half of what the copy window shows, in lines of the document.

        That is what the wheel scrolls by, and tmux's half-up and
        half-down are the same. Before the window has been drawn once
        there is no height to read, and the pane's own row count
        stands in for it.
        """
        info = self.window.render_info
        height = info.window_height if info else self.terminal.screen.lines
        return max(1, height // 2)

    def wheel_lines(self) -> int:
        "How far one notch of the wheel moves the caret: the embedder's answer, else half a window."
        lines = self.terminal.wheel_lines
        return max(1, lines()) if lines is not None else self.half_window()

    def shown_rows(self) -> tuple[int, int] | None:
        "The first and the last row of the buffer the last frame showed."
        info = self.window.render_info
        if info is None or not info.displayed_lines or not self.lines:
            return None
        shown = [line for index in info.displayed_lines if (line := self._line_of(index)) is not None]
        return (shown[0].first, shown[-1].last) if shown else None

    def where_shown(self, row: int, column: int) -> tuple[int, int] | None:
        """
        The cell of the application's screen, as (y, x), that a cell of
        the buffer was drawn at in the last frame, or None.

        A line of the document is a whole line of the buffer, wrapped
        again by the window, so the window's own map from text to screen
        says.
        """
        info = self.window.render_info
        lines = self.lines
        index = bisect_right(lines, row, key=lambda line: line.first) - 1
        if info is None or index < 0 or row > lines[index].last:
            return None
        # An edit moves lines and may have touched this one.
        shown = self._index_of(index)
        if shown is None:
            return None
        return info._rowcol_to_yx.get((shown, self.page.offset_in_line(lines[index], row, column)))

    def scroll(self, lines: int) -> None:
        """
        Move the caret this many lines, up when the number is negative.

        A move past either end stops there. The arithmetic is local and
        not `Document.get_cursor_up_position`, on purpose: the caret
        copy mode opens with stands one past the last character (#189),
        and from there the document answers with a negative position,
        which the buffer then reads back clamped to nothing -- the view
        froze at the top of the history and every wheel after it moved
        from a caret nobody could see.
        """
        buffer = self.buffer
        text = buffer.document.text
        position = max(0, min(buffer.cursor_position, len(text)))
        index = text.count("\n", 0, position)
        column = position - (text.rfind("\n", 0, position) + 1)
        split = text.split("\n")
        target = max(0, min(len(split) - 1, index + lines))
        new_position = sum(len(line) + 1 for line in split[:target]) + min(column, len(split[target]))
        buffer.cursor_position = new_position

    def jump_to_mark(self, mark: RowMark, down: bool) -> None:
        """
        Put the caret at the start of the next line down, or up, that a
        shell marked with `mark`. No such line leaves it where it is.

        tmux's `next-prompt` and `previous-prompt`
        (`window_copy_cursor_prompt`), which go to the start of the line
        too. Lillecarl/pymux#500.
        """
        rows = self.page.data_buffer
        document = self.buffer.document
        here = document.cursor_position_row
        candidates = range(here + 1, document.line_count) if down else range(here - 1, -1, -1)
        for index in candidates:
            line = self._line_of(index)
            if line is not None and any(
                (row := rows.get(number)) is not None and row.marks & mark
                for number in range(line.first, line.last + 1)
            ):
                self.buffer.cursor_position = self.buffer.document.translate_row_col_to_index(index, 0)
                return

    def freeze(self) -> None:
        """
        Copy the buffer, and put the whole of it, history and all, into
        the document.

        It is a method of its own because it is the work: entering copy
        mode is this and a focus, and this is the part that grows with
        the history. `tests/measure_instructions.py` measures it under
        "history <depth> (copy)". Lillecarl/pymux#131.

        **The copy takes the rows of the screen and shares the rows of
        the history.** The program goes on writing, and it writes into a
        row of the screen in place. A row of the history it never writes
        again: it scrolls rows in, drops them off the top (the history
        limit, `clear-history`) and lays them out again on a resize, and
        each of those takes a row out of the buffer or puts a new one in.
        A copy that holds the row object keeps the row. So the work is
        one copy of the table and a copy of each row of the screen, and
        not a copy of fifty thousand rows.

        The one thing the program changes on a row of the history is its
        wrap mark (`Screen._forget_the_wrap_marks`), so nothing here reads
        the mark after the lines are made: `styled_line` takes a line's
        rows from the line and not from the marks.

        **It reads lines and not rows.** A row is a line cut to fit the
        pane, and a person copying wants the line. So a search crosses
        a wrap, a selection of one line is one line, and the width the
        history was laid out at does not reach the document at all.
        Lillecarl/pymux#135.
        """
        screen = self.terminal.screen
        live = screen.page.data_buffer

        # DECSCNM reverses the whole screen, and copy mode shows the
        # same screen stopped. `_style` paints the reverse over the
        # window, the way `_Window` does for the pane, and a cell that
        # "SGR 7" already reversed turns the other way here.
        # Lillecarl/pymux#96.
        self.reverse_video = screen.has_reverse_video
        self.writes = screen.writes

        page = Page()
        rows = page.data_buffer
        rows.update(live)
        # Every row from the top of the screen down, and not the screen's
        # height of them: a row a shorter screen left below it is still
        # one the program may write again.
        for number in range(screen.line_offset, max(live, default=-1) + 1):
            row = live.get(number)
            if row is not None:
                kept = type(row)()
                kept.update(row)
                kept.wrapped = row.wrapped
                kept.marks = row.marks
                rows[number] = kept
        self.page = page

        lines: list[TextLine] = []
        if rows:
            # **Without the spaces at the end of a line**, as tmux has it:
            # every move and every copy of `window-copy.c` measures a row
            # with `grid_line_length`, which stops at the last cell that is
            # not a space. A program that pads each row to the width, as
            # Claude Code does, otherwise put `gl` and `gs` at the right
            # edge and a copy of a line ran on with blanks.
            lines = page.text_lines(min(rows), max(rows), trailing_spaces=False)

        text_str = "\n".join(line.text for line in lines)

        # Before the document, so `_follow_the_edit` finds nothing edited.
        self._frozen = self._before = Document(
            text=text_str,
            cursor_position=self._where_the_pane_is(lines, text_str),
        )
        self.buffer.set_document(self._frozen, bypass_readonly=True)
        self._origin = None

        self.lines = lines
        self._styled_lines = {}

    def refresh(self) -> None:
        """
        Take a new copy of the buffer, and keep the caret where it was.

        A row keeps its number while the program writes, so the caret
        goes back to the line that starts at the same row, at the same
        offset. A line the history limit dropped puts it on the first
        line. A selection does not survive, because its positions name
        the old document. tmux keeps the distance from the top of the
        history (`window_copy_cmd_refresh_from_pane`), which is the
        same place until the limit drops a row.

        **Not over edits.** A new copy would drop them without a word, so
        it is refused, and the corner says to undo them or copy first.
        Lillecarl/pymux#751.
        """
        if self.edited:
            self.refresh_refused = True
            return
        document = self.buffer.document
        index = document.cursor_position_row
        offset = document.cursor_position_col
        first = self.lines[index].first if index < len(self.lines) else None

        self.buffer.exit_selection()
        self.freeze()
        # The undo history of Helix's editor names the old copy.
        if self.helix_keys():
            _helix().reset(self.buffer)

        lines = self.lines
        if first is None or not lines:
            return
        number = max(0, bisect_right(lines, first, key=lambda line: line.first) - 1)
        offset = min(offset, len(lines[number].text))
        self.buffer.cursor_position = self.buffer.document.translate_row_col_to_index(number, offset)

    def _where_the_pane_is(self, lines: list[TextLine], text: str) -> int:
        """
        Where in the copy document the cursor of the pane stands.

        **Copy mode opens on what a person was looking at**, and not at
        the end of the whole flattened buffer, which is where a shell
        prompt happens to be and is nowhere in particular for a program
        that draws its own screen. The window follows the cursor, so on
        a full screen program it would scroll away from the screen as
        copy mode opened. Lillecarl/pymux#189.

        The rows of the buffer and the offsets in the document are two
        countings of the same cells, and `Page.offset_in_line` is the
        one place that turns one into the other.

        **Nothing here walks the lines.** Copy mode opens on fifty
        thousand of them and this runs while a person waits, which is
        what `tests/instruction-budgets.txt` holds it to. The lines
        come in row order, so the one that holds a row is the last one
        that starts at or before it, and `Document` counts the
        characters before a line with the same list of line starts
        that drawing the window needs anyway.
        """
        where = self.terminal.screen.pt_cursor_position

        number = bisect_right(lines, where.y, key=lambda line: line.first) - 1
        if number < 0 or where.y > lines[number].last:
            # A cursor on no line of the range. The end is where copy
            # mode always opened, so it is the honest answer for a
            # buffer that does not hold the cursor's row at all.
            return len(text)

        column = self.page.offset_in_line(lines[number], where.y, where.x)
        return Document(text).translate_row_col_to_index(number, column)

    def styled_line(self, number: int) -> StyleAndTextTuples:
        """
        One line of the copy buffer, as the styles a person sees.

        **It is built when it is asked for, and not before.** A window
        shows a screenful, and the history behind it can be fifty
        thousand rows: styling all of them cost 22,924,756 bytecode
        instructions at that depth, and a person waited for it after
        pressing a key. Lillecarl/pymux#131.

        The answer is kept, because the copy never changes. An edit
        changes the document over it: a line the edit did not touch is
        still a line of the copy, and one it did is plain text.
        Lillecarl/pymux#751.
        """
        if self._origin is not None:
            source = self._origin[number] if 0 <= number < len(self._origin) else None
            if source is None:
                document = self.buffer.document
                return [("", document.lines[number])] if 0 <= number < document.line_count else []
            number = source
        line = self._styled_lines.get(number)
        if line is not None:
            return line

        line = []
        if 0 <= number < len(self.lines):
            shown = self.lines[number]
            # The cells of each row, the way `Page.text_lines` joined
            # them into the line's text.
            rows = self.page.data_buffer
            for row_number in range(shown.first, shown.last + 1):
                row = rows.get(row_number)
                if row:
                    for column in range(max(row) + 1):
                        line.append(self.cell(row[column]))
            # The spaces `freeze` took off the end of the text: one cell
            # each, and the line must hold no more characters than its text.
            excess = sum(len(text) for _, text in line) - len(shown.text)
            if excess > 0:
                del line[-excess:]
        self._styled_lines[number] = line
        return line


class _CopyBufferControl(BufferControl):
    """
    The buffer of copy mode, and the wheel over it.

    A subclass because the base `BufferControl` refuses the wheel
    (`prompt_toolkit/layout/controls.py:901`): here the wheel moves the
    caret `CopyView.wheel_lines`, and the wheel down that reaches the bottom is
    the live screen again -- tmux's `-e`, which leaves copy mode when
    the person scrolls back to where the program stands.
    """

    def __init__(self, view: CopyView, **kw) -> None:
        super().__init__(**kw)
        self.view = view

    def mouse_handler(self, mouse_event):
        buffer = self.buffer
        view = self.view
        at_the_bottom = buffer.cursor_position >= len(buffer.document.text)

        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            view.scroll(-view.wheel_lines())
            return None

        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            if at_the_bottom:
                view.terminal.exit_copy_mode()
            else:
                view.scroll(view.wheel_lines())
                if buffer.cursor_position >= len(buffer.document.text):
                    # The scroll that reached the bottom leaves copy
                    # mode with it.
                    view.terminal.exit_copy_mode()
            return None

        return super().mouse_handler(mouse_event)


class _CopyBuffer(Buffer):
    """
    The buffer of copy mode, whose caret never stands on a line break.

    prompt_toolkit puts it there: `$` is `get_end_of_line_position()`,
    which is one past the last character, and `l` stops in the same
    place. That is where an editor puts what a person types next, and
    copy mode has nothing to type. A vi selection takes the character
    under the caret, so a selection to the end of a line took the break
    with it: the copy carried a line ending nobody selected, and the
    window drew one selected cell at the start of the row under it.
    Lillecarl/pymux#377.

    vi does not allow the caret there, and neither does tmux:
    `window_copy_cursor_limit` returns `grid_line_limit`, the last
    character of the row, and `window_copy_find_length`, one past it,
    only when `mode-keys` is not vi. So this holds for vi keys alone.

    **A move of the caret is clamped, and the opening of copy mode is
    not.** Copy mode opens where the cursor of the pane stands, which is
    where the next character goes and is past the last character of a
    shell prompt. `CopyView.freeze` sets the whole document, which does
    not come through here. Lillecarl/pymux#189.
    """

    def __init__(self, view: CopyView, **kw) -> None:
        super().__init__(**kw)
        #: How a key bound for every copy view finds the one it is for.
        self.view = view

    @property
    def cursor_position(self) -> int:
        return Buffer.cursor_position.fget(self)

    @cursor_position.setter
    def cursor_position(self, value: int) -> None:
        Buffer.cursor_position.fset(self, self._off_the_line_break(value))

    def _off_the_line_break(self, position: int) -> int:
        if not vi_mode():
            return position

        text = self.text
        if position < len(text) and text[position] != "\n":
            return position

        # The start of the line is as far back as this goes. An empty
        # line has nowhere else to stand.
        if position > 0 and text[position - 1] != "\n":
            return position - 1
        return position


def _view() -> CopyView | None:
    # Not `current_buffer`, which builds a Buffer whenever a pane has
    # the focus, and every key in a pane asks this. Lillecarl/pymux#773.
    control = get_app().layout.current_control
    return control.view if isinstance(control, _CopyBufferControl) else None


@Condition
def _HELIX_KEYS() -> bool:
    "The copy view in front takes Helix's keys: its embedder asks for them."
    view = _view()
    return view is not None and view.helix_keys()


@Condition
def _EMBEDDER_FIRST() -> bool:
    "The embedder takes the next key, as pymux does after its prefix."
    view = _view()
    takes = view.terminal.terminal_control.takes_key_first if view is not None else None
    return takes is not None and takes()


def _tell_the_terminal(buffer: Buffer, keys: str) -> None:
    report = buffer.view.terminal.on_copy_command if isinstance(buffer, _CopyBuffer) else None
    if report is not None:
        report(keys)


def _key_of(event: KeyPressEvent) -> str:
    key = event.key_sequence[-1].key
    return key.value if isinstance(key, Keys) else key


@cache
def copy_mode_key_bindings() -> DynamicKeyBindings:
    """
    prompt_toolkit's own vi and emacs keys, the ones every application
    holds, again, so that in copy mode each tells the terminal what it
    ran through `Terminal.on_copy_command`. Nothing public says which
    handler a key reached. Lillecarl/pymux#773.

    **An embedder puts these under its own bindings**, where the
    application's copies rank, and so shadows those with the same
    handlers. On the copy buffer's control they would rank over the
    embedder's, and its prefix would move the caret.

    Dynamic rather than conditional: a condition on each binding is
    asked for every binding a key could reach, and a key in a pane
    paid a tenth more for it in checks.pymux-keystroke.
    """
    defaults = merge_key_bindings(
        [
            load_basic_bindings(),
            load_emacs_bindings(),
            load_emacs_search_bindings(),
            load_emacs_shift_selection_bindings(),
            load_vi_bindings(),
            load_vi_search_bindings(),
            load_page_navigation_bindings(),
        ]
    )
    reporting = _reporting(defaults)

    def in_copy_mode() -> KeyBindings | None:
        view = _view()
        return reporting if view is not None and not view.helix_keys() else None

    return DynamicKeyBindings(in_copy_mode)


def _reporting(bindings: KeyBindingsBase) -> KeyBindings:
    kb = KeyBindings()
    for binding in bindings.bindings:
        kb.add(
            *binding.keys,
            filter=binding.filter,
            eager=binding.eager,
            is_global=binding.is_global,
            save_before=binding.save_before,
            record_in_macro=binding.record_in_macro,
        )(_reported(binding))
    return kb


def _reported(binding: Binding) -> KeyHandlerCallable:
    """
    `binding`'s handler, telling the terminal the keys it was bound to.

    The bound keys and not the pressed ones: `Keys.Any` stands for a
    character the buffer holds, as in vi's `f`, and that stays out.
    """
    names = [key.value if isinstance(key, Keys) else key for key in binding.keys if key is not Keys.Any]
    name = ("" if all(len(each) == 1 for each in names) else " ").join(names)
    handler = binding.handler

    def reported(event: KeyPressEvent):
        if name:
            _tell_the_terminal(event.current_buffer, name)
        return handler(event)

    return reported


class _CopyHelix(HelixBindings):
    """
    Helix's keys in copy mode, in normal mode on entry. The copy can be
    edited before it is copied. Lillecarl/pymux#751.

    **One for every copy view.** It binds some four hundred keys, and
    building them on each entry into copy mode would cost that entry,
    which a person waits for. The editors hang off the buffers, so each
    view keeps its own selection, and a key finds its view through the
    buffer it reaches.

    tmux's leaving and copying keys sit over Helix's outside insert
    mode: `y` and Enter copy the selection and leave, `q` and Escape in
    normal mode leave. `r` is Helix's replace, so `Alt-r` takes a new
    copy.
    """

    def __init__(self) -> None:
        super().__init__(
            initial_mode=Mode.NORMAL,
            filter=_HELIX_KEYS & ~_EMBEDDER_FIRST,
            accept=_copy_and_leave,
        )
        self.on_command = _tell_the_terminal
        self.copy_keys = self._copy_keys()

    def _copy_keys(self) -> ConditionalKeyBindings:
        kb = KeyBindings()

        @kb.add("c-c")
        def _leave(event: KeyPressEvent) -> None:
            _tell_the_terminal(event.current_buffer, _key_of(event))
            event.current_buffer.view.terminal.exit_copy_mode()

        # Not while a key waits for another or a regex is typed, nor in
        # insert mode: `fq` finds a `q`, a search may hold a `y`, and
        # typing writes them.
        def idle() -> bool:
            buffer = get_app().current_buffer
            return not self.pending_of(buffer) and self.mode_of(buffer) is not Mode.INSERT

        kb.add("q", filter=Condition(idle))(_leave)

        # Enter by name too: prompt_toolkit's own Enter names it, and
        # beats the editor's catch-all.
        @kb.add("y", filter=Condition(idle))
        @kb.add("enter", filter=Condition(idle))
        def _copy(event: KeyPressEvent) -> None:
            _tell_the_terminal(event.current_buffer, _key_of(event))
            _copy_and_leave(event.current_buffer, event.app)

        # Several cursors type through the editor, which owns the text then,
        # and prompt_toolkit's Enter, which names the key and so beats the
        # editor's catch-all, broke one line only for the editor to write
        # its own text back over it. One cursor keeps prompt_toolkit's.
        def typing_at_several() -> bool:
            editor = self.editor_for(get_app().current_buffer)
            return editor.mode is Mode.INSERT and editor.owns_input

        @kb.add("enter", filter=Condition(typing_at_several))
        def _break_each_line(event: KeyPressEvent) -> None:
            self.insert_text(event.current_buffer, "\n")

        # After Helix's own `escape r` in the merge, so this wins the tie.
        @kb.add("escape", "r", filter=Condition(idle))
        def _refresh(event: KeyPressEvent) -> None:
            event.current_buffer.view.refresh()

        return ConditionalKeyBindings(kb, Condition(self._active))

    @override
    def before_escape(self, event: KeyPressEvent) -> bool:
        "Escape in normal mode, with nothing half typed, leaves copy mode."
        buffer = event.current_buffer
        if self.mode_of(buffer) is not Mode.NORMAL or self.pending_of(buffer):
            return False
        buffer.view.terminal.exit_copy_mode()
        return True


def _copy_and_leave(buffer: Buffer, _app: Application) -> None:
    """
    Copy every selection, one to a line, and leave copy mode.

    One string is all a clipboard holds, so the selections are joined
    the way Helix joins them for its own clipboard register.

    """
    view = buffer.view
    editor = _helix().editor_for(buffer)
    view.copy(ClipboardData("\n".join(editor.selection.fragments(editor.text))))
    view.terminal.exit_copy_mode()


@cache
def _helix() -> _CopyHelix:
    return _CopyHelix()


class _HighlightSelectionWithoutTheWrap(HighlightSelectionProcessor):
    """
    A selection highlights the cells of its line and no cell past them.

    The base processor appends a space for the newline a selection
    reaches, so an empty selected line shows as selected. Copy mode's
    window wraps, so on a line that already fills the pane that space
    is one cell too many: the line grows a second, blank row, and a vi
    line selection over full-width lines drew an empty line under
    each. Lillecarl/pymux#483.
    """

    def apply_transformation(self, transformation_input) -> Transformation:
        cells = len(transformation_input.fragments)
        result = super().apply_transformation(transformation_input)
        fragments = result.fragments
        if cells and len(fragments) == cells + 1:
            style, text = fragments[-1][0], fragments[-1][1]
            if text == " " and "class:selected" in style:
                return Transformation(fragments[:-1])
        return result


class _UseStyledTextProcessor(Processor):
    """
    The styled cells of the line, in place of the document's plain text.

    It goes before every other processor, because it replaces the list
    of (style, text) tuples they work on.
    """

    def __init__(self, view: CopyView) -> None:
        self.view = view

    def apply_transformation(self, transformation_input) -> Transformation:
        return Transformation(self.view.styled_line(transformation_input.lineno))
