"""
What runs behind a terminal widget: the protocol a program meets, and
the pty that runs one on this widget's screen.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from ptyhost.backends.posix import spawn_backend
from pyte.environment import preparing
from pyte.images import ASSUMED_CELL_HEIGHT, ASSUMED_CELL_WIDTH

if TYPE_CHECKING:
    import anyio.abc
    from ptyhost.backends import Backend

__all__ = ["Machinery", "Program", "create_backend"]


class Machinery(Protocol):
    "What a reader may ask of the machinery under a program."

    @property
    def pid(self) -> int | None: ...


class Program(Protocol):
    """
    What a terminal and its embedder ask of whatever runs behind it.

    A `ptyhost.Process` is one. An embedder may put something else in
    its place, which writes to the screen through `feed_output`: pymux
    shows a job that way, with no pty behind the pane.

    The data members are read-only here, so each implementation keeps
    its own attribute type.
    """

    @property
    def suspended(self) -> bool: ...

    @property
    def sx(self) -> int: ...

    @property
    def sy(self) -> int: ...

    @property
    def backend(self) -> Machinery: ...

    async def start(self, task_group: anyio.abc.TaskGroup) -> None: ...

    def get_name(self) -> str: ...

    def get_cwd(self) -> str | None: ...

    def kill(self) -> None: ...

    def hang_up(self) -> None: ...

    @property
    def is_terminated(self) -> bool: ...

    def set_size(self, width: int, height: int) -> None: ...

    def write_input(self, data: str) -> None: ...

    def suspend(self) -> None: ...

    def resume(self) -> None: ...


def create_backend(
    command: list[str],
    environment: Callable[[dict[str, str]], None] | None = None,
    directory: str | None = None,
) -> Backend:
    "A pty for `command`, which runs on this widget's screen: `ptyhost.backends.posix.spawn_backend` says why."
    return spawn_backend(command, preparing(environment), directory, cell=(ASSUMED_CELL_WIDTH, ASSUMED_CELL_HEIGHT))
