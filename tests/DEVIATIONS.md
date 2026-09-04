# Deviations from kitty

`tests/kitty_oracle.py` feeds the same bytes to ptterm and to the
emulator that kitty carries as a python extension, and compares the two
screens cell by cell. `tests/vterm_oracle.py` does the same with
libvterm, the emulator that Vim and Neovim carry.

**Two emulators make a vote, and a vote says more than a comparison.**
Where kitty and libvterm agree and ptterm differs, ptterm is wrong and
nobody has to decide anything. Where the two disagree, the difference
is a real choice. `three_way` answers "agree", "ptterm-wrong" or
"split", and the hunt asserts that "ptterm-wrong" never happens.

- `test_against_kitty.py` holds sequences by hand.
- `test_corpus_against_kitty.py` replays what real programs wrote.
- `fuzz_against_kitty.py` builds random programs with hypothesis. It is
  a tool for hunting, not a gate: `nix-build -A checks.fuzz` in the
  pymux repository runs it, and `PYMUX_FUZZ` says how many examples.
- `test_against_vterm.py` compares against libvterm and holds the vote
  on every difference that stands.
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

- A write over one half of a double width character left the other
  half behind, and a character that needs two columns wrapped one
  column too late, so it wrote past the last column.
- A combining mark after a double width character landed in the empty
  second half, so the character never got it.
- A CSI sequence that carries more parameters than its command takes
  raised a TypeError in pyte and stopped the whole stream. One stray
  sequence took the pane with it.
- The first visible line followed the cursor as well as the content, so
  a cursor that moved above it pulled the screen back into the history
  and hid the line that a program had just written.
- A move down that starts above the scrolling region stopped at the
  bottom margin, and a move up that starts below it stopped at the top
  margin. The screen stops both now.
- "ESC ( 0" names the line drawing set of the DEC terminals, which is
  how ncurses draws a box. pyte dropped it in UTF-8 mode and the screen
  had no handler for it either, so a box came out as the letters "lqk".
- A tab found a stop past the last column, put the cursor there, and
  the next character wrapped to the line below.
- Only "?1049" took the alternate screen. A program that sends "?47" or
  "?1047" drew over the shell it came from.
- A terminal keeps one alternate screen for its whole life and hands it
  back with what it held. ptterm made a new one on every switch, so a
  program that takes the screen with "?47" or "?1047", which do not
  clear it, found it empty. The vote called this one: kitty and
  libvterm both keep the content.
- "?1049" does what "ESC 7" and "ESC 8" do, on the screen it comes
  from: it saves the place, the rendition and the character sets, and
  brings them back. The screen did none of that, so a colour set on the
  alternate screen stayed on the shell behind it. "?47" and "?1047"
  save nothing, so the cursor stays where the program left it.
- The scrolling region and the saved cursor sat on the wrong side of
  the switch: the region belongs to the terminal and survives it, and
  the saved cursor belongs to one screen and does not.
- A restore with nothing saved kept the character set that "ESC ( 0"
  had picked, instead of the one a terminal starts with.
- G1 held the line drawing set before any program named it, so a stray
  shift out turned every letter into a box character.
- A linefeed, an index and a move down left the cursor past the last
  column, where a character waits to wrap. A move ends that wait, so
  the next character went to the line below instead of the last column.

- A restore of the cursor was not faithful: it clamped the position
  into the margins that are set now, it read a stack instead of the
  one cursor that a terminal remembers, and it kept a row of the
  buffer instead of a row of the screen, so a scroll in between
  dragged the cursor back into the history.
- A margin held the cursor wherever it was, so a move up above the top
  margin moved the cursor down. "CSI r" homes the cursor, which puts
  it above the top margin nearly every time.
- The bounds let the cursor sit one row below the last, so a position
  past the bottom of the screen drew a line that pushed the screen
  into the history. DECALN found it: a full screen makes the drift
  visible where a blank one hides it.
- DECALN ("ESC # 8") drew the pattern and did nothing else. The DEC
  manuals also put the margins back to the whole screen and send the
  cursor home, and kitty does both; libvterm does neither, so the vote
  calls this a split and the manual breaks the tie.
- CHT and CBT ("CSI Ps I" and "CSI Ps Z") did nothing at all: pyte has
  neither. kitty and libvterm agree on both, so the vote called it a
  bug with nothing to decide.
- DL left the cursor where it was. It moves to the first column, the
  same way IL does.
- A tab ended the wait to wrap. A character in the last column leaves
  the cursor waiting, and a tab cleared that wait, so the character
  after the tab landed over the one that is there. The whole panel
  puts it on the next line: four judges to nothing, and only a
  document behind ptterm. The tab is the one cursor move that does not
  end the wait.

## Where ptterm follows xterm and kitty does something else

These six are in `test_known_deviations.py` and in `test_against_vterm.py`. ptterm follows xterm in
each; a program is written against xterm, not against kitty.

**libvterm draws what ptterm draws in every one of these.** That was a
reading of the documentation before; it is now a second
implementation, and the vote calls these a split and not a bug.

**The tab was the exception, and the panel closed it.** A tab that
fills the last column and ends the program leaves the same screen
everywhere. One character after it told the three apart: kitty and
libvterm put it on the next line, and ptterm cleared the wait to wrap,
so the character landed over the one that is there. The vote called
that "ptterm-wrong", and ptterm now leaves the wait alone. What is
left of the tab is the row below the last one, and that one is a
split.

1. A tab in the last column of the last row scrolls the screen in
   kitty. ptterm keeps the cursor where it is, and libvterm and
   WezTerm keep it there too.
2. A backspace in the first column steps back to the end of the row
   above in kitty. xterm does that only with mode 45 set.
3. A count of zero for SU or SD means no scroll in kitty. Every other
   sequence that counts reads a zero as one, on both sides.
4. The line that a scroll brings in keeps the default style in kitty.
   xterm paints it with the background that is set.
5. A sequence that carries more parameters than its command takes is
   dropped whole by kitty. xterm reads the ones it needs and ignores
   the rest.
6. "?1047l" clears the alternate screen before it switches back. xterm
   documents that and libvterm does it; kitty keeps the content. (The
   three do not line up here: libvterm clears whenever it leaves,
   whatever the mode, and ptterm and kitty keep the screen that
   "?1049l" and "?47l" leave.)

## Where kitty looks wrong

kitty puts the second character after a wrap into the cell of the
first, when that character is not ASCII and the cursor sits below the
scrolling region. Every case around it draws two cells on both sides.
The oracle takes the second character out of the cell, because a reader
sees two cells either way, and `test_known_deviations` holds the case.

## Where libvterm cannot answer

libvterm is the second opinion, not a second authority. It holds less
than kitty does, and a comparison that asks for more reads a limit of
the reference as a difference. `test_against_vterm.py` writes each of
these down.

- It reads "?1047" and "?1049" and not "?47", so it draws the
  alternate screen of the oldest name on the first screen.
- It knows three shapes of underline: single, double and curly. A
  dotted and a dashed line both come out single, so the comparison
  reads those two as single on every side.
- It carries no colour for the line itself ("SGR 58"), so the
  comparison drops the colour before it looks.
- It reads a colour of its own as "38:2:r:g:b" only. ISO 8613-6 writes
  "38:2:<colour space>:r:g:b", with the colour space empty, and
  libvterm takes that empty part for the red. kitty reads both forms
  and ptterm follows kitty.

## Not compared yet

- A hyperlink (OSC 8) belongs to a cell. ptterm carries one now, in
  the style of the cell, but the comparison cannot see it: kitty holds
  an identifier that names the link and not the target itself.
  `test_hyperlinks.py` covers it against the screen instead.
- Sixel and the graphics protocol of kitty. Both draw pixels, which
  asks for a comparison of images and not of cells.

## Open, found by the hunt and not fixed

- An erased cell holds a space in ptterm and nothing in kitty, so a
  combining mark that lands on one hangs on the space here and goes
  away there. libvterm gives a third answer: it hangs the mark on the
  character that the erase was meant to take away. Three emulators,
  three answers, so there is nothing to follow. The hunt leaves the
  marks out; `test_combining_marks` covers them by hand.

Run it again to find more. Each one needs a decision about whether to
follow kitty or xterm before it becomes a fix.
