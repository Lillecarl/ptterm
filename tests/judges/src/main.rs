//! Read a screen back from other terminal emulators.
//!
//! Two modern emulators run here, each with a screen model of its own:
//! WezTerm and Alacritty. The same bytes go into both and the cells
//! come back out, in the shape that `kitty_oracle` uses on the python
//! side.
//!
//! One request is one line of JSON on standard input:
//!
//! ```json
//! {"data": "hello", "lines": 6, "columns": 20}
//! ```
//!
//! One answer is one line of JSON on standard output, holding a grid
//! for every emulator. A cell is an array, to keep the answer small:
//!
//! ```json
//! [char, fg, bg, bold, italic, underline, reverse, underline_color]
//! ```
//!
//! A colour is `null` for the default, `["index", n]` for a number of
//! the palette or `["rgb", r, g, b]`. The python side resolves a
//! number above fifteen, so that every judge resolves it the same way.
//!
//! The process stays open and answers one request after another,
//! because the hunt asks tens of thousands of times.

use std::io::{self, BufRead, Write};
use std::sync::Arc;

use serde_json::{json, Value};

// ---------------------------------------------------------------------
// WezTerm.

use wezterm_term::color::{ColorAttribute, ColorPalette};
use wezterm_term::{Intensity, Terminal, TerminalConfiguration, TerminalSize};

#[derive(Debug)]
struct WezConfig;

impl TerminalConfiguration for WezConfig {
    fn color_palette(&self) -> ColorPalette {
        ColorPalette::default()
    }
}

fn wez_color(color: ColorAttribute) -> Value {
    match color {
        ColorAttribute::Default => Value::Null,
        ColorAttribute::PaletteIndex(index) => json!(["index", index]),
        ColorAttribute::TrueColorWithPaletteFallback(rgb, _)
        | ColorAttribute::TrueColorWithDefaultFallback(rgb) => {
            let (red, green, blue, _alpha) = rgb.to_srgb_u8();
            json!(["rgb", red, green, blue])
        }
    }
}

fn wezterm_screen(data: &str, lines: usize, columns: usize) -> Value {
    let size = TerminalSize {
        rows: lines,
        cols: columns,
        pixel_width: columns * 10,
        pixel_height: lines * 20,
        dpi: 96,
    };
    let mut terminal = Terminal::new(
        size,
        Arc::new(WezConfig),
        "ptterm-judges",
        "0.1.0",
        Box::new(Vec::new()),
    );
    terminal.advance_bytes(data.as_bytes());

    let screen = terminal.screen_mut();
    let mut rows = Vec::with_capacity(lines);
    for y in 0..lines {
        let mut row = Vec::with_capacity(columns);
        for x in 0..columns {
            row.push(match screen.get_cell(x, y as i64) {
                None => json!([" ", null, null, false, false, 0, false, null]),
                Some(cell) => {
                    let attrs = cell.attrs();
                    let text = cell.str();
                    let underline = attrs.underline() as u8;
                    json!([
                        if text.is_empty() { " " } else { text },
                        wez_color(attrs.foreground()),
                        wez_color(attrs.background()),
                        attrs.intensity() == Intensity::Bold,
                        attrs.italic(),
                        underline,
                        attrs.reverse(),
                        // The colour of a line that nobody draws is
                        // not visible, so it does not travel.
                        if underline == 0 {
                            Value::Null
                        } else {
                            wez_color(attrs.underline_color())
                        },
                    ])
                }
            });
        }
        rows.push(Value::Array(row));
    }
    Value::Array(rows)
}

// ---------------------------------------------------------------------
// Alacritty.

use alacritty_terminal::event::VoidListener;
use alacritty_terminal::grid::Dimensions;
use alacritty_terminal::index::{Column, Line, Point};
use alacritty_terminal::term::cell::Flags;
use alacritty_terminal::term::{Config, Term};
use alacritty_terminal::vte::ansi::{Color, Processor};

struct Size {
    lines: usize,
    columns: usize,
}

impl Dimensions for Size {
    fn total_lines(&self) -> usize {
        self.lines
    }
    fn screen_lines(&self) -> usize {
        self.lines
    }
    fn columns(&self) -> usize {
        self.columns
    }
}

fn alacritty_color(color: Color) -> Value {
    match color {
        Color::Spec(rgb) => json!(["rgb", rgb.r, rgb.g, rgb.b]),
        Color::Indexed(index) => json!(["index", index]),
        Color::Named(named) => {
            let index = named as usize;
            if index < 16 {
                json!(["index", index])
            } else {
                // The foreground, the background and the cursor are
                // the colour of the terminal, which is the default.
                Value::Null
            }
        }
    }
}

fn alacritty_underline(flags: Flags) -> u8 {
    if flags.contains(Flags::DOUBLE_UNDERLINE) {
        2
    } else if flags.contains(Flags::UNDERCURL) {
        3
    } else if flags.contains(Flags::DOTTED_UNDERLINE) {
        4
    } else if flags.contains(Flags::DASHED_UNDERLINE) {
        5
    } else if flags.contains(Flags::UNDERLINE) {
        1
    } else {
        0
    }
}

fn alacritty_screen(data: &str, lines: usize, columns: usize) -> Value {
    let size = Size { lines, columns };
    let config = Config {
        scrolling_history: 0,
        ..Config::default()
    };
    let mut term = Term::new(config, &size, VoidListener);
    let mut processor: Processor = Processor::new();
    processor.advance(&mut term, data.as_bytes());

    let grid = term.grid();
    let mut rows = Vec::with_capacity(lines);
    for y in 0..lines {
        let mut row = Vec::with_capacity(columns);
        for x in 0..columns {
            let cell = &grid[Point::new(Line(y as i32), Column(x))];
            let underline = alacritty_underline(cell.flags);
            row.push(json!([
                // The second half of a double width character holds no
                // character of its own.
                //
                // Alacritty keeps a mark of no width beside the cell
                // and not in it. Reading `c` alone drops every
                // combining mark, and the judge then says a screen
                // holds no mark when it holds one.
                if cell.flags.contains(Flags::WIDE_CHAR_SPACER) {
                    " ".to_string()
                } else {
                    let mut text = cell.c.to_string();
                    if let Some(marks) = cell.zerowidth() {
                        text.extend(marks.iter());
                    }
                    text
                },
                alacritty_color(cell.fg),
                alacritty_color(cell.bg),
                cell.flags.contains(Flags::BOLD),
                cell.flags.contains(Flags::ITALIC),
                underline,
                cell.flags.contains(Flags::INVERSE),
                if underline == 0 {
                    Value::Null
                } else {
                    cell.underline_color().map_or(Value::Null, alacritty_color)
                },
            ]));
        }
        rows.push(Value::Array(row));
    }
    Value::Array(rows)
}

// ---------------------------------------------------------------------

fn main() {
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    for line in stdin.lock().lines() {
        let line = line.expect("a line of standard input");
        if line.trim().is_empty() {
            continue;
        }
        let request: Value = serde_json::from_str(&line).expect("a request of JSON");
        let data = request["data"].as_str().unwrap_or("");
        let lines = request["lines"].as_u64().unwrap_or(6) as usize;
        let columns = request["columns"].as_u64().unwrap_or(20) as usize;

        let answer = json!({
            "wezterm": wezterm_screen(data, lines, columns),
            "alacritty": alacritty_screen(data, lines, columns),
        });
        writeln!(stdout, "{}", answer).expect("an answer on standard output");
        stdout.flush().expect("a flush");
    }
}
