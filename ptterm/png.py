"""
PNG image decoding.

The kitty graphics protocol carries PNG data, which a terminal that
draws the image itself has to decode. ptterm keeps the bytes as they
arrive, so this decoder only runs when something needs the pixels: the
sixel fallback of pymux, for instance, which re-encodes an image for a
terminal that does not speak the kitty protocol.

The decoder covers what a PNG writer normally produces: bit depths of
1, 2, 4, 8 and 16, all five colour types, the transparency chunk, and
the five filters. Interlaced images (Adam7) are refused.
"""
import struct
import zlib
from typing import List, Tuple

__all__ = [
    "decode_png",
]

SIGNATURE = b"\x89PNG\r\n\x1a\n"

# A runaway image must not take the memory of the server.
MAX_PIXELS = 4 * 1024 * 1024

# Channels per pixel for every colour type.
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _paeth(left: int, up: int, up_left: int) -> int:
    "The Paeth predictor of the PNG filter."
    estimate = left + up - up_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_up_left = abs(estimate - up_left)
    if distance_left <= distance_up and distance_left <= distance_up_left:
        return left
    if distance_up <= distance_up_left:
        return up
    return up_left


def _chunks(data: bytes):
    "Yield the (type, payload) pairs of a PNG file."
    offset = len(SIGNATURE)
    total = len(data)
    while offset + 8 <= total:
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end > total:
            return
        yield kind, data[start:end]
        offset = end + 4  # Step over the CRC.


def _unfilter(raw: bytes, height: int, stride: int, bytes_per_pixel: int) -> bytearray:
    "Undo the per scanline filters. Returns the raw samples."
    out = bytearray(height * stride)
    previous = bytearray(stride)
    position = 0

    for row in range(height):
        if position + 1 + stride > len(raw):
            raise ValueError("truncated image data")
        filter_type = raw[position]
        line = bytearray(raw[position + 1 : position + 1 + stride])
        position += 1 + stride

        if filter_type == 1:  # Sub
            for i in range(bytes_per_pixel, stride):
                line[i] = (line[i] + line[i - bytes_per_pixel]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                up_left = (
                    previous[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                )
                line[i] = (line[i] + _paeth(left, previous[i], up_left)) & 0xFF
        elif filter_type != 0:
            raise ValueError("unknown filter type %i" % filter_type)

        out[row * stride : (row + 1) * stride] = line
        previous = line

    return out


def _samples(line: bytes, width: int, depth: int, channels: int) -> List[int]:
    """
    The samples of one scanline, scaled to bytes.

    Depths below eight pack several samples into one byte; a depth of
    sixteen keeps only the high byte of each sample.
    """
    count = width * channels

    if depth == 8:
        return list(line[:count])

    if depth == 16:
        return list(line[0 : count * 2 : 2])

    # 1, 2 or 4 bits per sample.
    maximum = (1 << depth) - 1
    per_byte = 8 // depth
    values = []
    for index in range(count):
        byte = line[index // per_byte]
        shift = 8 - depth * (index % per_byte + 1)
        value = (byte >> shift) & maximum
        values.append(value)
    return values


def decode_png(data: bytes) -> Tuple[int, int, bytes] | None:
    """
    Decode a PNG image. Returns (width, height, RGBA bytes), or None
    when the data is not a PNG that this decoder handles.
    """
    if not data.startswith(SIGNATURE):
        return None

    width = height = 0
    depth = colour_type = interlace = 0
    palette: List[Tuple[int, int, int]] = []
    transparency = b""
    compressed = bytearray()
    seen_header = False

    for kind, payload in _chunks(data):
        if kind == b"IHDR":
            if len(payload) < 13:
                return None
            width, height, depth, colour_type, _method, _filter, interlace = (
                struct.unpack(">IIBBBBB", payload[:13])
            )
            seen_header = True
        elif kind == b"PLTE":
            palette = [
                (payload[i], payload[i + 1], payload[i + 2])
                for i in range(0, len(payload) - 2, 3)
            ]
        elif kind == b"tRNS":
            transparency = payload
        elif kind == b"IDAT":
            compressed += payload
        elif kind == b"IEND":
            break

    if not seen_header or interlace != 0:
        return None
    if colour_type not in _CHANNELS or depth not in (1, 2, 4, 8, 16):
        return None
    if colour_type in (2, 4, 6) and depth < 8:
        return None  # Not a valid combination.
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        return None
    if not compressed:
        return None

    channels = _CHANNELS[colour_type]
    bits_per_pixel = depth * channels
    stride = (width * bits_per_pixel + 7) // 8
    bytes_per_pixel = max(1, bits_per_pixel // 8)

    try:
        raw = zlib.decompress(bytes(compressed))
        samples = _unfilter(raw, height, stride, bytes_per_pixel)
    except (zlib.error, ValueError):
        return None

    scale = 255 // ((1 << depth) - 1) if depth < 8 else 1

    out = bytearray(width * height * 4)
    for row in range(height):
        line = _samples(
            samples[row * stride : (row + 1) * stride], width, depth, channels
        )
        base = row * width * 4

        for column in range(width):
            offset = base + column * 4
            index = column * channels

            if colour_type == 0:  # Greyscale.
                grey = line[index] * scale
                alpha = 255
                if len(transparency) >= 2:
                    (value,) = struct.unpack(">H", transparency[:2])
                    if line[index] == (value if depth == 16 else value & 0xFF):
                        alpha = 0
                out[offset : offset + 4] = bytes((grey, grey, grey, alpha))

            elif colour_type == 2:  # RGB.
                red, green, blue = line[index], line[index + 1], line[index + 2]
                alpha = 255
                if len(transparency) >= 6:
                    keys = struct.unpack(">HHH", transparency[:6])
                    if depth == 16:
                        match = (red, green, blue) == keys
                    else:
                        match = (red, green, blue) == tuple(
                            key & 0xFF for key in keys
                        )
                    if match:
                        alpha = 0
                out[offset : offset + 4] = bytes((red, green, blue, alpha))

            elif colour_type == 3:  # Palette.
                entry = line[index]
                if entry < len(palette):
                    red, green, blue = palette[entry]
                else:
                    red = green = blue = 0
                alpha = transparency[entry] if entry < len(transparency) else 255
                out[offset : offset + 4] = bytes((red, green, blue, alpha))

            elif colour_type == 4:  # Greyscale with alpha.
                grey = line[index] * scale
                out[offset : offset + 4] = bytes(
                    (grey, grey, grey, line[index + 1] * scale)
                )

            else:  # Colour type 6: RGBA.
                out[offset : offset + 4] = bytes(
                    (
                        line[index],
                        line[index + 1],
                        line[index + 2],
                        line[index + 3],
                    )
                )

    return (width, height, bytes(out))
