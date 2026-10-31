"""
The `Window` a terminal widget draws its control in.

It keeps the bottom of the screen in view, from the screen's own
numbers rather than from a prompt_toolkit cursor, and paints the pane
style over what the control drew.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from prompt_toolkit.layout.containers import (
    Window,
    WindowRenderInfo,
)
from prompt_toolkit.layout.screen import Point
from prompt_toolkit.mouse_events import MouseEvent

from .per_application import PerApplication

if TYPE_CHECKING:
    from .control import TerminalControl

__all__ = ["TerminalWindow"]


class _DrawnAt(NamedTuple):
    info: WindowRenderInfo
    horizontal_scroll: int


class TerminalWindow(Window):
    """ """

    def __init__(self, terminal_control: TerminalControl, **kw) -> None:
        self.terminal_control = terminal_control
        # pymux puts this one window in the layout of every client, so
        # `render_info` is whichever drew last. Lillecarl/pymux#713.
        self.drawn_at: PerApplication[_DrawnAt] = PerApplication()
        kw.setdefault("style", self._pane_style)
        # A pane owns every cell of its rectangle: a program left the
        # ones it never wrote at the default background, and the
        # terminal draws those. The fill writes them before the
        # content lands over them, so what shows is the default and
        # not whatever a layer below drew -- the layout background,
        # which is for the margins where no pane draws.
        kw.setdefault("char", " ")
        super().__init__(**kw)

    def _pane_style(self) -> str:
        """
        The style of the whole pane, blank cells included.

        DECSCNM ("CSI ? 5 h") reverses the screen, and the screen is
        more than the cells a program wrote: an empty row and the space
        after the last character both turn as well. prompt_toolkit fills
        the area of a window with the style of that window before it
        writes the content over it, so this is the one place that
        reaches every cell of the pane.

        `create_content` takes the reverse off a cell that already
        carries one, which is the other half. Lillecarl/pymux#95.
        """
        screen = self.terminal_control.screen
        if screen is not None and screen.has_reverse_video:
            return "reverse"
        return ""

    def write_to_screen(self, *a, **kw) -> None:
        # Make sure that the bottom of the terminal is always visible.
        screen = self.terminal_control.screen

        # NOTE: the +1 is required because max_y starts counting at 0, while
        #       lines counts the numbers of lines, starting at 1 for one line.
        self.vertical_scroll = screen.max_y - screen.lines + 1

        super().write_to_screen(*a, **kw)

    def _write_to_screen_at_index(self, screen, mouse_handlers, write_position, parent_style, erase_bg) -> None:
        """
        A click goes to the control at the cell it was on.

        prompt_toolkit's `Window` maps a click through the lines the
        content holds and clamps one below them to the last: on a screen
        with text on its first two rows, every click came to the cursor's
        row, at the first column. A terminal reports cells, so the cell
        is the answer. Lillecarl/pymux#654.
        """
        super()._write_to_screen_at_index(screen, mouse_handlers, write_position, parent_style, erase_bg)
        if write_position.width > 0 and write_position.height > 0 and self.render_info is not None:
            self.drawn_at.set(_DrawnAt(self.render_info, self.horizontal_scroll))
        else:
            self.drawn_at.pop()
        control = self.terminal_control
        left, top, scroll = write_position.xpos, write_position.ypos, self.vertical_scroll

        def handler(mouse_event: MouseEvent):
            return control.mouse_handler(
                MouseEvent(
                    position=Point(x=mouse_event.position.x - left, y=mouse_event.position.y - top + scroll),
                    event_type=mouse_event.event_type,
                    button=mouse_event.button,
                    modifiers=mouse_event.modifiers,
                )
            )

        mouse_handlers.set_mouse_handler_for_range(
            x_min=left,
            x_max=left + write_position.width,
            y_min=top,
            y_max=top + write_position.height,
            handler=handler,
        )
