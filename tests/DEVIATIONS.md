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
- `tests/drive_with_esctest.py` runs esctest2, the conformance suite of
  xterm, on a pty that ptterm owns. It judges from the inside, which
  the panel cannot: it writes sequences and reads the reports that come
  back. `tests/esctest-failures.txt` holds what fails, and the section
  at the end of this file says what each one is.
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
- The other 240 colours of the palette had the same fault, and Alacritty's
  reference tests found it. A number above fifteen became the colour that
  xterm paints, so the theme of the user reached only sixteen cells out of
  256. Every judge of the panel keeps the number.
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

Every way of bringing a line in paints it: SU, a linefeed at the
bottom of the screen, and a linefeed or IND at the bottom of a
scrolling region. A linefeed with no region painted nothing until
Alacritty's `vim_large_window_scroll` reference test found it, so the
same linefeed painted or did not paint by whether a program had set a
region. `tests/test_scroll_background.py` holds all four.

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

### 15. A pane has no window to move or iconify

`\x1b[3;10;20t` then `\x1b[13t`, and `\x1b[2t` then `\x1b[11t`.

"CSI 3 t" moves the window, "CSI 2 t" iconifies it, and "CSI 13 t" and
"CSI 11 t" report where it is and whether it is iconified. xterm has a
window and does all four. ptterm ignores the two that act and answers
nothing for the two that ask.

**Why.** A pane is not a window. It has no place on a screen to be
moved to, and nothing to be iconified into. There is no honest number
to report, and an invented one is worse than none: a program that
reads a position will draw at it.

The related question does have an honest answer, and ptterm gives it.
"CSI 19 t" asks how much room there is. For a window that is the
display it stands on; for a pane it is the pane, because a pane draws
where the embedder puts it and cannot take more. So the room it has is
the room it already fills, and "CSI 19 t" answers its own size. That
is what makes a maximize or a fullscreen ask come out right: the pane
is already as large as it can be.

`XtermWinopsTests.test_XtermWinops_MoveToXY`,
`test_XtermWinops_MoveToXY_Defaults` and
`test_XtermWinops_IconifyDeiconfiy` of esctest2 ask for the window, so
they fail, and the failure list records them. The other fifteen of
that class pass.

**A note on what a query costs.** Answering nothing is right here, and
it is not free: a program that asks and waits hears nothing back. The
two that ask are rare, and neither xterm nor a multiplexer can promise
an answer to them, so a program that sends one already has to cope
with silence. Where a pane can answer at all, it answers; see
`DEVIATIONS.md` entry 13 and the device status reports.

### 16. A pane cannot take a 132 column page on its own

`\x1b[?40h\x1b[?3h`, then `\x1b[18t`.

DECCOLM ("?3") picks the 80 or the 132 column page, and private mode 40
says whether it may. ptterm carries both: the mode is off until a
program sets it, and DECCOLM then asks for the width through
`resize_func`, the same route that DECSLPP and the window resizes use.

**Why it asks instead of taking.** A pane is not a window. Its width
comes from the layout, and pymux answers a program that asks for room
by moving the weights of the panes around, and only when the person
allowed it with `set-option allow-program-resize on`.

ptterm used to resize its own screen for DECCOLM. That does not hold:
`TerminalControl.create_content` calls `set_size` on every draw with
the width the layout gives, so the 132 lasts until the next frame. A
program that read 132 and laid its output out for it would then draw
off the edge of an 80 column pane. A width that is right for one frame
is worse than a width that never moved.

So a pane reaches 132 columns only when the window has 132 columns to
give. esctest2 runs in a window of 80, so three of its tests fail and
the failure list records them:

- `DECSETTests.test_DECSET_Allow80To132`
- `DECSETTests.test_DECSET_DECCOLM`
- `RISTests.test_RIS_ResetDECCOLM`

The first two passed while ptterm resized its own screen, because each
asks for the width straight after setting it and the answer arrives
before the next draw. That is the whole of what they proved.

`tests/test_page_width.py` covers the same steps by reading the ask
rather than the width.

**DECNCSM.** A fourth test fails for the other reason: ptterm carries
more than xterm here, not less.

DECNCSM ("?95") tells DECCOLM to keep the page instead of clearing it.
ptterm carries it, from conformance level 5 up, because the VT510
brought it. xterm keeps it behind the `allowWindowOps` resource, and
the suite is told that resource is off, so it expects a terminal to
refuse the mode. `DECRQMTests.test_DECRQM_DEC_DECNCSM` therefore
fails: ptterm answers that the mode is set, and the suite wanted no
answer at all.

Turning the resource on in the driver costs more than it gives. Five
other tests then expect a pass that a pane cannot give, so the list
grows by four. The one honest entry is cheaper.

A pane has its own version of that resource, `allow-program-resize`,
and ptterm cannot see it: the screen only holds `resize_func` and
learns nothing about what the embedder will allow. See
Lillecarl/pymux#31.

**As a setting:** it already is one. `allow-program-resize` decides,
and it decides for every sequence that asks for room, not for DECCOLM
alone.

**A terminal that owns its pty takes the page, and a fault came out
from behind it.** `checks.ptterm-esctest` gives ptterm a pty of its own
and answers the ask, so DECCOLM really changes the width there. RIS
then left the page at 132 columns, which nothing could see while the
width never moved. Fixed; `tests/test_page_width.py` holds it, and
Lillecarl/pymux#42 says what it was.

**The mode starts off, and one esctest2 test assumes it starts on.**
`DECSETTests.test_DECSET_DECNCSM` never sets mode 40. So DECCOLM does
nothing, the page keeps what was written on it, and the test reads a
character where it wants a blank. xterm passes it because its
`allowC132` resource turns mode 40 on by default; ptterm follows the
mode and not the resource. `test_DECSET_Allow80To132`, which sets the
mode itself, passes here, and so does `test_DECSET_DECCOLM`. So the
three tests together say the behaviour is consistent and the default
is the only difference.

**As a setting, again:** a resource that turns mode 40 on at startup
would make that test pass and change nothing else. Nobody has asked
for one.

### 17. Where the cursor stands after the alternate screen is taken

`\x1b[2;3H\x1b[?47hX` and the same with `?1047` and `?1049`, on 3 lines
and 6 columns.

For `?47` and `?1047`, ptterm leaves the cursor where it stands, and so
do Alacritty, Ghostty, libvterm, WezTerm and xterm.js. kitty alone puts
it home. `DECSETTests.test_DECSET_ALTBUF` and
`test_DECSET_OPT_ALTBUF` of esctest2 ask for the same thing, so xterm
is with the five.

For `?1049`, ptterm puts the cursor home, and so do kitty and WezTerm.
Alacritty, Ghostty, libvterm and xterm.js leave it, and xterm describes
the mode as a save, a switch and a clear, with no move. Nothing in
esctest2 asks, so nothing forces the reading.

The panel is four to two against ptterm here, so this is a choice
ptterm has made and not an answer it has: the argument is that `?1049`
saves the cursor on the way in and gives it back on the way out, so a
program that uses the pair never has to know where the cursor stood in
between. That argument does not cover a program that takes the screen
and then reads the cursor. Lillecarl/pymux#34 holds the question.

**As a setting:** the same argument as entry 2. A pane holds one
cursor, so the choice belongs to the pane and is made once.

### 18. A pane names fewer extensions than xterm in its DA answer

`\x1b[c`, and the answer that comes back.

xterm at level 5 names thirteen: `65;1;2;6;9;15;16;17;18;21;22;28;29`.
A pane names ten: `65;1;4;6;9;15;17;21;22;28`.

Four of xterm's are missing, and a pane has none of them:

- **2**, the printer port. There is no printer, and DECPFF and DECPEX
  are kept and not acted on.
- **16**, the locator device port. It reports the mouse the way ReGIS
  does, and a pane reports the mouse the way xterm does.
- **18**, user windows. A pane is one window and cannot make another.
  Entry 15 says the same about moving one.
- **29**, the ANSI text locator. The other half of 16.

One is there that xterm does not name: **4**, sixel. A pane draws sixel
images, so it says so.

**Why.** A capability claimed and not served is worse than one that is
missing. A program reads the list to decide what to send, and a claim
it acts on and gets nothing for leaves it waiting. The list is the one
place a program asks before it commits.

`DATests.test_DA_NoParameter` and `test_DA_0` of esctest2 check for all
thirteen, so they fail, and the failure list records them. The rest of
that class passes.

**As a setting:** no. The list has to say what the pane really does,
and a person cannot make a pane grow a printer.

### 19. A pane writes the clipboard and does not read it

`\x1b]52;;?\x1b\\`, and the answer that never comes.

"OSC 52" carries the clipboard of the user. A program can set it and a
program can ask for it, and ptterm serves the two differently: a set
goes out through `osc_func` to whoever embeds the pane, and a query is
dropped where it arrives. `_forward_osc` in `ptterm/screen.py` is the
line, and `tests/test_osc_forward.py` holds both halves.

**Why.** The clipboard holds what the person copied somewhere else: a
password, an address, a paragraph of a document they were reading. A
program in a pane has no claim on that, and a program that asks is
asking to read something nobody gave it. Setting the clipboard needs no
such trust, so it is handed on.

The cost is a program that copies with "OSC 52" and reads back to check
that it worked. It does not get an answer. That is a small price beside
the alternative.

**A host that keeps a clipboard does not change this.** The query is
dropped before `osc_func` sees it, so nothing an embedder does can
answer one. Lillecarl/pymux#45 asked for such a host and is closed for
that reason.

`ManipulateSelectionDataTests.test_ManipulateSelectionData_default` of
esctest2 sets the clipboard and reads it back, so it waits for the
report timeout and fails. That is the one test it costs.

**As a setting:** it could be. A person who wants a pane to read the
clipboard could say so, the way `allow-program-resize` lets a program
take room. Nobody has asked, and the default stays no either way.

## Where kitty looks wrong

kitty puts the second character after a wrap into the cell of the
first, when that character is not ASCII and the cursor sits below the
scrolling region. Every case around it draws two cells on both sides.
The oracle takes the second character out of the cell, because a reader
sees two cells either way, and `test_known_deviations` holds the case.

## Where Alacritty looks wrong

Alacritty reads "SGR 21" as the end of bold. Five judges read it as a
double underline, which is what ECMA-48 numbers it: kitty, WezTerm,
libvterm, Ghostty and xterm.js all keep the bold and draw the line.
`test_the_panel.py::test_what_sgr_21_means` holds the tally.

This is the whole of the `underline` difference that
`checks.pymux-alacritty` reports. That reference test writes
`CSI 4:3 ; 21 m` and records a curl, so ten cells differ. ptterm keeps
all five shapes of a line, and a bare `CSI 4:3 m` reaches the wire as
`SGR 4:3`.

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

## Every esctest2 failure that stands, and where it is written down

**The suite runs twice, and the difference is the point.**
`checks.ptterm-esctest` runs it on a pty that ptterm owns, so what it
judges is the emulator alone. `checks.pymux-esctest` runs it in a pane,
so what it judges is the emulator and everything pymux puts around it.
What fails in both belongs to ptterm; what fails only in a pane is the
pane.

Three tests run in neither. `NOT_OURS` in each driver holds them:
`test_XtermWinops_IconifyDeiconfiy`, `test_XtermWinops_MoveToXY` and
`test_XtermWinops_MoveToXY_Defaults` ask where the window is and
whether it is iconified. Neither a widget nor a pane has one, and no
decision follows from the answer, so the question does not apply. A
pattern there that matches no test fails the check, and so does a name
that is left out and recorded as a failure as well.

### On a pty of its own: five

`ptterm/tests/esctest-failures.txt` holds the names, and every one of
them is an entry above. None is an unfixed fault.

| Test | Entry |
| --- | --- |
| `DATests.test_DA_0` | 18 |
| `DATests.test_DA_NoParameter` | 18 |
| `DECSETTests.test_DECSET_DECNCSM` | 16 |
| `ManipulateSelectionDataTests.test_ManipulateSelectionData_default` | 19 |
| `ResetSpecialColorTests.test_ResetSpecialColor_Dynamic` | 14 |

**The check paid for itself twice on the first run.** It answers a
resize, which no pane can, so it reached two faults that a pane hid.
RIS left the page at 132 columns (Lillecarl/pymux#42). And it claims
the window operations of xterm, so the suite ran the title tests it was
skipping and found that xterm's four title modes were not there at all
(Lillecarl/pymux#44). Both are fixed, and `test_page_width.py` and
`test_title_modes.py` hold them.

### In a pane: nine

`pymux/tests/esctest-failures.txt` holds the names. The eight above
are not all here, because the pane never reaches four of them.

| Test | Entry |
| --- | --- |
| `DATests.test_DA_0` | 18 |
| `DATests.test_DA_NoParameter` | 18 |
| `DECRQMTests.test_DECRQM_DEC_DECNCSM` | 16 |
| `DECRQSSTests.test_DECRQSS_DECSLPP` | 13 |
| `DECSETTests.test_DECSET_Allow80To132` | 16 |
| `DECSETTests.test_DECSET_DECCOLM` | 16 |
| `RISTests.test_RIS_ResetDECCOLM` | 16 |
| `ResetSpecialColorTests.test_ResetSpecialColor_Dynamic` | 14 |
| `XtermWinopsTests.test_XtermWinops_DECSLPP` | 13 |

Eight of the nine are the same sentence: **a pane is not a window.** It
has no printer, no locator, no window to move, and its width and height
come from the layout and not from the program inside it.

**The resize tests cannot pass in a pane, whatever the option says.**
Entry 13 names `allow-program-resize`, and turning it on changes
nothing here: `Pymux.resize_pane_for_program` calls
`Window.change_size_for_pane`, which moves room between panes. The
suite runs in a window that holds one pane, so there is no sibling to
take the room from and none to give it. A wider window does not help
either: the suite asks for 80 columns in its own reset, and a lone pane
cannot be made narrower than the window it fills.

`ResetSpecialColorTests.test_ResetSpecialColor_Dynamic` is the one
that is not about the window. Entry 14 has it: the suite writes
xterm's own default foreground before it asks, and a pane starts from
a different one.

## Every libvterm assertion that stands, and what it is

`checks.ptterm-vterm` runs libvterm's own 43 test files through
libvterm's own runner, with `tests/vterm_harness.py` as the program it
drives. `NOT_OURS` in `tests/drive_with_vterm.py` leaves out 27 of the
files, each with the reason: libvterm reports every glyph it lays down
and which rectangle it redrew, and ptterm has neither.

The 16 that run hold 270 assertions, and four of those sit inside a
`$SEQ` and are asked more than once. 15 answers differ. They are in
`tests/vterm-failures.txt`, and each one is one of four things.

**ptterm does not hold it at all, and holding it is a decision.**

| Assertions | What | Issue |
| --- | --- | --- |
| `30state_pen` 68, 70 | SGR 10 to 19, the alternate fonts | Lillecarl/pymux#60 |
| `30state_pen` 118 to 122 | SGR 73 to 75, superscript and subscript | Lillecarl/pymux#59 |

**The suite is describing a limit of libvterm, and the panel says so.**

`61screen_unicode` 35 and 41 want a cell to hold a base character and
five combining marks and no more. `VTERM_MAX_CHARS_PER_CELL` is a fixed
array in a C struct, and nobody else has one: kitty, Alacritty, WezTerm
and xterm.js all keep every mark, and so does ptterm. Four to one, with
Ghostty abstaining because our reader for it drops the marks
(Lillecarl/pymux#63). `test_the_panel.py` holds that tally.

**The suite runs libvterm without a scrollback, and ptterm always has
one.**

`69screen_reflow` 74 to 79 make a five row screen hold seven rows of
text, so two rows scroll away. They then widen it to sixteen columns,
where the text needs one row less. libvterm expects the text at rows 0
to 3 and a blank row 4, with the cursor on row 3. ptterm pulls one of
the two rows back and answers row 4, with the cursor on row 4.

libvterm does what ptterm does when it has a history to read. Its
`src/screen.c` lays the new screen out from the bottom upwards, and
lines 676 to 718 then call `sb_popline` for every row still spare at the
top. Only when that call gives nothing do lines 719 to 732 move the text
up to row 0 and blank the bottom.

The test file asks for `WANTSCREEN r`, which turns reflow on and leaves
the scrollback off, and `t/harness.c` line 589 returns 0 from
`sb_popline` while it is off. So the expected rows are the fallback.
Give the same harness `WANTSCREEN rb` and the same bytes, and it pops a
line, backfills row 0, and reports the cursor at `4,2`, which is
ptterm's answer.

**The panel cannot rule here.** A judge takes bytes and one size, and no
judge on it can be resized, so a reflow has no vote to read. libvterm's
own source, run with its scrollback on, is the only oracle
(Lillecarl/pymux#64). `test_reflow_history.py` holds the case.

One difference is ptterm's to keep. libvterm copies a popped line cell
for cell (`src/screen.c` line 684) and does not rewrap it, so an
embedder with a history sees `S HERE` on row 0 and not the whole prompt.
ptterm unwraps the history and wraps it again at the new width, which is
what kitty and WezTerm do.

**The suite is describing its own rendering decision, and ptterm keeps
the parts apart on purpose.**

`30state_pen` 111 and 114 want `\e[1;37m` to report `idx(15)`, colour
fifteen. ptterm reports `idx(7)` with bold set, which is what the
program asked for. libvterm's own harness turns the fold on with
`vterm_state_set_bold_highbright`, so the number the suite expects is
what libvterm's embedder chose to draw and not what the program wrote.

ptterm keeps the bold and the colour apart so that the renderer can
decide, and a terminal that draws bold plus colour seven as bright will
still do so. Whether the server should carry enough to make that call
per client is Lillecarl/pymux#53.

**Five faults the suite found are already fixed.** The DEC line
attributes reached no handler, so `67screen_dbl_wh` failed five times.
`screen.py` holds one per line now, in `line_attributes`, next to
`wrapped_lines` and counted the same way. An erase, a scroll and a
reflow all carry it, and DECLRMM takes it off, because half a double
width line is not a thing a terminal can draw.

The line still holds every column it held. libvterm alone halves a
double width line, and kitty, WezTerm, Alacritty, Ghostty and xterm.js
all keep it whole. Five to one, and `test_the_panel.py` holds the vote.
ptterm draws nothing with the attribute: how wide a line looks is the
renderer's decision. Emitting it is Lillecarl/pymux#65.

DECALN filled the screen with a plain `Char`, which reads as a cell
nobody wrote, so eight assertions in `90vttest_01-movement-1` saw an
empty frame where the E's should be. ptterm `9e6b697b` builds them out
of `_CHAR_CACHE` like every other draw.

HPB and VPB (`CSI Ps j` and `CSI Ps k`) reached no handler, so the
cursor stayed where it was. `stream.py` names both now and gives them to
the handlers of CUB and CUU, which is the arithmetic libvterm uses.
Three of the six judges carry the pair and all three land in the same
place; the other three do not carry it at all.
`test_the_panel.py` holds that tally and `test_cursor_margins.py` holds
the bounds.

A reflow took the blanks off the end of every line by reading the
character, so it could not tell a space a program wrote from the blank
an erase leaves. The space after a shell prompt went away on every
resize. `_reflow` asks whether the cell is a `TerminalChar` now, which
is the same distinction the alignment screen needed.

An erase that cleared the end of a line left the continuation mark on
the line below it, so a resize joined two lines that nothing wrapped
between. `erase_in_line` takes the mark off now.
`test_continuation.py` holds it, and libvterm is the only oracle there
is: no judge on the panel reports the mark, and it shows from outside
only through a resize.

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

- Giving the alternate screen back under a name other than the one that
  took it, with the cursor waiting to wrap:
  `\x1b[?1049h\x1b[14G00000你你你\x1b[?47l0`. The verdict is a split.
  kitty, WezTerm, Ghostty and xterm.js agree with each other and differ
  from ptterm in two cells; Alacritty and libvterm differ in ten, for
  the reason entry 2 gives. Lillecarl/pymux#35 holds it.

Run it again to find more. Each one needs a decision about whether to
follow kitty or xterm before it becomes a fix.
