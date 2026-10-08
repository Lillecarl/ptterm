#!/usr/bin/env python
from __future__ import annotations

import anyio
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.widgets import Dialog

from ptterm import Terminal


async def main():
    def done():
        application.exit()

    term = Terminal(width=D(preferred=60), height=D(preferred=25), done_callback=done)

    application = Application(
        layout=Layout(
            container=Dialog(title="Terminal demo", body=term, with_background=True),
            focused_element=term,
        ),
        full_screen=True,
        mouse_support=True,
    )
    async with anyio.create_task_group() as task_group:
        await term.start(task_group)
        await application.run_async()
        # The application is gone, and the program may not be: leaving
        # the scope waits for its tasks, so end them.
        task_group.cancel_scope.cancel()


if __name__ == "__main__":
    anyio.run(main)
