"""
Kitty graphics protocol state for a terminal pane.

Implements the parts of the terminal side of the protocol that do not
require a pixel renderer: parsing the control data of graphics
commands, storing transmitted images and their placements, and
reserving the cells that a placement covers. The actual pixel output
is up to the application that renders the screen (for pymux: the
multiplexer, which re-emits images to clients that support the
protocol).

Not implemented yet: animation (actions ``f``, ``a`` and ``c``),
scrolling placements along with the text, the file- and shared-memory
transmission media, and z-index handling beyond storing the value.
"""
import base64
import zlib
from typing import Dict, List, Optional, Tuple

__all__ = [
    "ASSUMED_CELL_HEIGHT",
    "ASSUMED_CELL_WIDTH",
    "GraphicsError",
    "GraphicsImage",
    "GraphicsPlacement",
    "GraphicsState",
    "parse_control_data",
]


# Cell size in pixels assumed when a placement does not specify its
# size in cells. (A terminal that renders text only does not know
# pixel sizes; applications that care ask with "CSI 16 t".)
ASSUMED_CELL_WIDTH = 10
ASSUMED_CELL_HEIGHT = 20

# Memory guards. A runaway program must not take the whole machine
# down: refuse payloads and image storage beyond these limits, the same
# way kitty bounds its image storage.
MAX_PENDING_PAYLOAD = 256 * 1024 * 1024  # base64 string of one transmission
MAX_TOTAL_IMAGE_DATA = 1024 * 1024 * 1024  # decoded bytes of all images

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class GraphicsError(Exception):
    """
    A graphics command failed. The code becomes the response prefix
    ("EINVAL", "ENOENT", ...).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GraphicsImage:
    "A transmitted image."

    __slots__ = ("format", "width", "height", "data", "number")

    def __init__(
        self, format: int, width: int, height: int, data: bytes, number: int = 0
    ) -> None:
        self.format = format  # 24 (RGB), 32 (RGBA) or 100 (PNG)
        self.width = width  # in pixels
        self.height = height  # in pixels
        self.data = data
        self.number = number  # image number ("I" key), if any


class GraphicsPlacement:
    "A placement of an image on the screen. Coordinates are cells."

    __slots__ = (
        "image_id",
        "placement_id",
        "x",
        "y",
        "columns",
        "rows",
        "z",
        "virtual",
    )

    def __init__(
        self,
        image_id: int,
        placement_id: int,
        x: int,
        y: int,
        columns: int,
        rows: int,
        z: int = 0,
        virtual: bool = False,
    ) -> None:
        self.image_id = image_id
        self.placement_id = placement_id
        self.x = x
        self.y = y
        self.columns = columns
        self.rows = rows
        self.z = z
        self.virtual = virtual  # "U=1": no cells are occupied


def parse_control_data(data: str) -> Tuple[Dict[str, str], str]:
    """
    Split a graphics command into its control data keys and the base64
    payload. ("a=T,f=24;<payload>".)
    """
    if ";" in data:
        control, payload = data.split(";", 1)
    else:
        control, payload = data, ""

    keys: Dict[str, str] = {}
    for part in control.split(","):
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
        else:
            key, value = part, ""
        keys[key] = value
    return keys, payload


def _png_size(data: bytes) -> Tuple[int, int]:
    "Read the width and height from the PNG IHDR chunk."
    if data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR" or len(data) < 24:
        raise GraphicsError("EINVAL", "invalid PNG data")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        raise GraphicsError("EINVAL", "invalid PNG dimensions")
    return width, height


class GraphicsState:
    """
    The images and placements of one screen. (The main and the
    alternate screen each have their own instance; see
    `BetterScreen.swap_variables`.)
    """

    def __init__(self) -> None:
        self.images_by_id: Dict[int, GraphicsImage] = {}
        # The newest image for every image number ("I" key).
        self.newest_by_number: Dict[int, GraphicsImage] = {}
        self.placements: List[GraphicsPlacement] = []
        self.next_image_id = 1
        # An in-flight chunked transmission: (keys, payload-so-far).
        self._pending: Optional[Tuple[Dict[str, str], str]] = None

    # ------------------------------------------------------------------

    def handle(self, data: str, screen) -> Optional[Tuple[str, bool]]:
        """
        Handle a graphics command (the payload of the APC sequence,
        without the leading "G"). Returns the response body (including
        the "i=...;" prefix) and whether it reports success, or None
        when nothing should be sent to the process.

        Like kitty, only commands that carry an image id ("i") or an
        image number ("I") get a response at all.
        """
        keys, payload = parse_control_data(data)
        action = keys.get("a", "t")

        try:
            if action == "t":
                result = self._transmit(keys, payload, store=True)
            elif action == "T":
                result = self._transmit_and_display(keys, payload, screen)
            elif action == "q":
                result = self._transmit(keys, payload, store=False)
            elif action == "p":
                result = self._put(keys, screen)
            elif action == "d":
                result = self._delete(keys, screen)
            else:
                # Animation and composition are not implemented.
                raise GraphicsError(
                    "EINVAL", "unsupported action: %r" % action
                )
        except GraphicsError as exc:
            result = (self._prefix(keys) + exc.code + ":" + exc.args[0], False)
        except ValueError:
            result = (
                self._prefix(keys) + "EINVAL:invalid integer value",
                False,
            )

        if result is None:
            return None
        response, is_ok = result[0], result[1]
        quiet = keys.get("q", "0")
        if not (keys.get("i") or keys.get("I")):
            return None  # Nothing to address a response to.
        if is_ok and quiet in ("1", "2"):
            return None  # Suppress OK responses.
        if not is_ok and quiet == "2":
            return None  # Suppress error responses.
        return (response, is_ok)

    @staticmethod
    def _prefix(keys: Dict[str, str]) -> str:
        parts = []
        if keys.get("i"):
            parts.append("i=%s" % keys["i"])
        if keys.get("I"):
            parts.append("I=%s" % keys["I"])
        if keys.get("p"):
            parts.append("p=%s" % keys["p"])
        return ",".join(parts) + ";" if parts else ""

    @staticmethod
    def _int(keys: Dict[str, str], key: str, default: int = 0) -> int:
        value = keys.get(key)
        if not value:
            return default
        return int(value)

    # ------------------------------------------------------------------
    # Transmission.

    def _transmit(
        self, keys: Dict[str, str], payload: str, store: bool
    ) -> Optional[Tuple[str, bool, Optional[int]]]:
        """
        Handle the 't' and 'q' actions. Returns the response, whether
        it is a success, and the id of the stored image (None for the
        'q' action and for chunked transmissions still in flight).
        """
        if "i" in keys and "I" in keys:
            raise GraphicsError("EINVAL", "both image id and image number given")

        medium = keys.get("t", "d")
        if medium != "d":
            raise GraphicsError(
                "EINVAL", "unsupported transmission medium: %r" % medium
            )

        # Chunked transmissions are buffered until the final chunk.
        # (Like kitty, the keys of the first message govern; later
        # messages only add payload.)
        if keys.get("m", "0") == "1":
            if self._pending is None:
                if len(payload) > MAX_PENDING_PAYLOAD:
                    raise GraphicsError("EINVAL", "too much data")
                self._pending = (dict(keys), payload)
            else:
                if len(self._pending[1]) + len(payload) > MAX_PENDING_PAYLOAD:
                    self._pending = None
                    raise GraphicsError("EINVAL", "too much data")
                self._pending = (self._pending[0], self._pending[1] + payload)
            return None

        if self._pending is not None:
            # Final chunk of a chunked transmission.
            keys, payload = self._pending
            self._pending = None

        image_id: Optional[int] = None
        try:
            try:
                data = base64.b64decode(payload, validate=True)
            except Exception:
                raise GraphicsError("EINVAL", "invalid base64 data")

            fmt = self._int(keys, "f", 32)
            compression = keys.get("o", "")
            if fmt == 100:
                if compression:
                    raise GraphicsError("EINVAL", "PNG data cannot be compressed")
                width, height = _png_size(data)
            elif fmt in (24, 32):
                if compression == "z":
                    try:
                        data = zlib.decompress(data)
                    except Exception:
                        raise GraphicsError("EINVAL", "invalid compressed data")
                elif compression:
                    raise GraphicsError(
                        "EINVAL", "unknown compression: %r" % compression
                    )
                width = self._int(keys, "s")
                height = self._int(keys, "v")
                if width <= 0 or height <= 0:
                    raise GraphicsError("EINVAL", "width and height required")
                expected = width * height * (3 if fmt == 24 else 4)
                if len(data) != expected:
                    raise GraphicsError(
                        "EINVAL", "data size does not match width and height"
                    )
            else:
                raise GraphicsError("EINVAL", "unknown format: %i" % fmt)

            image = GraphicsImage(
                fmt, width, height, data, number=self._int(keys, "I")
            )
            if store and self._total_image_data() + len(data) > MAX_TOTAL_IMAGE_DATA:
                raise GraphicsError("EINVAL", "image storage quota exceeded")
            if store:
                if "i" in keys:
                    image_id = int(keys["i"])
                    if image_id <= 0:
                        raise GraphicsError("EINVAL", "invalid image id")
                    # Re-transmitting an id replaces the image and all
                    # its placements. The new data is not displayed
                    # until a placement is created for it.
                    self.delete_image_data(image_id)
                    self.images_by_id[image_id] = image
                    if image.number:
                        self.newest_by_number[image.number] = image
                elif "I" in keys:
                    # An image number always creates a new image; the
                    # terminal assigns the id and reports it.
                    image_id = self._new_image_id()
                    self.images_by_id[image_id] = image
                    if image.number:
                        self.newest_by_number[image.number] = image
                else:
                    # Without id or number, the image is stored in the
                    # id-0 slot and cannot be referenced later.
                    self.delete_image_data(0)
                    self.images_by_id[0] = image
        except GraphicsError:
            if self._pending_response_possible(keys):
                raise
            return None

        if not store:
            # The 'q' action: load, but don't store.
            if "i" in keys or "I" in keys:
                return (self._prefix(keys) + "OK", True, None)
            return None

        if "i" in keys:
            return (self._prefix(keys) + "OK", True, image_id)
        if "I" in keys:
            # Report the assigned id together with the image number.
            return ("i=%i,I=%i;OK" % (image_id, image.number), True, image_id)
        return None  # No response for id-less transmissions.

    @staticmethod
    def _pending_response_possible(keys: Dict[str, str]) -> bool:
        return bool(keys.get("i") or keys.get("I"))

    def _transmit_and_display(
        self, keys: Dict[str, str], payload: str, screen
    ) -> Optional[Tuple[str, bool]]:
        "Handle the 'T' action: transmit, then place at the cursor."
        result = self._transmit(keys, payload, store=True)
        if result is None:
            return None
        _response, _is_ok, image_id = result
        if image_id is None:
            return None
        self._put(keys, screen, image_id=image_id)
        return (_response, True)

    # ------------------------------------------------------------------
    # Placement.

    def _lookup_image(self, keys: Dict[str, str]) -> Tuple[int, GraphicsImage]:
        if "i" in keys and "I" in keys:
            raise GraphicsError("EINVAL", "both image id and image number given")
        if "i" in keys:
            image_id = int(keys["i"])
            image = self.images_by_id.get(image_id)
        elif "I" in keys:
            number = int(keys["I"])
            image = self.newest_by_number.get(number)
            image_id = 0
            for known_id, known in self.images_by_id.items():
                if known is image:
                    image_id = known_id
                    break
        else:
            raise GraphicsError("EINVAL", "image id or image number required")

        if image is None:
            raise GraphicsError("ENOENT", "no such image")
        return image_id, image

    @staticmethod
    def _put_prefix(keys: Dict[str, str], image_id: int) -> str:
        parts = ["i=%i" % image_id]
        if keys.get("p"):
            parts.append("p=%s" % keys["p"])
        return ",".join(parts) + ";"

    def _put(
        self, keys: Dict[str, str], screen, image_id: Optional[int] = None
    ) -> Tuple[str, bool]:
        if image_id is None:
            image_id, _image = self._lookup_image(keys)
        else:
            _image = self.images_by_id.get(image_id)
            if _image is None:
                raise GraphicsError("ENOENT", "no such image")

        placement_id = self._int(keys, "p")
        columns = self._int(keys, "c")
        rows = self._int(keys, "r")

        if columns <= 0 and _image.width:
            columns = -(-_image.width // ASSUMED_CELL_WIDTH)
        if rows <= 0 and _image.height:
            rows = -(-_image.height // ASSUMED_CELL_HEIGHT)
        if columns <= 0 or rows <= 0:
            raise GraphicsError("EINVAL", "invalid placement size")

        cursor = screen.pt_cursor_position
        x = cursor.x
        y = cursor.y
        z = self._int(keys, "z")
        virtual = self._int(keys, "U") == 1

        # A placement id replaces an earlier placement of the same
        # image with the same id.
        if placement_id:
            for existing in list(self.placements):
                if (
                    existing.image_id == image_id
                    and existing.placement_id == placement_id
                ):
                    self._clear_placement_cells(screen, existing)
                    self.placements.remove(existing)

        placement = GraphicsPlacement(
            image_id, placement_id, x, y, columns, rows, z, virtual
        )
        self.placements.append(placement)

        if not virtual and z >= 0:
            # Reserve the covered cells. (Images with a negative
            # z-index are drawn below the text.)
            self._clear_cells(screen, x, y, columns, rows)

        if not virtual and keys.get("C", "0") != "1":
            # Move the cursor to the cell right after the image, like
            # kitty does: same row counting, clamped by the screen.
            cursor.x += columns
            if rows:
                cursor.y += rows - 1
            screen.max_y = max(screen.max_y, cursor.y)
            screen.ensure_bounds()

        response = self._put_prefix(keys, image_id) + "OK"
        return (response, True)

    # ------------------------------------------------------------------
    # Deletion.

    def _delete(
        self, keys: Dict[str, str], screen
    ) -> Optional[Tuple[str, bool]]:
        specifier = keys.get("d", "a")
        lower = specifier.lower()
        free_data = specifier.isupper()

        if lower == "f":
            # Animation frames are not implemented.
            return None

        if lower == "a":
            targets = list(self.placements)
        elif lower == "i":
            image_id = self._int(keys, "i")
            placement_id = self._int(keys, "p")
            targets = [
                pl
                for pl in self.placements
                if pl.image_id == image_id
                and (not placement_id or pl.placement_id == placement_id)
            ]
        elif lower == "n":
            number = self._int(keys, "I")
            image = self.newest_by_number.get(number)
            targets = [
                pl for pl in self.placements if image is not None and
                pl.image_id in self._ids_of(image)
            ]
        elif lower == "c":
            cursor = screen.pt_cursor_position
            targets = [
                pl
                for pl in self.placements
                if pl.x <= cursor.x < pl.x + pl.columns
                and pl.y <= cursor.y < pl.y + pl.rows
            ]
        elif lower in ("p", "q"):
            x = self._int(keys, "x") - 1
            y = self._int(keys, "y") - 1
            targets = [
                pl
                for pl in self.placements
                if pl.x <= x < pl.x + pl.columns
                and pl.y <= y < pl.y + pl.rows
            ]
            if lower == "q":
                z = self._int(keys, "z")
                targets = [pl for pl in targets if pl.z == z]
        elif lower == "r":
            low = self._int(keys, "x")
            high = self._int(keys, "y")
            image_ids = [
                image_id
                for image_id in self.images_by_id
                if low <= image_id <= high
            ]
            targets = [pl for pl in self.placements if pl.image_id in image_ids]
        else:
            return None  # Unknown specifier: ignore.

        for placement in targets:
            self._clear_placement_cells(screen, placement)
            self.placements.remove(placement)

        if free_data:
            for image_id in list(self.images_by_id):
                if not any(pl.image_id == image_id for pl in self.placements):
                    self.delete_image_data(image_id)

        return None  # Deletes are not acknowledged.

    def _ids_of(self, image: GraphicsImage) -> List[int]:
        return [
            image_id
            for image_id, known in self.images_by_id.items()
            if known is image
        ]

    def _new_image_id(self) -> int:
        "An id that no image uses. (For images that the terminal names.)"
        while self.next_image_id in self.images_by_id:
            self.next_image_id += 1
        image_id = self.next_image_id
        self.next_image_id += 1
        return image_id

    def _total_image_data(self) -> int:
        return sum(len(image.data) for image in self.images_by_id.values())

    def delete_image_data(self, image_id: int) -> None:
        """
        Remove an image and its placements. (Re-transmitting an image
        id must delete the old placements; the new data is not
        displayed until a placement is created.)
        """
        self.placements = [
            pl for pl in self.placements if pl.image_id != image_id
        ]
        image = self.images_by_id.pop(image_id, None)
        if image is not None:
            for number, known in list(self.newest_by_number.items()):
                if known is image:
                    del self.newest_by_number[number]

    # ------------------------------------------------------------------
    # Sixel.

    def add_sixel(
        self, width: int, height: int, data: bytes, screen
    ) -> Optional[int]:
        """
        Store a decoded sixel image and place it at the cursor.

        Sixel has no image ids: every image is new, and the terminal
        names it. The cursor ends at the left of the row below the
        image, the way xterm leaves it.
        """
        if self._total_image_data() + len(data) > MAX_TOTAL_IMAGE_DATA:
            return None

        image_id = self._new_image_id()
        self.images_by_id[image_id] = GraphicsImage(32, width, height, data)

        columns = max(1, -(-width // ASSUMED_CELL_WIDTH))
        rows = max(1, -(-height // ASSUMED_CELL_HEIGHT))

        cursor = screen.pt_cursor_position
        self.placements.append(
            GraphicsPlacement(image_id, 0, cursor.x, cursor.y, columns, rows)
        )
        self._clear_cells(screen, cursor.x, cursor.y, columns, rows)

        cursor.x = 0
        cursor.y += rows
        screen.max_y = max(screen.max_y, cursor.y)
        screen.ensure_bounds()
        return image_id

    # ------------------------------------------------------------------
    # Screen interaction.

    def remove_all_placements(self) -> None:
        "Remove every placement. (Image data is kept.)"
        self.placements = []

    def scroll(self, first_row: int, last_row: int, count: int) -> None:
        """
        Follow a scroll of the region from `first_row` to `last_row`
        (absolute rows of the data buffer, both inclusive). A positive
        `count` moves the content up by that many rows.

        Placements outside the region keep their position. Placements
        that the scroll would tear or move out of the region are
        removed, the same way kitty drops an image that scrolls out.
        """
        kept: List[GraphicsPlacement] = []
        for placement in self.placements:
            top = placement.y
            bottom = placement.y + placement.rows - 1

            if bottom < first_row or top > last_row:
                kept.append(placement)  # Outside the region.
                continue
            if top < first_row or bottom > last_row:
                continue  # Crosses the edge of the region: torn.

            placement.y -= count
            if (
                placement.y >= first_row
                and placement.y + placement.rows - 1 <= last_row
            ):
                kept.append(placement)
        self.placements = kept

    def prune_above(self, row: int) -> None:
        "Remove placements that end above `row`. (History was trimmed.)"
        self.placements = [
            placement
            for placement in self.placements
            if placement.y + placement.rows > row
        ]

    def prune_below(self, row: int) -> None:
        "Remove placements that start below `row`. (Lines were dropped.)"
        self.placements = [
            placement for placement in self.placements if placement.y <= row
        ]

    def clear(self) -> None:
        "Forget all images and placements. (Full terminal reset.)"
        self.images_by_id = {}
        self.newest_by_number = {}
        self.placements = []
        self._pending = None

    # Cell helpers. These touch the data buffer of the surrounding
    # BetterScreen. Deleting a cell key makes the cell blank, the same
    # way that BetterScreen erases text.

    def _clear_cells(self, screen, x: int, y: int, columns: int, rows: int) -> None:
        data_buffer = screen.pt_screen.data_buffer
        for row in range(y, y + rows):
            line = data_buffer.get(row)
            if line is None:
                continue
            for column in range(x, x + columns):
                if column in line:
                    del line[column]

    def _clear_placement_cells(self, screen, placement: GraphicsPlacement) -> None:
        if not placement.virtual and placement.z >= 0:
            self._clear_cells(
                screen,
                placement.x,
                placement.y,
                placement.columns,
                placement.rows,
            )
