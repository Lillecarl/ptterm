/*
 * Read a screen back from libghostty-vt, the terminal that Ghostty
 * carries as a library.
 *
 * One process answers one request after another, the same way the
 * judges written in Rust do. A request is one line of JSON:
 *
 *     {"data": "...", "lines": 6, "columns": 20}
 *
 * The answer is one line holding the screen, as rows of cells:
 *
 *     {"ghostty": [[[char, fg, bg, bold, italic, ul, rev, ulcol], ...]]}
 *
 * A colour is null, ["index", n] or ["rgb", r, g, b]. That is the shape
 * every other judge speaks, so `rust_oracle` reads this one too.
 *
 * This is C and not a binding, because the library hands out sized
 * structs and tagged unions. The compiler knows their layout; a
 * hand written binding only thinks it does.
 */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <ghostty/vt.h>

/* A screen larger than this is not something the tests ask for. */
#define MAX_CELLS (1024 * 1024)

/* Grow-as-needed output buffer. Writing straight to stdout would mean
 * a syscall for every cell. */
typedef struct {
  char *data;
  size_t len;
  size_t cap;
} Buffer;

static void buffer_reserve(Buffer *buffer, size_t extra) {
  if (buffer->len + extra + 1 <= buffer->cap) return;
  size_t cap = buffer->cap ? buffer->cap : 4096;
  while (cap < buffer->len + extra + 1) cap *= 2;
  buffer->data = realloc(buffer->data, cap);
  assert(buffer->data != NULL);
  buffer->cap = cap;
}

static void put(Buffer *buffer, const char *text) {
  size_t len = strlen(text);
  buffer_reserve(buffer, len);
  memcpy(buffer->data + buffer->len, text, len);
  buffer->len += len;
  buffer->data[buffer->len] = 0;
}

static void put_int(Buffer *buffer, long value) {
  char text[32];
  snprintf(text, sizeof(text), "%ld", value);
  put(buffer, text);
}

/* One codepoint as JSON string content. Everything outside plain ASCII
 * goes as \uXXXX, so the answer is ASCII whatever the screen holds. */
static void put_codepoint(Buffer *buffer, uint32_t codepoint) {
  char text[16];
  if (codepoint == '"' || codepoint == '\\') {
    snprintf(text, sizeof(text), "\\%c", (char)codepoint);
  } else if (codepoint >= 0x20 && codepoint < 0x7f) {
    snprintf(text, sizeof(text), "%c", (char)codepoint);
  } else if (codepoint < 0x10000) {
    snprintf(text, sizeof(text), "\\u%04x", codepoint);
  } else {
    /* Outside the basic plane: a surrogate pair, the way JSON wants. */
    uint32_t value = codepoint - 0x10000;
    snprintf(text, sizeof(text), "\\u%04x\\u%04x", 0xd800 + (value >> 10),
             0xdc00 + (value & 0x3ff));
  }
  put(buffer, text);
}

static void put_color(Buffer *buffer, GhosttyStyleColor color) {
  switch (color.tag) {
    case GHOSTTY_STYLE_COLOR_PALETTE:
      put(buffer, "[\"index\",");
      put_int(buffer, color.value.palette);
      put(buffer, "]");
      return;
    case GHOSTTY_STYLE_COLOR_RGB:
      put(buffer, "[\"rgb\",");
      put_int(buffer, color.value.rgb.r);
      put(buffer, ",");
      put_int(buffer, color.value.rgb.g);
      put(buffer, ",");
      put_int(buffer, color.value.rgb.b);
      put(buffer, "]");
      return;
    default:
      put(buffer, "null");
      return;
  }
}

/* Read one JSON string field. The requests come from the tests, so the
 * parsing only has to cover what they send: the escapes that
 * json.dumps writes. */
static char *read_string_field(const char *line, const char *name,
                               size_t *out_len) {
  char needle[64];
  snprintf(needle, sizeof(needle), "\"%s\"", name);
  const char *at = strstr(line, needle);
  if (at == NULL) return NULL;
  at = strchr(at + strlen(needle), '"');
  if (at == NULL) return NULL;
  at++;

  size_t cap = strlen(at) * 4 + 5;
  char *out = malloc(cap);
  assert(out != NULL);
  size_t len = 0;

  while (*at && *at != '"') {
    uint32_t codepoint;
    if (*at != '\\') {
      out[len++] = *at++;
      continue;
    }
    at++;
    switch (*at) {
      case 'n': out[len++] = '\n'; at++; continue;
      case 'r': out[len++] = '\r'; at++; continue;
      case 't': out[len++] = '\t'; at++; continue;
      case 'b': out[len++] = '\b'; at++; continue;
      case 'f': out[len++] = '\f'; at++; continue;
      case '"': out[len++] = '"'; at++; continue;
      case '\\': out[len++] = '\\'; at++; continue;
      case '/': out[len++] = '/'; at++; continue;
      case 'u': break;
      default: out[len++] = *at++; continue;
    }

    at++;
    char digits[5] = {at[0], at[1], at[2], at[3], 0};
    codepoint = (uint32_t)strtoul(digits, NULL, 16);
    at += 4;

    /* A surrogate pair carries one codepoint above the basic plane. */
    if (codepoint >= 0xd800 && codepoint < 0xdc00 && at[0] == '\\' &&
        at[1] == 'u') {
      char low_digits[5] = {at[2], at[3], at[4], at[5], 0};
      uint32_t low = (uint32_t)strtoul(low_digits, NULL, 16);
      if (low >= 0xdc00 && low < 0xe000) {
        codepoint = 0x10000 + ((codepoint - 0xd800) << 10) + (low - 0xdc00);
        at += 6;
      }
    }

    /* Back to UTF-8: the terminal reads bytes. */
    if (codepoint < 0x80) {
      out[len++] = (char)codepoint;
    } else if (codepoint < 0x800) {
      out[len++] = (char)(0xc0 | (codepoint >> 6));
      out[len++] = (char)(0x80 | (codepoint & 0x3f));
    } else if (codepoint < 0x10000) {
      out[len++] = (char)(0xe0 | (codepoint >> 12));
      out[len++] = (char)(0x80 | ((codepoint >> 6) & 0x3f));
      out[len++] = (char)(0x80 | (codepoint & 0x3f));
    } else {
      out[len++] = (char)(0xf0 | (codepoint >> 18));
      out[len++] = (char)(0x80 | ((codepoint >> 12) & 0x3f));
      out[len++] = (char)(0x80 | ((codepoint >> 6) & 0x3f));
      out[len++] = (char)(0x80 | (codepoint & 0x3f));
    }
  }

  out[len] = 0;
  *out_len = len;
  return out;
}

static long read_int_field(const char *line, const char *name, long fallback) {
  char needle[64];
  snprintf(needle, sizeof(needle), "\"%s\"", name);
  const char *at = strstr(line, needle);
  if (at == NULL) return fallback;
  at = strchr(at + strlen(needle), ':');
  if (at == NULL) return fallback;
  return strtol(at + 1, NULL, 10);
}

static void write_cell(Buffer *out, const GhosttyGridRef *ref) {
  GhosttyCell cell;
  if (ghostty_grid_ref_cell(ref, &cell) != GHOSTTY_SUCCESS) {
    put(out, "[\" \",null,null,false,false,0,false,null]");
    return;
  }

  bool has_text = false;
  ghostty_cell_get(cell, GHOSTTY_CELL_DATA_HAS_TEXT, &has_text);

  GhosttyCellWide wide = GHOSTTY_CELL_WIDE_NARROW;
  ghostty_cell_get(cell, GHOSTTY_CELL_DATA_WIDE, &wide);

  put(out, "[\"");
  if (wide == GHOSTTY_CELL_WIDE_SPACER_TAIL) {
    /* The second half of a wide character holds no character of its
     * own. Every judge reports a space there. */
    put(out, " ");
  } else if (has_text) {
    /* The graphemes of a cell are the whole cluster: the character and
     * the marks of no width that hang on it, in order. Reading the
     * codepoint alone would drop every combining mark, and reading
     * both would write the character twice. */
    uint32_t cluster[16];
    size_t cluster_len = 0;
    if (ghostty_grid_ref_graphemes(ref, cluster, 16, &cluster_len) ==
            GHOSTTY_SUCCESS &&
        cluster_len > 0) {
      for (size_t i = 0; i < cluster_len; i++) put_codepoint(out, cluster[i]);
    } else {
      uint32_t codepoint = 0;
      ghostty_cell_get(cell, GHOSTTY_CELL_DATA_CODEPOINT, &codepoint);
      put_codepoint(out, codepoint);
    }
  } else {
    put(out, " ");
  }
  put(out, "\",");

  GhosttyStyle style = GHOSTTY_INIT_SIZED(GhosttyStyle);
  ghostty_grid_ref_style(ref, &style);

  put_color(out, style.fg_color);
  put(out, ",");
  put_color(out, style.bg_color);
  put(out, ",");
  put(out, style.bold ? "true," : "false,");
  put(out, style.italic ? "true," : "false,");
  put_int(out, style.underline);
  put(out, ",");
  put(out, style.inverse ? "true," : "false,");
  if (style.underline == GHOSTTY_SGR_UNDERLINE_NONE) {
    put(out, "null");
  } else {
    put_color(out, style.underline_color);
  }
  put(out, "]");
}

static void answer(const char *line, Buffer *out) {
  size_t data_len = 0;
  char *data = read_string_field(line, "data", &data_len);
  long rows = read_int_field(line, "lines", 6);
  long columns = read_int_field(line, "columns", 20);

  out->len = 0;
  if (data == NULL || rows <= 0 || columns <= 0 ||
      rows * columns > MAX_CELLS) {
    put(out, "{\"ghostty\":[]}");
    free(data);
    return;
  }

  GhosttyTerminal terminal;
  GhosttyTerminalOptions options = {
      .cols = (uint16_t)columns,
      .rows = (uint16_t)rows,
      .max_scrollback = 0,
  };
  if (ghostty_terminal_new(NULL, &terminal, options) != GHOSTTY_SUCCESS) {
    put(out, "{\"ghostty\":[]}");
    free(data);
    return;
  }

  ghostty_terminal_vt_write(terminal, (const uint8_t *)data, data_len);

  put(out, "{\"ghostty\":[");
  for (long row = 0; row < rows; row++) {
    if (row) put(out, ",");
    put(out, "[");
    for (long column = 0; column < columns; column++) {
      if (column) put(out, ",");
      GhosttyGridRef ref = GHOSTTY_INIT_SIZED(GhosttyGridRef);
      GhosttyPoint point = {
          .tag = GHOSTTY_POINT_TAG_ACTIVE,
          .value = {.coordinate = {.x = (uint32_t)column,
                                   .y = (uint32_t)row}},
      };
      if (ghostty_terminal_grid_ref(terminal, point, &ref) !=
          GHOSTTY_SUCCESS) {
        put(out, "[\" \",null,null,false,false,0,false,null]");
        continue;
      }
      write_cell(out, &ref);
    }
    put(out, "]");
  }
  put(out, "]}");

  ghostty_terminal_free(terminal);
  free(data);
}

int main(void) {
  char *line = NULL;
  size_t line_cap = 0;
  Buffer out = {0};

  while (getline(&line, &line_cap, stdin) > 0) {
    answer(line, &out);
    fputs(out.data, stdout);
    fputc('\n', stdout);
    fflush(stdout);
  }

  free(line);
  free(out.data);
  return 0;
}
