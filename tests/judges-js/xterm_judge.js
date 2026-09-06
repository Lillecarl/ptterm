// Read a screen back from xterm.js, the terminal that VS Code carries.
//
// One process answers one request after another, the same way the
// judges written in Rust and in C do. A request is one line of JSON:
//
//     {"data": "...", "lines": 6, "columns": 20}
//
// The answer is one line holding the screen, as rows of cells:
//
//     {"xterm": [[[char, fg, bg, bold, italic, ul, rev, ulcol,
//                  link, link_name], ...]]}
//
// A colour is null, ["index", n] or ["rgb", r, g, b]. That is the
// shape every other judge speaks.
//
// The module of xterm.js arrives as the first argument, because
// nothing here installs packages: nix unpacks the one tarball and
// names the file.

const path = process.argv[2];
if (!path) {
  process.stderr.write("usage: xterm_judge.js <path to xterm-headless.js>\n");
  process.exit(2);
}
const { Terminal } = require(path);

// This judge reads what `IBufferCell` does not name. These are private
// paths of @xterm/headless 6.0.0, and a version bump has to probe them
// again:
//
//   terminal._core._oscLinkService   the pool of links
//   cell.extended.urlId              which link a cell belongs to, or 0
//   cell.getUnderlineStyle()         the shape of the line, 0 to 5
//   cell.getUnderlineColor()         the colour of the line
//   cell.isUnderlineColor*()         which kind of colour that is
//
// A judge that reports less than the emulator holds is not neutral. It
// abstains, and an abstention is a vote that nobody cast. xterm.js holds
// all of these, so the judge reads them.

// A colour, in the form that the other judges write.
function color(isDefault, isRGB, value) {
  if (isDefault) return null;
  if (isRGB) return ["rgb", (value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
  return ["index", value];
}

function screenOf(terminal, lines, columns) {
  const buffer = terminal.buffer.active;
  const links = terminal._core._oscLinkService;
  const rows = [];

  for (let y = 0; y < lines; y++) {
    const line = buffer.getLine(buffer.baseY + y);
    const cells = [];
    for (let x = 0; x < columns; x++) {
      if (!line) {
        cells.push([" ", null, null, false, false, 0, false, null, null, null]);
        continue;
      }
      const cell = line.getCell(x);
      if (!cell) {
        cells.push([" ", null, null, false, false, 0, false, null, null, null]);
        continue;
      }

      // The second half of a wide character holds no character of its
      // own: xterm.js gives it a width of zero. Every judge reports a
      // space there.
      const text = cell.getWidth() === 0 ? " " : cell.getChars() || " ";

      // Which link this cell belongs to, and where that link goes.
      // `urlId` is the name xterm.js gives one link, out of a pool it
      // keeps for the screen, so it says which cells are one link. It is
      // 0 on a cell that carries none.
      const urlId = (cell.extended && cell.extended.urlId) || 0;
      const link = urlId ? links.getLinkData(urlId) : null;

      // Whether an "SGR 58" ever set a colour for the line. The raw
      // field is the only thing that says so. `isUnderlineColorDefault`
      // does not: it answers false on a cell that carries a foreground
      // and no "SGR 58" at all, and `getUnderlineColor` then hands back
      // that foreground. A red letter with a plain line would read as a
      // red line, on every cell of every coloured program.
      //
      // Zero is not a colour a program can ask for. The two bits above
      // the value say which kind of colour it is, and both forms set
      // one, so the field is zero only when nothing wrote it.
      const hasUnderlineColor =
        ((cell.extended && cell.extended.underlineColor) || 0) !== 0;

      // `isFgDefault` and `isFgRGB` answer with a boolean; `isBold`
      // and the other attributes answer with a number.
      cells.push([
        text,
        color(cell.isFgDefault(), cell.isFgRGB(), cell.getFgColor()),
        color(cell.isBgDefault(), cell.isBgRGB(), cell.getBgColor()),
        cell.isBold() !== 0,
        cell.isItalic() !== 0,
        // The shape of the line: 0 none, 1 single, 2 double, 3 curly,
        // 4 dotted, 5 dashed. That is how kitty numbers them and how
        // libghostty-vt numbers `GHOSTTY_SGR_UNDERLINE_*`, so the number
        // compares as it is.
        //
        // A cell of a link reads as 5 whatever the program asked for.
        // `_as_xterm_sees` drops the line of a linked cell for that
        // reason; the judge reports what xterm.js holds.
        cell.getUnderlineStyle(),
        cell.isInverse() !== 0,
        // The colour of the line itself, once the raw field says a
        // program asked for one.
        hasUnderlineColor
          ? color(false, cell.isUnderlineColorRGB(), cell.getUnderlineColor())
          : null,
        // The target of an "OSC 8", and what xterm.js calls that one
        // link. The name is the number out of the pool, as a string,
        // because `number_the_links` wants a name and not an index.
        link ? link.uri : null,
        urlId ? String(urlId) : null,
      ]);
    }
    rows.push(cells);
  }
  return rows;
}

function answer(line, done) {
  let request;
  try {
    request = JSON.parse(line);
  } catch (error) {
    done(JSON.stringify({ xterm: [] }));
    return;
  }

  const lines = request.lines || 6;
  const columns = request.columns || 20;
  const terminal = new Terminal({
    cols: columns,
    rows: lines,
    scrollback: 0,
    allowProposedApi: true,
  });

  // The write is asynchronous: the buffer is only settled once the
  // callback runs, so reading it earlier reads the screen before.
  terminal.write(request.data || "", () => {
    const rows = screenOf(terminal, lines, columns);
    terminal.dispose();
    done(JSON.stringify({ xterm: rows }));
  });
}

// One request at a time, in order. A second write while the first is
// still settling would answer out of order.
const pending = [];
let busy = false;

function pump() {
  if (busy || pending.length === 0) return;
  busy = true;
  const line = pending.shift();
  answer(line, (text) => {
    process.stdout.write(text + "\n");
    busy = false;
    pump();
  });
}

let buffered = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffered += chunk;
  let at;
  while ((at = buffered.indexOf("\n")) >= 0) {
    const line = buffered.slice(0, at);
    buffered = buffered.slice(at + 1);
    if (line.trim()) pending.push(line);
  }
  pump();
});
process.stdin.on("end", () => {
  if (buffered.trim()) pending.push(buffered);
  pump();
});
