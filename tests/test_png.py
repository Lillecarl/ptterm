"""
Tests for the PNG decoder.

The images marked "golden" were written by an independent encoder
(Pillow), so they check the decoder against a real PNG writer rather
than against the assumptions of this repository. The filter tests build
their own images and apply the forward filter by hand, which checks the
filter arithmetic on its own.
"""
import struct
import zlib

import pytest

from ptterm.png import decode_png

# ----------------------------------------------------------------------
# Golden images.

RGBA_3X2 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000300000002080600000"
    "09d74661a0000001d49444154789c05c1a10100300cc02074f5746fed"
    "e71988e488795b15fa81240ab3266668530000000049454e44ae426082"
)
RGBA_3X2_PIXELS = [
    (255, 0, 0, 255),
    (0, 255, 0, 128),
    (0, 0, 255, 0),
    (10, 20, 30, 255),
    (255, 255, 255, 255),
    (0, 0, 0, 255),
]

PALETTE_2X2 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000020000000202030000000fd8e5"
    "b700000009504c5445ff000000ff000000ff2d4acd8a0000000374524e53ff00"
    "80a95673130000000c49444154789c63106098000000c400a1165cba96000000"
    "0049454e44ae426082"
)
PALETTE_2X2_PIXELS = [
    (255, 0, 0, 255),
    (0, 255, 0, 0),
    (0, 0, 255, 128),
    (0, 255, 0, 0),
]

GREY_4X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000004000000010800000000dc5750"
    "110000000d49444154789c6360085df51f00035701ff2d6672ef000000004945"
    "4e44ae426082"
)

GREY16_2X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000200000001100000000081d9fc"
    "150000000d49444154789c636060f8ff1f00030201ffe6770bae0000000049454e44ae426082"
)

RGB_8X8 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000080000000808020000004b6d29"
    "dc0000003649444154789c6364606090c7865818541918187831115c420a0d21"
    "4ba82323340913188ac694708420ac127e0c0c7e6812d130896800ec550964c9"
    "cdf0820000000049454e44ae426082"
)
RGB_8X8_PIXELS = [
    ((x * 31) % 256, (y * 37) % 256, (x * y * 13) % 256)
    for y in range(8)
    for x in range(8)
]

BILEVEL_8X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000008000000010100000000cb7bd2"
    "ee0000000a49444154789c63880200005c005bd8b4565a0000000049454e44ae426082"
)


def pixels(data):
    "Split RGBA bytes into tuples."
    return [tuple(data[i : i + 4]) for i in range(0, len(data), 4)]


def test_an_rgba_image():
    result = decode_png(RGBA_3X2)
    assert result is not None
    width, height, data = result
    assert (width, height) == (3, 2)
    assert pixels(data) == RGBA_3X2_PIXELS


def test_a_palette_image_with_transparency():
    width, height, data = decode_png(PALETTE_2X2)
    assert (width, height) == (2, 2)
    assert pixels(data) == PALETTE_2X2_PIXELS


def test_a_greyscale_image():
    width, height, data = decode_png(GREY_4X1)
    assert (width, height) == (4, 1)
    assert pixels(data) == [
        (0, 0, 0, 255),
        (85, 85, 85, 255),
        (170, 170, 170, 255),
        (255, 255, 255, 255),
    ]


def test_a_sixteen_bit_image_keeps_the_high_byte():
    width, height, data = decode_png(GREY16_2X1)
    assert (width, height) == (2, 1)
    assert pixels(data) == [(0, 0, 0, 255), (255, 255, 255, 255)]


def test_a_one_bit_image():
    width, height, data = decode_png(BILEVEL_8X1)
    assert (width, height) == (8, 1)
    greys = [pixel[0] for pixel in pixels(data)]
    assert greys == [0, 255, 0, 255, 255, 0, 255, 0]


def test_a_larger_rgb_image():
    "Eight rows: the writer uses more than one filter here."
    width, height, data = decode_png(RGB_8X8)
    assert (width, height) == (8, 8)
    assert [pixel[:3] for pixel in pixels(data)] == RGB_8X8_PIXELS
    assert all(pixel[3] == 255 for pixel in pixels(data))


def test_an_interlaced_image_is_refused():
    # Adam7 is not implemented. The header says interlace method one.
    header = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 1)
    body = zlib.compress(bytes(16))
    assert decode_png(_build([(b"IHDR", header), (b"IDAT", body)])) is None


def test_data_that_is_not_a_png_is_refused():
    assert decode_png(b"not a png at all") is None
    assert decode_png(b"") is None


def test_a_png_without_image_data_is_refused():
    header = struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)
    assert decode_png(_build([(b"IHDR", header)])) is None


def test_broken_image_data_is_refused():
    header = struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)
    assert (
        decode_png(_build([(b"IHDR", header), (b"IDAT", b"not zlib")])) is None
    )


def test_an_image_past_the_pixel_bound_is_refused():
    header = struct.pack(">IIBBBBB", 40000, 40000, 8, 6, 0, 0, 0)
    body = zlib.compress(b"\x00" * 16)
    assert decode_png(_build([(b"IHDR", header), (b"IDAT", body)])) is None


# ----------------------------------------------------------------------
# Filters. The images below are built here, so the forward filter is
# written out on its own and does not share code with the decoder.


def _build(chunks):
    "A PNG file from (type, payload) pairs."
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    for kind, payload in chunks:
        out += struct.pack(">I", len(payload))
        out += kind + payload
        out += struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    out += struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    return bytes(out)


def _paeth(left, up, up_left):
    estimate = left + up - up_left
    distances = (
        abs(estimate - left),
        abs(estimate - up),
        abs(estimate - up_left),
    )
    if distances[0] <= distances[1] and distances[0] <= distances[2]:
        return left
    if distances[1] <= distances[2]:
        return up
    return up_left


def _filter_row(filter_type, line, previous, bytes_per_pixel):
    "Apply the forward filter of `filter_type` to one scanline."
    out = bytearray()
    for i, value in enumerate(line):
        left = line[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
        up = previous[i]
        up_left = previous[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
        if filter_type == 0:
            out.append(value)
        elif filter_type == 1:
            out.append((value - left) & 0xFF)
        elif filter_type == 2:
            out.append((value - up) & 0xFF)
        elif filter_type == 3:
            out.append((value - ((left + up) >> 1)) & 0xFF)
        else:
            out.append((value - _paeth(left, up, up_left)) & 0xFF)
    return bytes(out)


def _rgb_png(rows, filter_type):
    "An RGB PNG whose every scanline uses `filter_type`."
    height = len(rows)
    width = len(rows[0]) // 3
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    raw = bytearray()
    previous = bytes(len(rows[0]))
    for line in rows:
        raw.append(filter_type)
        raw += _filter_row(filter_type, line, previous, 3)
        previous = line

    return _build(
        [(b"IHDR", header), (b"IDAT", zlib.compress(bytes(raw)))]
    )


ROWS = [
    bytes([10, 20, 30, 200, 100, 50, 7, 8, 9]),
    bytes([11, 21, 31, 199, 99, 49, 250, 251, 252]),
    bytes([0, 0, 0, 255, 255, 255, 128, 128, 128]),
]


@pytest.mark.parametrize("filter_type", [0, 1, 2, 3, 4])
def test_every_filter_round_trips(filter_type):
    width, height, data = decode_png(_rgb_png(ROWS, filter_type))
    assert (width, height) == (3, 3)
    got = [pixel[:3] for pixel in pixels(data)]
    expected = [
        tuple(row[i : i + 3]) for row in ROWS for i in range(0, len(row), 3)
    ]
    assert got == expected


def test_an_unknown_filter_is_refused():
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    body = zlib.compress(bytes([9, 1, 2, 3]))  # Filter type nine.
    assert decode_png(_build([(b"IHDR", header), (b"IDAT", body)])) is None


def test_truncated_image_data_is_refused():
    header = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    body = zlib.compress(bytes(5))  # One short scanline.
    assert decode_png(_build([(b"IHDR", header), (b"IDAT", body)])) is None
