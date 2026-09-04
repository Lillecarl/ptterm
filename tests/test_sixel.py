"""
Tests for the sixel decoder and for the sixel images that a pane
stores.
"""
from ptterm.screen import BetterScreen
from ptterm.sixel import DEFAULT_PALETTE, decode_sixel
from ptterm.stream import BetterStream

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)

# Colour definitions in the RGB system (percentages).
# Colour definitions on registers that are not the background one.
DEFINE_RED = "#4;2;100;0;0"
DEFINE_GREEN = "#5;2;0;100;0"
RED_ = "#4"
GREEN_ = "#5"


def decode(body, params="0;0;0"):
    "Decode a sixel body. Returns (width, height, pixel getter)."
    result = decode_sixel(params + "q" + body)
    assert result is not None
    width, height, data = result

    def pixel(x, y):
        offset = (y * width + x) * 4
        return tuple(data[offset : offset + 4])

    return width, height, pixel


def test_a_payload_without_a_head_is_not_sixel():
    assert decode_sixel("no head here") is None


def test_an_empty_body_has_no_pixels():
    assert decode_sixel("0;0;0q") is None


def test_one_data_character_is_a_column_of_six():
    # "~" is 0x7e: all six bits set.
    width, height, pixel = decode(DEFINE_RED + RED_ + "~")
    assert (width, height) == (1, 6)
    for y in range(6):
        assert pixel(0, y) == RED + (255,)


def test_the_bits_select_the_rows():
    # "A" is 0x41: value 2, so only the second row of the band.
    width, height, pixel = decode(DEFINE_RED + RED_ + "A")
    assert (width, height) == (1, 6)
    assert pixel(0, 0) == (0, 0, 0, 255)  # Background: register 0...
    assert pixel(0, 1) == RED + (255,)
    assert pixel(0, 2) == (0, 0, 0, 255)


def test_the_default_palette_is_the_vt340_one():
    # Register 1 without a definition: DEC blue, 20/20/80 percent.
    _width, _height, pixel = decode("#1~")
    assert pixel(0, 0) == DEFAULT_PALETTE[1] + (255,)
    assert DEFAULT_PALETTE[1] == (51, 51, 204)


def test_an_rgb_definition():
    _width, _height, pixel = decode("#4;2;0;100;0#4~")
    assert pixel(0, 0) == GREEN + (255,)


def test_an_hls_definition_starts_the_wheel_at_blue():
    # DEC turns the hue wheel: 0 is blue, 120 is red, 240 is green.
    for hue, expected in ((0, BLUE), (120, RED), (240, GREEN)):
        _width, _height, pixel = decode("#4;1;%i;50;100#4~" % hue)
        assert pixel(0, 0) == expected + (255,)


def test_an_hls_definition_uses_lightness_and_saturation():
    _width, _height, pixel = decode("#4;1;0;100;100#4~")
    assert pixel(0, 0) == (255, 255, 255, 255)  # Full lightness: white.
    _width, _height, pixel = decode("#4;1;0;50;0#4~")
    assert pixel(0, 0) == (128, 128, 128, 255)  # No saturation: grey.


def test_repeat():
    width, height, pixel = decode(DEFINE_RED + RED_ + "!5~")
    assert (width, height) == (5, 6)
    for x in range(5):
        assert pixel(x, 0) == RED + (255,)


def test_a_repeat_without_a_count_writes_once():
    width, _height, _pixel = decode("#0!~")
    assert width == 1


def test_carriage_return_paints_over_the_same_band():
    body = DEFINE_RED + DEFINE_GREEN + "#4!4~$#5!2~"
    width, height, pixel = decode(body)
    assert (width, height) == (4, 6)
    assert pixel(0, 0) == GREEN + (255,)
    assert pixel(1, 0) == GREEN + (255,)
    assert pixel(2, 0) == RED + (255,)


def test_graphics_new_line_starts_the_next_band():
    body = DEFINE_RED + DEFINE_GREEN + "#4~-#5~"
    width, height, pixel = decode(body)
    assert (width, height) == (1, 12)
    assert pixel(0, 5) == RED + (255,)
    assert pixel(0, 6) == GREEN + (255,)


def test_raster_attributes_extend_the_canvas():
    width, height, pixel = decode('"1;1;10;20' + DEFINE_RED + RED_ + "~")
    assert (width, height) == (10, 20)
    # The body only wrote the first column.
    assert pixel(0, 0) == RED + (255,)
    assert pixel(9, 19) == (0, 0, 0, 255)


def test_raster_attributes_never_shrink_the_width():
    width, height, _pixel = decode('"1;1;1;6' + "#0!4~")
    assert (width, height) == (4, 6)


def test_the_raster_height_crops_the_last_band():
    # Two bands make twelve rows, but the image is eight tall.
    width, height, _pixel = decode('"1;1;4;8' + "#0!4~-!4~")
    assert (width, height) == (4, 8)


def test_a_raster_height_far_below_the_bands_is_ignored():
    # A bogus value must not throw away rows that the body wrote.
    width, height, _pixel = decode('"1;1;4;1' + "#0!4~-!4~")
    assert (width, height) == (4, 12)


def test_unwritten_pixels_are_transparent_with_p2_one():
    _width, _height, pixel = decode("#0A", params="0;1;0")
    assert pixel(0, 0) == (0, 0, 0, 0)  # Never written.
    assert pixel(0, 1)[3] == 255  # Written.


def test_unwritten_pixels_take_register_zero_otherwise():
    _width, _height, pixel = decode("#1;2;0;100;0#1A", params="0;0;0")
    assert pixel(0, 0) == (0, 0, 0, 255)  # Register 0 is black.
    assert pixel(0, 1) == GREEN + (255,)


def test_the_background_follows_register_zero():
    _width, _height, pixel = decode("#0;2;0;0;100#1A")
    assert pixel(0, 0) == BLUE + (255,)


def test_whitespace_in_the_body_is_ignored():
    width, height, _pixel = decode(DEFINE_RED + RED_ + "~\n  ~\r\n~")
    assert (width, height) == (3, 6)


def test_a_selection_of_an_undefined_high_register_is_black():
    _width, _height, pixel = decode("#200~")
    assert pixel(0, 0) == (0, 0, 0, 255)


def test_a_huge_repeat_is_bounded():
    # The guard must cap the width instead of allocating forever.
    width, height, _pixel = decode("#0!999999999~")
    assert (width, height) == (16384, 6)


def test_an_image_past_the_pixel_bound_is_refused():
    assert decode_sixel('0;0;0q"1;1;9000;9000#0~') is None


# ----------------------------------------------------------------------
# The screen stores the image.


def make_screen():
    responses = []
    screen = BetterScreen(24, 80, write_process_input=responses.append)
    stream = BetterStream(screen)
    return screen, stream, responses


def sixel(body, params="0;0;0"):
    return "\x1bP" + params + "q" + body + "\x1b\\"


def test_a_sixel_image_becomes_a_placement():
    screen, stream, _ = make_screen()
    stream.feed(sixel('"1;1;30;12' + DEFINE_RED + RED_ + "!30~-!30~"))

    assert len(screen.graphics.placements) == 1
    placement = screen.graphics.placements[0]
    # 30x12 pixels with a 10x20 cell: three columns, one row.
    assert (placement.x, placement.y) == (0, 0)
    assert (placement.columns, placement.rows) == (3, 1)

    image = screen.graphics.images_by_id[placement.image_id]
    assert (image.format, image.width, image.height) == (32, 30, 12)
    assert len(image.data) == 30 * 12 * 4


def test_the_cursor_lands_below_the_image():
    screen, stream, _ = make_screen()
    stream.feed("abc")
    stream.feed(sixel('"1;1;30;40' + DEFINE_RED + RED_ + "~"))
    # 40 pixels is two rows of 20. The cursor goes to the left of the
    # row below the image.
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (0, 2)


def test_the_image_covers_its_cells():
    screen, stream, _ = make_screen()
    stream.feed("abcdef")
    stream.feed("\r")
    stream.feed(sixel('"1;1;30;12' + DEFINE_RED + RED_ + "~"))
    row = screen.pt_screen.data_buffer[0]
    assert "".join(row[i].char for i in range(6)) == "   def"


def test_a_sixel_image_does_not_take_a_kitty_image_id():
    screen, stream, _ = make_screen()
    # A kitty image claims id 1 first.
    stream.feed("\x1b_Ga=t,f=24,s=1,v=1,i=1;AAAA\x1b\\")
    stream.feed(sixel(DEFINE_RED + RED_ + "~"))

    ids = sorted(screen.graphics.images_by_id)
    assert len(ids) == 2
    assert 1 in ids
    assert screen.graphics.images_by_id[1].width == 1  # The kitty one.


def test_a_non_sixel_dcs_is_consumed():
    screen, stream, _ = make_screen()
    stream.feed("\x1bP$qm\x1b\\")
    stream.feed("hello")
    assert screen.graphics.placements == []
    row = screen.pt_screen.data_buffer[0]
    assert "".join(row[i].char for i in range(5)) == "hello"


def test_a_sixel_image_scrolls_with_the_text():
    screen, stream, _ = make_screen()
    stream.feed("\x1b[1;10r")  # Margins: rows 0..9.
    stream.feed("\x1b[5;1H")
    stream.feed(sixel('"1;1;30;12' + DEFINE_RED + RED_ + "~"))
    assert screen.graphics.placements[0].y == 4

    stream.feed("\x1b[10;1H")
    stream.feed("\n")
    assert screen.graphics.placements[0].y == 3
