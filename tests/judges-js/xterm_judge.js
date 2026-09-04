// Read a screen back from xterm.js, the terminal that VS Code carries.
//
// One process answers one request after another, the same way the
// judges written in Rust and in C do. A request is one line of JSON:
//
//     {"data": "...", "lines": 6, "columns": 20}
//
// The answer is one line holding the screen, as rows of cells:
//
//     {"xterm": [[[char, fg, bg, bold, italic, ul, rev, ulcol], ...]]}
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

// A colour, in the form that the other judges write.
function color(isDefault, isRGB, value) {
  if (isDefault) return null;
  if (isRGB) return ["rgb", (value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
  return ["index", value];
}

function screenOf(terminal, lines, columns) {
  const buffer = terminal.buffer.active;
  const rows = [];

  for (let y = 0; y < lines; y++) {
    const line = buffer.getLine(buffer.baseY + y);
    const cells = [];
    for (let x = 0; x < columns; x++) {
      if (!line) {
        cells.push([" ", null, null, false, false, 0, false, null]);
        continue;
      }
      const cell = line.getCell(x);
      if (!cell) {
        cells.push([" ", null, null, false, false, 0, false, null]);
        continue;
      }

      // The second half of a wide character holds no character of its
      // own: xterm.js gives it a width of zero. Every judge reports a
      // space there.
      const text = cell.getWidth() === 0 ? " " : cell.getChars() || " ";

      // `isFgDefault` and `isFgRGB` answer with a boolean; `isBold`
      // and the other attributes answer with a number.
      cells.push([
        text,
        color(cell.isFgDefault(), cell.isFgRGB(), cell.getFgColor()),
        color(cell.isBgDefault(), cell.isBgRGB(), cell.getBgColor()),
        cell.isBold() !== 0,
        cell.isItalic() !== 0,
        // Only whether a line is there. xterm.js keeps the shape and
        // the colour of the line out of its buffer API, so this judge
        // says nothing about either and the panel drops both before
        // it compares.
        cell.isUnderline() !== 0 ? 1 : 0,
        cell.isInverse() !== 0,
        null,
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
