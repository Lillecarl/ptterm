"""
Some utilities.
"""
import array
import fcntl
import os
import termios
from ..graphics import ASSUMED_CELL_HEIGHT, ASSUMED_CELL_WIDTH

#: The pixel fields of `struct winsize` are unsigned shorts, and the
#: array that carries them is signed. Anything above this is not
#: reported.
MAX_WINSIZE_PIXELS = 32767

__all__ = (
    "pty_make_controlling_tty",
    "set_terminal_size",
    "nonblocking",
)


def pty_make_controlling_tty(tty_fd):
    """
    This makes the pseudo-terminal the controlling tty. This should be
    more portable than the pty.fork() function. Specifically, this should
    work on Solaris.

    Thanks to pexpect:
    http://pexpect.sourceforge.net/pexpect.html
    """
    child_name = os.ttyname(tty_fd)

    # Disconnect from controlling tty. Harmless if not already connected.
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
        if fd >= 0:
            os.close(fd)
    # which exception, shouldnt' we catch explicitly .. ?
    except:
        # Already disconnected. This happens if running inside cron.
        pass

    os.setsid()

    # Verify we are disconnected from controlling tty
    # by attempting to open it again.
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
        if fd >= 0:
            os.close(fd)
            raise Exception(
                "Failed to disconnect from controlling "
                "tty. It is still possible to open /dev/tty."
            )
    # which exception, shouldnt' we catch explicitly .. ?
    except:
        # Good! We are disconnected from a controlling tty.
        pass

    # Verify we can open child pty.
    fd = os.open(child_name, os.O_RDWR)
    if fd < 0:
        raise Exception("Could not open child pty, " + child_name)
    else:
        os.close(fd)

    # Verify we now have a controlling tty.
    if os.name != "posix":
        # Skip this on BSD-like systems since it will break.
        fd = os.open("/dev/tty", os.O_WRONLY)
        if fd < 0:
            raise Exception("Could not open controlling tty, /dev/tty")
        else:
            os.close(fd)


def set_terminal_size(stdout_fileno, rows, cols):
    """
    Set terminal size.

    (This is also mainly for internal use. Setting the terminal size
    automatically happens when the window resizes. However, sometimes the
    process that created a pseudo terminal, and the process that's attached to
    the output window are not the same, e.g. in case of a telnet connection, or
    unix domain socket, and then we have to sync the sizes by hand.)

    The size in pixels goes with it. A program that draws images reads
    it to work out how big a cell is, and a zero there says "I do not
    know", which leaves the program with no size to draw. The pixels
    follow the cell that `ptterm.graphics` assumes, so the answer
    agrees with what "CSI 14 t" and "CSI 16 t" report.
    """
    # Buffer for the C call
    # (The first parameter of 'array.array' needs to be 'str' on both Python 2
    # and Python 3.)
    buf = array.array(
        "h",
        [
            rows,
            cols,
            _pixels(cols, ASSUMED_CELL_WIDTH),
            _pixels(rows, ASSUMED_CELL_HEIGHT),
        ],
    )

    # Do: TIOCSWINSZ (Set)
    fcntl.ioctl(stdout_fileno, termios.TIOCSWINSZ, buf)


def _pixels(cells, cell_size):
    """
    The size of a number of cells in pixels, in the range that the C
    structure holds. A terminal too wide to count says nothing rather
    than a wrong number.
    """
    if cells <= 0:
        return 0
    size = cells * cell_size
    return size if size <= MAX_WINSIZE_PIXELS else 0


class nonblocking:
    """
    Make fd non blocking.
    """

    def __init__(self, fd):
        self.fd = fd

    def __enter__(self):
        self.orig_fl = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, self.orig_fl | os.O_NONBLOCK)

    def __exit__(self, *args):
        fcntl.fcntl(self.fd, fcntl.F_SETFL, self.orig_fl)
