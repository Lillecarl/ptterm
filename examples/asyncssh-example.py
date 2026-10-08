#!/usr/bin/env python
from __future__ import annotations

import anyio
import asyncssh
from prompt_toolkit.application import Application, get_app
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from ptyhost.backends.asyncssh import AsyncSSHBackend

from ptterm import Terminal


async def main():
    style = Style(
        [
            ("title", "bg:#000044 #ffffff underline"),
        ]
    )

    async with asyncssh.connect("localhost", port=2222, username="jonathan") as client_connection:
        backend = AsyncSSHBackend(client_connection)

        kb = KeyBindings()

        @kb.add("c-x")
        def _(event):
            backend.kill()

        def done():
            get_app().exit()

        term = Terminal(
            backend=backend,
            style="class:terminal",
            done_callback=done,
        )

        application = Application(
            layout=Layout(
                container=HSplit(
                    [
                        Window(
                            height=1,
                            style="class:title",
                            content=FormattedTextControl(
                                HTML(' AsyncSSH: Press <u fg="#ff8888"><b>Control-X</b></u> to <b>exit</b>.')
                            ),
                        ),
                        term,
                    ]
                ),
                focused_element=term,
            ),
            style=style,
            key_bindings=kb,
            full_screen=True,
            mouse_support=True,
        )
        async with anyio.create_task_group() as task_group:
            await term.start(task_group)
            await application.run_async()
            # The application is gone, and the session may not be:
            # leaving the scope waits for its tasks, so end them.
            task_group.cancel_scope.cancel()


if __name__ == "__main__":
    anyio.run(main())
