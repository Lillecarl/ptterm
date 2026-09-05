"""
Read a colour spec with the real Xlib, so the port can be judged.

`ptterm/xcms.py` is a port of the colour management of Xlib. xterm
answers a colour query with what `XParseColor` gives it, so the port is
right only where it agrees with `XParseColor` itself.

This asks the real one. `PTTERM_LIBX11` names libX11, and `DISPLAY`
names a display that the check starts. The display matters: Xcms reads
the screen description from the root window, and a bare Xvfb carries
none, so Xlib falls back to its built-in description. That is the same
description xterm uses on such a screen, which is what the conformance
suite measures against.

The answer is three 16 bit components. On a screen of eight bits per
channel the low byte of each is zero, so `>> 8` gives what a pane
holds.
"""
import ctypes
import os
from typing import Tuple

__all__ = ["xlib_is_available", "xlib_color"]


class _XColor(ctypes.Structure):
    _fields_ = [
        ("pixel", ctypes.c_ulong),
        ("red", ctypes.c_ushort),
        ("green", ctypes.c_ushort),
        ("blue", ctypes.c_ushort),
        ("flags", ctypes.c_char),
        ("pad", ctypes.c_char),
    ]


class _Xlib:
    "One open display, and the two calls that read a colour spec."

    def __init__(self, path: str) -> None:
        self.library = ctypes.CDLL(path)
        self.library.XOpenDisplay.restype = ctypes.c_void_p
        self.library.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.library.XDefaultScreen.argtypes = [ctypes.c_void_p]
        self.library.XDefaultColormap.restype = ctypes.c_ulong
        self.library.XDefaultColormap.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.library.XParseColor.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_char_p,
            ctypes.POINTER(_XColor),
        ]
        self.display = self.library.XOpenDisplay(None)
        if not self.display:
            raise OSError("no display for the Xlib oracle")
        screen = self.library.XDefaultScreen(self.display)
        self.colormap = self.library.XDefaultColormap(self.display, screen)

    def parse(self, spec: str) -> Tuple[int, int, int] | None:
        color = _XColor()
        answered = self.library.XParseColor(
            self.display, self.colormap, spec.encode(), ctypes.byref(color)
        )
        if not answered:
            return None
        return color.red, color.green, color.blue


_XLIB: _Xlib | None = None
_TRIED = False


def _xlib() -> _Xlib | None:
    global _XLIB, _TRIED
    if not _TRIED:
        _TRIED = True
        path = os.environ.get("PTTERM_LIBX11")
        if path:
            _XLIB = _Xlib(path)
    return _XLIB


def xlib_is_available() -> bool:
    "True when `PTTERM_LIBX11` names a library that opens a display."
    return _xlib() is not None


def xlib_color(spec: str) -> Tuple[int, int, int] | None:
    """
    What `XParseColor` gives for `spec`, as three eight bit
    components, or `None` for a spec it refuses.
    """
    library = _xlib()
    assert library is not None
    answer = library.parse(spec)
    if answer is None:
        return None
    return answer[0] >> 8, answer[1] >> 8, answer[2] >> 8
