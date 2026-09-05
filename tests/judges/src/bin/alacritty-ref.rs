//! Alacritty, judging one of its own reference tests against our wire.
//!
//! `alacritty_terminal/tests/ref.rs` feeds a recording to a `Term` and
//! compares the grid against a recorded one. This does the same thing
//! with one byte stream changed: the recording goes to a pymux pane
//! instead, and what pymux emitted comes in here.
//!
//! ```text
//!   the recording ──▶ a full screen pane ──▶ pymux emits ──▶ this
//!                                                              │
//!                            grid.json ── compared with ───────┘
//! ```
//!
//! So Alacritty's own assertion holds if, and only if, we emit what the
//! program drew. Nothing of ours decides anything: the grid is
//! deserialized by `alacritty_terminal`, built by `alacritty_terminal`,
//! and compared with `alacritty_terminal`'s own `PartialEq`.
//!
//! Usage: `alacritty-ref <ref directory>`, with the wire on standard
//! input. The directory is one of `alacritty_terminal/tests/ref/*`, and
//! holds `size.json`, `config.json` and `grid.json`. The recording in
//! it is the driver's business, not this program's.
//!
//! It answers with its exit code: 0 when the grids are the same, 1 when
//! they differ, and 2 when it could not ask. A difference is printed
//! one cell to a line, the way `ref.rs` prints one.
//!
//! ## The one thing that is masked
//!
//! `WRAPLINE` says a row was filled and the text went on below it. A
//! wire cannot carry it. pymux positions every row of every frame and
//! turns autowrap off, so nothing the judge reads ever wraps, and the
//! flag is off on every cell we produce and on in the reference
//! wherever a line was long.
//!
//! That is `?lineinfo cont` again, and it is the same answer: a
//! projection of what a wire cannot hold, taken off both sides before
//! they are compared. `ptterm/tests/panel.py` drops what a judge cannot
//! hold for the same reason. Every other flag is compared.
//!
//! The flag comes off in the serialized form and not through the grid,
//! because a recorded grid cannot be indexed. `grid.json` for `csi_rep`
//! holds `lines: 29` and `raw.visible_lines: 28`, and `Line` is read
//! against the second: `Storage::compute_index` turns the last row of
//! the screen into a wild offset. Alacritty's own `ref.rs` never meets
//! it, because it indexes only to print a difference it has already
//! found. Nothing here indexes a grid at all.

use std::fs;
use std::io::{self, Read};
use std::path::Path;
use std::process::ExitCode;

use alacritty_terminal::event::VoidListener;
use alacritty_terminal::grid::{Dimensions, Grid};
use alacritty_terminal::term::cell::Cell;
use alacritty_terminal::term::{Config, Term};
use alacritty_terminal::vte::ansi::Processor;
use serde_json::Value;

/// How many differing cells to print before saying how many are left.
/// A screen of 174 by 96 that went wrong early has sixteen thousand,
/// and a log nobody reads is worth as much as no log.
const MOST_TO_PRINT: usize = 40;

/// The size of the screen, the way `term::test::TermSize` gives it:
/// the history is not part of it, because `Config` carries that.
struct Size {
    screen_lines: usize,
    columns: usize,
}

impl Dimensions for Size {
    fn total_lines(&self) -> usize {
        self.screen_lines
    }
    fn screen_lines(&self) -> usize {
        self.screen_lines
    }
    fn columns(&self) -> usize {
        self.columns
    }
}

fn number(value: &Value, name: &str) -> Result<usize, String> {
    value
        .get(name)
        .and_then(|found| found.as_u64())
        .map(|found| found as usize)
        .ok_or_else(|| format!("{name} is not a number"))
}

/// Take `WRAPLINE` out of every `flags` in a serialized grid.
///
/// bitflags writes the set as the names joined by " | ", so this walks
/// the whole value and rewrites each one. Walking rather than following
/// a path is on purpose: the shape of a `Row` is Alacritty's business,
/// and a member named `flags` is a set of them wherever it sits.
fn unwrap_the_lines(value: &mut Value) {
    match value {
        Value::Object(members) => {
            for (name, member) in members.iter_mut() {
                if name == "flags" {
                    if let Value::String(flags) = member {
                        let kept: Vec<&str> = flags
                            .split('|')
                            .map(|one| one.trim())
                            .filter(|one| !one.is_empty() && *one != "WRAPLINE")
                            .collect();
                        *flags = kept.join(" | ");
                        continue;
                    }
                }
                unwrap_the_lines(member);
            }
        }
        Value::Array(members) => {
            for member in members.iter_mut() {
                unwrap_the_lines(member);
            }
        }
        _ => {}
    }
}

/// The rows of a serialized grid, as the cells of each one.
fn rows(value: &Value) -> &[Value] {
    value
        .get("raw")
        .and_then(|raw| raw.get("inner"))
        .and_then(|inner| inner.as_array())
        .map(|found| found.as_slice())
        .unwrap_or(&[])
}

fn cells(row: &Value) -> &[Value] {
    row.get("inner")
        .and_then(|inner| inner.as_array())
        .map(|found| found.as_slice())
        .unwrap_or(&[])
}

fn judge(directory: &Path, wire: &[u8]) -> Result<bool, String> {
    let read = |name: &str| {
        fs::read_to_string(directory.join(name)).map_err(|why| format!("{name}: {why}"))
    };

    let size: Value = serde_json::from_str(&read("size.json")?).map_err(|why| why.to_string())?;
    let config: Value =
        serde_json::from_str(&read("config.json")?).map_err(|why| why.to_string())?;

    let history = number(&config, "history_size")?;
    if history != 0 {
        // The reference grid then holds lines that scrolled away, and a
        // wire carries a screen and nothing else. The driver leaves
        // those tests out by name; this says so rather than answering a
        // question it cannot answer.
        return Err(format!(
            "history_size is {history}, and a wire carries no history"
        ));
    }

    let size = Size {
        screen_lines: number(&size, "screen_lines")?,
        columns: number(&size, "columns")?,
    };

    let options = Config {
        scrolling_history: history,
        ..Default::default()
    };
    let mut terminal = Term::new(options, &size, VoidListener);
    let mut parser: Processor = Processor::new();
    parser.advance(&mut terminal, wire);

    // The same two calls `ref.rs` makes: fill in the lines that were
    // never touched, and drop the ones past the end.
    let mut grid = terminal.grid().clone();
    grid.initialize_all();
    grid.truncate();

    let mut expected: Value =
        serde_json::from_str(&read("grid.json")?).map_err(|why| format!("grid.json: {why}"))?;
    let mut found = serde_json::to_value(&grid).map_err(|why| why.to_string())?;

    unwrap_the_lines(&mut expected);
    unwrap_the_lines(&mut found);

    // Alacritty's own equality decides, not the JSON: two values that
    // differ only in a field it leaves out are the same grid.
    let one: Grid<Cell> =
        serde_json::from_value(expected.clone()).map_err(|why| format!("grid.json: {why}"))?;
    let other: Grid<Cell> = serde_json::from_value(found.clone()).map_err(|why| why.to_string())?;
    if one == other {
        return Ok(true);
    }

    let mut printed = 0;
    let mut differ = 0;
    let expected_rows = rows(&expected);
    let found_rows = rows(&found);
    for (line, (expected_row, found_row)) in
        expected_rows.iter().zip(found_rows.iter()).enumerate()
    {
        for (column, (one, other)) in cells(expected_row)
            .iter()
            .zip(cells(found_row).iter())
            .enumerate()
        {
            if one != other {
                differ += 1;
                if printed < MOST_TO_PRINT {
                    println!("[{line}][{column}] {one} => {other}");
                    printed += 1;
                }
            }
        }
    }
    if differ > printed {
        println!("and {} more cells", differ - printed);
    }
    if differ == 0 {
        println!(
            "the grids differ in their shape: {} rows against {} rows",
            expected_rows.len(),
            found_rows.len(),
        );
    }
    Ok(false)
}

fn main() -> ExitCode {
    let directory = match std::env::args().nth(1) {
        Some(one) => one,
        None => {
            eprintln!("usage: alacritty-ref <ref directory>, with the wire on stdin");
            return ExitCode::from(2);
        }
    };

    let mut wire = Vec::new();
    if let Err(why) = io::stdin().read_to_end(&mut wire) {
        eprintln!("could not read the wire: {why}");
        return ExitCode::from(2);
    }

    match judge(Path::new(&directory), &wire) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::from(1),
        Err(why) => {
            eprintln!("{why}");
            ExitCode::from(2)
        }
    }
}
