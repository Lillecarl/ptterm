# Deviations from the panel

Six emulators judge ptterm, and ptterm is not one of them. Each is
written by other people, and each comes from a different line:

- kitty, in C, through the python extension that kitty ships.
- WezTerm and Alacritty, in Rust, through `tests/judges`.
- libvterm, in C, the one that Vim and Neovim carry.
- Ghostty, in Zig, through libghostty-vt and `tests/judges-c`.
- xterm.js, in TypeScript, the one VS Code draws in, through
  `tests/judges-js`.

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
- `tests/judges` builds the two written in Rust, `tests/judges-c` the
  one that reads libghostty-vt, and `tests/judges-js` the one that
  reads xterm.js. Each is a program that answers one line of JSON with
  another; `tests/line_judge.py` is the side that asks.
- `tests/fuzz_against_kitty.py` builds random programs with hypothesis.
  `nix build --file . checks.ptterm-fuzz` runs it from the pyterm checkout
  and `nix build --file . checks.fuzz` from this one. `PTTERM_FUZZ` says how
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

**The user has decided seven of these nine, and ptterm keeps what it
does in each.** Do not reopen one of those without a new reason. The
tally is what the decision rested on, so it stands beside each entry.

**The standing rule, when a tally leaves ptterm alone against the
rest:** follow the rest. That settles it, and no one has to be asked. A
tally where ptterm sits with one or more judges is not that case, and
it goes to the user.

**Two new judges changed the picture, and they changed it our way.**
Ghostty and xterm.js joined a panel of four. Three differences that
split it two against two are now four against two for the side ptterm
is on: the tab on the last row, `?1047l`, and DECALN. Nothing that was
decided has to be decided again.

They also found one. What looked like a quirk of Alacritty, in CBT and
CHT, is a real difference: Ghostty and xterm.js take that side too, and
the panel is three against three. It is number 9, and it is open.

| # | What | With ptterm | Against ptterm |
| --- | --- | --- | --- |
| 1 | A tab in the last column of the last row | Ghostty, libvterm, WezTerm, xterm.js | Alacritty, kitty |
| 2 | `?1047l` clears the alternate screen | Ghostty, libvterm, WezTerm, xterm.js | Alacritty, kitty |
| 3 | A sequence with too many parameters | Alacritty, libvterm, xterm.js | Ghostty, kitty, WezTerm |
| 4 | DECALN homes the cursor and clears the margins | Ghostty, kitty, WezTerm, xterm.js | Alacritty, libvterm |
| 5 | A backspace in the first column | every other judge | kitty |
| 6 | A count of zero for SU or SD | Alacritty, libvterm, WezTerm, xterm.js | Ghostty, kitty |
| 7 | The background of the line a scroll brings in | Alacritty, libvterm, WezTerm, xterm.js | Ghostty, kitty |
| 8 | A combining mark on a cell an erase left | kitty, WezTerm, xterm.js | Alacritty, Ghostty, libvterm |
| 9 | CBT and CHT over the tab stops | kitty, libvterm, WezTerm | Alacritty, Ghostty, xterm.js |

### 1. A tab in the last column of the last row

`\x1b[8;20H12345\t` on 8 lines and 24 columns.

ptterm keeps the cursor where it is, and so do Ghostty, libvterm,
WezTerm and xterm.js. kitty and Alacritty scroll the screen up.

A tab draws nothing. A character in the last column leaves the cursor
waiting to wrap, and a tab leaves that wait alone, so no character has
arrived to need a new line. The right margin case, one column earlier,
is not a deviation any more: the whole panel puts the character after
the tab on the next line, and ptterm does too.

**As a setting:** a branch in `tab()`, for a cursor that waits to wrap
on the last row. Cheap to add if a program ever needs it.

### 2. "?1047l" clears the alternate screen

`\x1b[?1047h X \x1b[?1047l \x1b[?47h` on 3 lines and 6 columns.

ptterm clears the alternate screen before it gives it back, and so do
Ghostty, libvterm, WezTerm and xterm.js. kitty and Alacritty keep the
content.

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

ptterm reads the parameters the command takes and ignores the rest, and
so do Alacritty, libvterm and xterm.js. kitty, WezTerm and Ghostty drop
the sequence whole. Three against three.

xterm reads the ones it needs. Dropping the sequence loses a move that
the program meant. pyte raised a TypeError here and took the whole
stream with it, so the forgiving side is also the safe one.

**As a setting:** possible, at the one place that counts the
parameters. Little value: no program sends these on purpose.

### 4. DECALN homes the cursor and clears the margins

`ab\x1b#8X` on 4 lines and 6 columns.

ptterm draws the pattern, puts the margins back to the whole screen and
sends the cursor home, and so do Ghostty, kitty, WezTerm and xterm.js.
Alacritty and libvterm draw the pattern and leave the cursor where it
was.

The DEC manuals say all three, and kitty and WezTerm do all three.

**As a setting:** no. DECALN is an alignment test for a real tube.
Nothing in daily use sends it.

### 5. A backspace in the first column

`\n\x080` on 4 lines and 8 columns.

ptterm keeps the cursor in the first column, and so does every other
judge. kitty alone steps back to the end of the row above.

xterm does that only with reverse wraparound, `DECSET 45`, and that
mode is off by default.

**As a setting:** this one already has a name, and it is not ours.
ptterm does not read mode 45 today. The honest way to make it
configurable is to implement that mode, so a program turns it on the
way it does in xterm.

### 6. A count of zero for SU or SD

`a\r\nb\x1b[0S` on 4 lines and 8 columns.

ptterm reads a count of zero as one, and so do Alacritty, libvterm,
WezTerm and xterm.js. kitty and Ghostty read it as no scroll.

Every other sequence that counts reads a zero as one, on both sides.
`test_known_deviations.py` checks twelve of them.

**As a setting:** no. It would make SU and SD the only sequences that
count differently from the rest.

### 7. The background of the line a scroll brings in

`\x1b[42m\x1b[1S` on 4 lines and 6 columns.

ptterm paints the new line with the background that is set, and so do
Alacritty, libvterm, WezTerm and xterm.js. kitty and Ghostty give it
the default.

xterm paints it, and the terminfo entry of ptterm claims `bce`. A
capability that is claimed has to hold.

**As a setting:** no, not on its own. It would have to move with the
`bce` claim in the terminfo entry, because a program reads that and
draws what it says.

### 8. A combining mark on a cell that an erase left

`0\x1b[40m\x1b[1K\u0301` on 3 lines and 6 columns.

The erase takes the "0" away. A combining mark then arrives with no
character to hang on.

ptterm drops it, and kitty, WezTerm and xterm.js drop it too. Alacritty
and Ghostty hang it on the blank that the erase left. libvterm puts the
"0" back and hangs the mark on that.

Three against three. ptterm used to hang the mark on the blank, but
only when a background was set, which is the bug in the list above.
Whichever side it takes, it has to take the same one both times.

**As a setting:** no. Not while the panel is this evenly divided and
nothing turns on it.

### 9. CBT and CHT over the tab stops

`\x1b[Ix\x1b[2Iy\x1b[Zz` on 8 lines and 24 columns.

"CSI Ps I" moves forward over tab stops and "CSI Ps Z" moves back, and
neither draws anything. Alacritty, Ghostty and xterm.js land somewhere
else than ptterm, kitty, libvterm and WezTerm.

**This is the one the new judges found.** It read as a quirk of
Alacritty while the panel was four, and it sat in the list of judges
standing apart. Two more judges took that side, so it is a difference
that stands. Nobody has ruled on it.

**As a setting:** too early. Work out which reading is right first.
ncurses uses CHT to reach a column without drawing the blanks in
between, so a program does depend on this.

### 10. Left and right margins

`a\r\nb\r\nc\r\nd\x1b[?69h\x1b[2;4s\x1b[2S` on 8 lines and 24 columns,
and six more programs in `test_the_judges_that_carry_margins_agree`.

DECSLRM ("CSI Pl ; Pr s") names a left and a right margin, and private
mode 69 (DECLRMM) says whether it may. Ghostty, libvterm and WezTerm
carry them. Alacritty, kitty and xterm.js drop DECSLRM and draw the
whole width, so they differ from ptterm on every program that sets a
margin.

**This is a missing feature and not a decision.** The three that carry
margins draw what ptterm draws, cell for cell, on scrolling, on
inserting and deleting lines and characters, and on a line feed at the
bottom margin. xterm carries them as well, and esctest2 tests them
heavily: 73 of its tests set a margin.

**As a setting:** no. A program asks for the margins, and a program
that does not ask never sees them.

### 11. DECIC, DECDC, DECBI and DECFI

`abcdefg\r\nABCDEFG\x1b[1;2H\x1b['}` and `x\x1b[1;1H\x1b6` on 4 lines
and 24 columns.

DECIC ("CSI Pn ' }") and DECDC ("CSI Pn ' ~") insert and delete columns
of the scrolling region. DECBI ("ESC 6") and DECFI ("ESC 9") move the
cursor one column, and move the region when the cursor stands on a
margin.

Only libvterm and xterm.js carry DECIC and DECDC. **No judge carries
DECBI or DECFI.** xterm carries all four, and esctest2 holds twenty
tests for them, which ptterm passes.

**This is the widest gap between ptterm and the panel.** ptterm stands
alone on DECBI and DECFI, six to nothing. It stands there because the
side it is on is xterm and DEC STD 070, and because every judge that
differs differs by doing nothing at all. A program that sends "ESC 6"
means the column move, and a terminal that drops it draws the wrong
screen quietly.

**As a setting:** no, for the same reason as the margins.

### 12. DECFRA, DECERA, DECSERA and DECCRA

`abcdefg\r\nABCDEFG\r\nhijklmn\r\nHIJKLMN\r\nopqrstu\x1b[37;2;2;4;4$x`
and the three commands beside it, on 6 lines and 8 columns.

The four commands take a rectangle of the screen. DECFRA
("CSI Pch ; Pt ; Pl ; Pb ; Pr $ x") fills one with a character. DECERA
("$ z") erases one. DECSERA ("$ {") erases one and leaves a cell that
DECSCA marked alone. DECCRA ("$ v") copies one to another place.

**No judge carries any of the four.** All six leave the screen exactly
as it was, in every one of fifteen probes. So the panel gives no tally
here, and it cannot give one: a judge that does nothing reads the same
way as a judge that disagrees, and six abstentions are not six votes.

xterm is the anchor instead. esctest2 is xterm's own suite, and its
`DECFRATests`, `DECERATests`, `DECSERATests` and `DECCRATests` hold
thirty-two tests between them, of which twenty-four failed before this
work. The other eight ask a command to do nothing, which a terminal
without the command does very well. `test_rectangles.py` follows the
suite, and
`test_the_panel.py` writes down the abstention so that a judge which
grows the feature makes a test fail.

One rule inside the four is worth naming, because it looks like an
inconsistency and is not. **DECSERA reads only the mark of DECSCA.**
The mark of ISO 6429 does not hold it away from a cell, and DECSEL
("CSI ? Ps K") reads both marks. esctest2 asks for each of the two, in
`test_DECSERA_doesNotRespectISOProtect` and in the DECSEL tests, so
ptterm answers each of the two.

**As a setting:** no, for the same reason as the margins. A program
that sends "$ v" means the copy.

### 13. DECRQSS reports the height a pane has, not the one it was told

`\x1b[27t` then `\x1bP$qt\x1b\\` on a pane of any height.

"CSI Ps t" with a Ps of 24 or more is DECSLPP. It asks for a page of
that many lines, and xterm resizes its window to match. DECRQSS "t"
then reports the number the program wrote.

ptterm reports how tall the pane really is.

**Why.** A pane cannot resize itself. It sits in a layout beside other
panes, and making one taller makes another shorter, so ptterm hands
the ask to the embedder through `resize_func` and pymux decides. The
option `allow-program-resize` says whether a program gets its way, and
it is off, because a person arranged those panes on purpose.

Either way the report is the truth. With the option on, the pane
really did change height and the number matches. With it off, the
number a program wrote was never true of anything. A program reads
this to learn how much room it has, and the height of the pane is that
answer.

The panel says nothing here: DECRQSS reports through a channel the
judges do not carry. `DECRQSSTests.test_DECRQSS_DECSLPP` of esctest2
asks for the number that was written, so it fails while the option is
off, and the failure list records it.

**As a setting:** it is one. `set-option allow-program-resize on`.

### 14. A reset of a dynamic colour gives white text, not black

`\x1b]10;#aabbcc\x1b\\` then `\x1b]110\x1b\\` then `\x1b]10;?\x1b\\`.

"OSC 110" puts the foreground back to the colour the terminal starts
with. xterm starts with black text on a white background, so it
answers black. ptterm answers white, because a pane draws on a dark
background.

**Why.** This is not a difference in the command. Both terminals put
the colour back to the one they began with; the two simply begin with
different colours. A pane reports what a program will really draw on,
and pymux paints a dark pane.

esctest2 makes the difference visible by accident. Before each test it
writes `OSC 10 ; #000` and `OSC 11 ; #ffffff`, to work around a bug
where "OSC 104" leaves the dynamic colours alone. Those two values are
the defaults of xterm, so on xterm the reset lands back on the value
the harness wrote and the test passes.
`ResetSpecialColorTests.test_ResetSpecialColor_Dynamic` therefore
fails here, and the failure list records it. The other four tests of
that class pass.

The panel says nothing here: a colour query travels through a channel
the judges do not carry.

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

### xterm.js

The buffer API of xterm.js says whether a cell carries an underline
and nothing more: not the shape of the line, and not its colour. The
judge reports a plain single line for any of them, and the comparison
drops the shape and the colour from both sides before it looks.

Everything else a cell of ours holds, xterm.js holds.

### Ghostty

Nothing. libghostty-vt holds every part of a cell that ptterm holds,
the shape of an underline and the colour of the line included, so its
answers pass through no projection.

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
