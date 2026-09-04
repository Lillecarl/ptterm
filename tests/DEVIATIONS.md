# Deviations from the panel

Four emulators judge ptterm, and ptterm is not one of them. Each is
written by other people, and each comes from a different line:

- kitty, in C, through the python extension that kitty ships.
- WezTerm and Alacritty, in Rust, through `tests/judges`.
- libvterm, in C, the one that Vim and Neovim carry.

**A tally says more than a comparison.** Where every judge differs from
ptterm and the judges agree with each other, ptterm is wrong and nobody
has to decide anything. Where the judges disagree, the difference is a
choice. `verdict()` in `tests/panel.py` answers "agree", "ptterm-wrong"
or "split".

**Nothing here is meant to live in anyone's head.** Every deviation
below names the program that shows it, the side each judge takes, the
reason ptterm does what it does, and whether it could become a setting.
A reader who has never seen this code should be able to reopen any one
of them without asking a person.

- `tests/test_the_panel.py` holds the tally of every deviation that
  stands, and the programs the whole panel agrees on.
- `tests/test_known_deviations.py` holds each deviation as a strict
  `xfail` against kitty. One that starts to pass means it is gone.
- `tests/test_against_kitty.py` and `tests/test_against_vterm.py` hold
  sequences by hand.
- `tests/test_corpus_against_kitty.py` and
  `tests/test_corpus_against_the_panel.py` replay what real programs
  wrote.
- `tests/fuzz_against_kitty.py` builds random programs with hypothesis.
  `nix-build -A checks.ptterm-fuzz` runs it from the pyterm checkout
  and `nix-build -A checks.fuzz` from this one. `PTTERM_FUZZ` says how
  many examples.

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
- A combining mark hung on a cell that an erase had blanked, but only
  when a background was set. An erase with no background drops the
  cell, so the mark had nothing to reach and went away; an erase with
  a background wrote a space, and the mark hung on that. One program
  gave two answers. A cell that an erase leaves now holds no
  character, whatever its background, so the mark goes away in both.
  kitty and WezTerm draw the same line.

## The deviations that stand

**The user has decided every one of these, and ptterm keeps what it
does in each.** Do not reopen one without a new reason. The tally is
what the decision rested on, so it stands beside each entry.

Four split the panel two against two. In the other three, kitty stands
alone against the other three judges and against xterm.

**The standing rule, when a tally is three to one:** follow the three.
If ptterm is the only one that deviates, that settles it, and no one
has to be asked. A tally where ptterm sits with one of the judges is
not that case, and it goes to the user.

| # | What | With ptterm | Against ptterm |
| --- | --- | --- | --- |
| 1 | A tab in the last column of the last row | libvterm, WezTerm | Alacritty, kitty |
| 2 | `?1047l` clears the alternate screen | libvterm, WezTerm | Alacritty, kitty |
| 3 | A sequence with too many parameters | Alacritty, libvterm | kitty, WezTerm |
| 4 | DECALN homes the cursor and clears the margins | kitty, WezTerm | Alacritty, libvterm |
| 5 | A backspace in the first column | Alacritty, libvterm, WezTerm | kitty |
| 6 | A count of zero for SU or SD | Alacritty, libvterm, WezTerm | kitty |
| 7 | The background of the line a scroll brings in | Alacritty, libvterm, WezTerm | kitty |

### 1. A tab in the last column of the last row

`\x1b[8;20H12345\t` on 8 lines and 24 columns.

ptterm keeps the cursor where it is. kitty and Alacritty scroll the
screen up.

A tab draws nothing. A character in the last column leaves the cursor
waiting to wrap, and a tab leaves that wait alone, so no character has
arrived to need a new line. The right margin case, one column earlier,
is not a deviation any more: the whole panel puts the character after
the tab on the next line, and ptterm does too.

**As a setting:** a branch in `tab()`, for a cursor that waits to wrap
on the last row. Cheap to add if a program ever needs it.

### 2. "?1047l" clears the alternate screen

`\x1b[?1047h X \x1b[?1047l \x1b[?47h` on 3 lines and 6 columns.

ptterm clears the alternate screen before it gives it back. kitty and
Alacritty keep the content.

xterm documents the clear for this mode. `?1049l` and `?47l` do not
clear, and ptterm keeps the screen for both of those, so a program that
wants its content back sends one of them. libvterm clears whenever it
leaves, whatever the mode.

**As a setting:** it cannot answer one way for one client and another
way for another. A pane holds one screen, and every attached client
draws the cells of that screen. The keyboard can translate per client
because it is a negotiation between a pane and a terminal; the content
of a screen is one buffer. So a setting belongs to the server or the
pane, and it decides once, where the program writes the mode.

### 3. A sequence with more parameters than its command takes

`\x1b[3;9;9GX` on 4 lines and 8 columns.

ptterm reads the parameters the command takes and ignores the rest.
kitty and WezTerm drop the sequence whole.

xterm reads the ones it needs. Dropping the sequence loses a move that
the program meant. pyte raised a TypeError here and took the whole
stream with it, so the forgiving side is also the safe one.

**As a setting:** possible, at the one place that counts the
parameters. Little value: no program sends these on purpose.

### 4. DECALN homes the cursor and clears the margins

`ab\x1b#8X` on 4 lines and 6 columns.

ptterm draws the pattern, puts the margins back to the whole screen and
sends the cursor home. Alacritty and libvterm draw the pattern and
leave the cursor where it was.

The DEC manuals say all three, and kitty and WezTerm do all three.

**As a setting:** no. DECALN is an alignment test for a real tube.
Nothing in daily use sends it.

### 5. A backspace in the first column

`\n\x080` on 4 lines and 8 columns.

ptterm keeps the cursor in the first column. kitty steps back to the
end of the row above.

xterm does that only with reverse wraparound, `DECSET 45`, and that
mode is off by default.

**As a setting:** this one already has a name, and it is not ours.
ptterm does not read mode 45 today. The honest way to make it
configurable is to implement that mode, so a program turns it on the
way it does in xterm.

### 6. A count of zero for SU or SD

`a\r\nb\x1b[0S` on 4 lines and 8 columns.

ptterm reads a count of zero as one. kitty reads it as no scroll.

Every other sequence that counts reads a zero as one, on both sides.
`test_known_deviations.py` checks twelve of them.

**As a setting:** no. It would make SU and SD the only sequences that
count differently from the rest.

### 7. The background of the line a scroll brings in

`\x1b[42m\x1b[1S` on 4 lines and 6 columns.

ptterm paints the new line with the background that is set. kitty gives
it the default.

xterm paints it, and the terminfo entry of ptterm claims `bce`. A
capability that is claimed has to hold.

**As a setting:** no, not on its own. It would have to move with the
`bce` claim in the terminfo entry, because a program reads that and
draws what it says.

## Where kitty looks wrong

kitty puts the second character after a wrap into the cell of the
first, when that character is not ASCII and the cursor sits below the
scrolling region. Every case around it draws two cells on both sides.
The oracle takes the second character out of the cell, because a reader
sees two cells either way, and `test_known_deviations` holds the case.

## Where a judge cannot answer

A judge that cannot hold something says nothing about it. A comparison
that asks for more reads a limit of the reference as a difference, so
`panel.py` runs each answer through a projection that drops what the
judge misses.

**Read the judge before you trust a tally.** The reader in
`tests/judges/src/main.rs` took the character of an Alacritty cell and
stopped there. Alacritty keeps a mark of no width beside the cell and
not in it, so every combining mark went missing, and Alacritty voted
"no mark" on every case that had one. That made one deviation look
like four judges to nothing when it was two against two. The reader
now takes the marks as well.

### libvterm

libvterm is the second opinion, not a second authority. It holds less
than kitty does. `test_against_vterm.py` writes each of these down.

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
