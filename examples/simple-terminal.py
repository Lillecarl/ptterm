#!/usr/bin/env python
from __future__ import annotations

import anyio
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout

from ptterm import Terminal


async def main():
    def done():
        application.exit()

    term = Terminal(done_callback=done)
    application = Application(layout=Layout(container=term), full_screen=True)
    async with anyio.create_task_group() as task_group:
        await term.start(task_group)
        await application.run_async()
        # The application is gone, and the program may not be: leaving
        # the scope waits for its tasks, so end them.
        task_group.cancel_scope.cancel()


if __name__ == "__main__":
    anyio.run(main)
