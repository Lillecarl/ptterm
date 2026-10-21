"""
State a widget keeps apart for each application that draws it.

**One widget can be in several applications at once.** pymux puts a
pane in the layout of every client that shows it, and each client is an
application of its own. What a person changes by looking -- where they
scrolled to, what they selected -- belongs to the one who looks, and not
to the widget. `get_app()` says who that is: the application that draws
the frame, or whose key is being handled.

Copy mode is the first thing kept this way. Lillecarl/pymux#470.
"""

from __future__ import annotations

from collections.abc import Iterator
from weakref import WeakKeyDictionary

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app_or_none

__all__ = ["PerApplication"]


class PerApplication[T]:
    """
    One value for each application, and one for code that runs under
    none.

    The keys are weak, so an application that goes takes its value with
    it. **No application is a key of its own**, and not the
    `DummyApplication` that `get_app()` gives then: that is a new object
    on every call, so a value set under it could never be read back.
    """

    def __init__(self) -> None:
        self._values: WeakKeyDictionary[Application, T] = WeakKeyDictionary()
        self._alone: T | None = None

    def of(self, app: Application | None) -> T | None:
        "The value of `app`, or of no application when it is None."
        if app is None:
            return self._alone
        return self._values.get(app)

    def get(self) -> T | None:
        "The value of the application that runs now."
        return self.of(get_app_or_none())

    def set(self, value: T) -> None:
        app = get_app_or_none()
        if app is None:
            self._alone = value
        else:
            self._values[app] = value

    def pop(self) -> T | None:
        "Take the value of the application that runs now away, and give it."
        app = get_app_or_none()
        if app is None:
            value, self._alone = self._alone, None
            return value
        return self._values.pop(app, None)

    def items(self) -> Iterator[tuple[Application | None, T]]:
        "Every application that holds a value, and the value."
        yield from list(self._values.items())
        if self._alone is not None:
            yield None, self._alone
