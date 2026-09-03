# Deviations from kitty

`tests/kitty_oracle.py` feeds the same bytes to ptterm and to the
emulator that kitty carries as a python extension, and compares the two
screens cell by cell.

- `test_against_kitty.py` holds sequences by hand.
- `test_corpus_against_kitty.py` replays what real programs wrote.
- `fuzz_against_kitty.py` builds random programs with hypothesis. It is
  a tool for hunting, not a gate: `nix-build -A checks.fuzz` in the
  pymux repository runs it, and `PYMUX_FUZZ` says how many examples.
- `test_known_deviations.py` holds every difference that stands, as a
  strict `xfail`. One that starts to pass means the difference is gone.

## Fixed by the comparison

- An erased cell took no background. htop draws the header of its table
  with "CSI K" and expects the colour to reach the end of the line.
- "CSI J" stopped at the last line in use instead of the bottom of the
  screen, and did nothing at all on a screen that held no cell yet.
- The first sixteen colours of the palette became numbers of their own
  instead of names, so a program that asked for "red" got the red of
  xterm and not the red of the theme of the user.
- SU and SD ("CSI S" and "CSI T") did nothing. pyte has neither.
- "CSI 2 L" dragged the lines above the cursor down with it.
- The blanks that "CSI @" and "CSI P" leave took no background, and an
  insert did not drop what falls off the right edge.

- A restore of the cursor was not faithful: it clamped the position
  into the margins that are set now, it read a stack instead of the
  one cursor that a terminal remembers, and it kept a row of the
  buffer instead of a row of the screen, so a scroll in between
  dragged the cursor back into the history.
- A margin held the cursor wherever it was, so a move up above the top
  margin moved the cursor down. "CSI r" homes the cursor, which puts
  it above the top margin nearly every time.
- DL left the cursor where it was. It moves to the first column, the
  same way IL does.

## Where ptterm follows xterm and kitty does something else

These four are in `test_known_deviations.py`. ptterm follows xterm in
each; a program is written against xterm, not against kitty.

1. A tab in the last column moves to the next line in kitty.
2. A backspace in the first column steps back to the end of the row
   above in kitty. xterm does that only with mode 45 set.
3. A count of zero for SU or SD means no scroll in kitty. Every other
   sequence that counts reads a zero as one, on both sides.
4. The line that a scroll brings in keeps the default style in kitty.
   xterm paints it with the background that is set.

## Open, found by the hunt and not looked at yet

Nothing. The hunt ran forty thousand examples after the last fix and
found no more.

Run it again to find more. Each one needs a decision about whether to
follow kitty or xterm before it becomes a fix.
