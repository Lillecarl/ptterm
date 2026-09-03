"""
Tests for the kitty graphics protocol state in BetterScreen.
"""
import base64
import zlib

from ptterm.screen import BetterScreen
from ptterm.stream import BetterStream


def make_screen():
    "Return (screen, stream, responses)."
    responses = []
    screen = BetterScreen(24, 80, write_process_input=responses.append)
    stream = BetterStream(screen)
    stream.attach(screen)
    return screen, stream, responses


def rgb_image(width, height):
    "The bytes of a width x height RGB image (one red pixel pattern)."
    return bytes([(x * 7) % 256 for x in range(width * height * 3)])


def apc(command, payload=""):
    "The full APC sequence for a graphics command."
    return "\x1b_G" + command + (";" + payload if payload else "") + "\x1b\\"


def row_text(screen, row=0, width=40):
    return "".join(screen.pt_screen.data_buffer[row][i].char for i in range(width))


def test_transmit_and_display_moves_cursor_and_clears_cells():
    screen, stream, responses = make_screen()
    stream.feed("abc")
    data = rgb_image(4, 2)
    # 4 pixels wide -> 1 cell (assumed cell width 10), 2 pixels -> 1 cell.
    stream.feed(apc("a=T,f=24,s=4,v=2,i=10", base64.b64encode(data).decode()))
    assert responses == ["\x1b_Gi=10;OK\x1b\\"]
    assert len(screen.graphics.placements) == 1
    placement = screen.graphics.placements[0]
    assert (placement.image_id, placement.x, placement.y) == (10, 3, 0)
    assert (placement.columns, placement.rows) == (1, 1)
    # The covered cell is blank, the text before it is untouched.
    assert row_text(screen).startswith("abc ")
    # The cursor moved right after the image.
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (4, 0)


def test_transmit_rgba_is_the_default_format():
    screen, stream, responses = make_screen()
    data = rgb_image(10, 20) + b"\x00" * (10 * 20)
    stream.feed(apc("a=t,s=10,v=20,i=11", base64.b64encode(data).decode()))
    assert responses == ["\x1b_Gi=11;OK\x1b\\"]
    image = screen.graphics.images_by_id[11]
    assert (image.width, image.height, image.format) == (10, 20, 32)


def test_transmit_without_id_gets_no_response():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    stream.feed(apc("a=t,f=24,s=4,v=2", base64.b64encode(data).decode()))
    assert responses == []
    assert 0 in screen.graphics.images_by_id


def test_image_number_assigns_an_id():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    encoded = base64.b64encode(data).decode()
    stream.feed(apc("a=t,f=24,s=4,v=2,I=5", encoded))
    stream.feed(apc("a=t,f=24,s=4,v=2,I=5", encoded))
    assert responses == ["\x1b_Gi=1,I=5;OK\x1b\\", "\x1b_Gi=2,I=5;OK\x1b\\"]
    # The newest image for the number is the second one.
    assert screen.graphics.newest_by_number[5].data is not None
    put = apc("a=p,I=5,c=2,r=2")
    stream.feed(put)
    assert responses[-1] == "\x1b_Gi=2;OK\x1b\\"


def test_retransmitting_an_id_deletes_its_placements():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    encoded = base64.b64encode(data).decode()
    stream.feed(apc("a=t,f=24,s=4,v=2,i=10", encoded))
    stream.feed(apc("a=p,i=10,c=2,r=2"))
    assert len(screen.graphics.placements) == 1
    stream.feed(apc("a=t,f=24,s=4,v=2,i=10", encoded))
    assert screen.graphics.placements == []


def test_chunked_transmission():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    encoded = base64.b64encode(data).decode()
    half = len(encoded) // 2
    stream.feed(apc("a=t,f=24,s=4,v=2,i=12,m=1", encoded[:half]))
    assert responses == []
    assert screen.graphics.images_by_id.get(12) is None
    stream.feed(apc("a=t,f=24,s=4,v=2,i=12,m=1", encoded[half:]))
    assert responses == []
    stream.feed(apc("a=t,f=24,s=4,v=2,i=12"))
    assert responses == ["\x1b_Gi=12;OK\x1b\\"]
    assert 12 in screen.graphics.images_by_id


def test_compressed_transmission():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    compressed = zlib.compress(data)
    stream.feed(
        apc("a=t,f=24,s=4,v=2,i=13,o=z", base64.b64encode(compressed).decode())
    )
    assert responses == ["\x1b_Gi=13;OK\x1b\\"]
    assert screen.graphics.images_by_id[13].data == data


def test_png_transmission():
    screen, stream, responses = make_screen()
    ihdr = b"IHDR" + (10).to_bytes(4, "big") + (20).to_bytes(4, "big") + b"\x08\x06"
    png = b"\x89PNG\r\n\x1a\n" + len(ihdr).to_bytes(4, "big") + ihdr + b"..."
    stream.feed(apc("a=t,f=100,i=14", base64.b64encode(png).decode()))
    assert responses == ["\x1b_Gi=14;OK\x1b\\"]
    image = screen.graphics.images_by_id[14]
    assert (image.width, image.height, image.format) == (10, 20, 100)


def test_data_size_mismatch_is_an_error():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)[:-1]
    stream.feed(apc("a=t,f=24,s=4,v=2,i=15", base64.b64encode(data).decode()))
    assert len(responses) == 1
    assert responses[0].startswith("\x1b_Gi=15;EINVAL:")
    assert 15 not in screen.graphics.images_by_id


def test_query_action_does_not_store():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    stream.feed(apc("a=q,f=24,s=4,v=2,i=16", base64.b64encode(data).decode()))
    assert responses == ["\x1b_Gi=16;OK\x1b\\"]
    assert screen.graphics.images_by_id == {}


def test_both_id_and_number_is_an_error():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    stream.feed(
        apc("a=t,f=24,s=4,v=2,i=17,I=7", base64.b64encode(data).decode())
    )
    assert responses[0].startswith("\x1b_Gi=17,I=7;EINVAL:")


def test_put_of_unknown_image_is_enoent():
    screen, stream, responses = make_screen()
    stream.feed(apc("a=p,i=999,c=1,r=1"))
    assert responses[0].startswith("\x1b_Gi=999;ENOENT:")


def test_quiet_modes():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    encoded = base64.b64encode(data).decode()
    # q=1 suppresses OK responses.
    stream.feed(apc("a=t,f=24,s=4,v=2,i=18,q=1", encoded))
    assert responses == []
    # ... but errors still come through.
    stream.feed(apc("a=t,f=24,s=4,v=2,i=19,q=1", base64.b64encode(b"xx").decode()))
    assert responses and responses[-1].startswith("\x1b_Gi=19;EINVAL:")
    # q=2 suppresses everything.
    stream.feed(apc("a=t,f=24,s=4,v=2,i=20,q=2", encoded))
    stream.feed(apc("a=t,f=24,s=4,v=2,i=21,q=2", base64.b64encode(b"xx").decode()))
    assert len(responses) == 1  # Only the earlier EINVAL.


def test_placement_id_replaces_placement():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    encoded = base64.b64encode(data).decode()
    stream.feed(apc("a=t,f=24,s=4,v=2,i=22", encoded))
    stream.feed(apc("a=p,i=22,c=1,r=1,p=7"))
    stream.feed(apc("a=p,i=22,c=1,r=1,p=7"))
    stream.feed(apc("a=p,i=22,c=1,r=1"))
    assert len(screen.graphics.placements) == 2
    assert responses[-1] == "\x1b_Gi=22;OK\x1b\\"
    replaced = [pl for pl in screen.graphics.placements if pl.placement_id == 7]
    assert len(replaced) == 1


def test_cursor_movement_policy():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    encoded = base64.b64encode(data).decode()
    stream.feed(apc("a=t,f=24,s=4,v=2,i=23", encoded))
    # Default: the cursor moves right after the image.
    stream.feed(apc("a=p,i=23,c=2,r=3"))
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (2, 2)
    # C=1: the cursor does not move.
    stream.feed(apc("a=p,i=23,c=2,r=3,C=1"))
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (2, 2)


def test_delete_all_placements():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    encoded = base64.b64encode(data).decode()
    stream.feed(apc("a=t,f=24,s=4,v=2,i=24", encoded))
    stream.feed(apc("a=p,i=24,c=1,r=1"))
    stream.feed("text")
    stream.feed(apc("a=d"))
    assert screen.graphics.placements == []
    # The image data is kept for lowercase deletes.
    assert 24 in screen.graphics.images_by_id


def test_delete_by_id_with_data():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    encoded = base64.b64encode(data).decode()
    stream.feed(apc("a=t,f=24,s=4,v=2,i=25", encoded))
    stream.feed(apc("a=p,i=25,c=1,r=1"))
    stream.feed(apc("a=d,d=I,i=25"))
    assert screen.graphics.placements == []
    assert 25 not in screen.graphics.images_by_id


def test_clear_screen_removes_placements():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    encoded = base64.b64encode(data).decode()
    stream.feed(apc("a=t,f=24,s=4,v=2,i=26", encoded))
    stream.feed(apc("a=p,i=26,c=1,r=1"))
    stream.feed("\x1b[2J")
    assert screen.graphics.placements == []
    assert 26 in screen.graphics.images_by_id


def test_reset_clears_everything():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    encoded = base64.b64encode(data).decode()
    stream.feed(apc("a=t,f=24,s=4,v=2,i=27", encoded))
    screen.reset()
    assert screen.graphics.images_by_id == {}
    assert screen.graphics.placements == []


def test_alternate_screen_has_independent_graphics():
    screen, stream, responses = make_screen()
    data = rgb_image(4, 2)
    encoded = base64.b64encode(data).decode()
    stream.feed(apc("a=t,f=24,s=4,v=2,i=28", encoded))
    stream.feed(apc("a=p,i=28,c=1,r=1"))
    stream.feed("\x1b[?1049h")
    # Fresh state on the alternate screen.
    assert screen.graphics.images_by_id == {}
    assert screen.graphics.placements == []
    # And the main screen state is restored when leaving.
    stream.feed("\x1b[?1049l")
    assert 28 in screen.graphics.images_by_id
    assert len(screen.graphics.placements) == 1


def test_non_graphics_apc_is_ignored():
    screen, stream, responses = make_screen()
    stream.feed("\x1b_bogus-protocol\x1b\\")
    assert responses == []
    assert screen.graphics.placements == []


def test_unsupported_actions_error():
    screen, stream, responses = make_screen()
    stream.feed(apc("a=f,i=30"))
    assert responses[0].startswith("\x1b_Gi=30;EINVAL:")


# ----------------------------------------------------------------------
# Scrolling.


def place(screen, stream, image_id, rows=1, columns=1):
    "Transmit a 1x1 image and place it at the cursor."
    data = base64.b64encode(rgb_image(1, 1)).decode()
    stream.feed(
        apc("a=T,f=24,s=1,v=1,c=%i,r=%i,C=1,i=%i" % (columns, rows, image_id), data)
    )


def placement_rows(screen):
    return sorted(
        (placement.image_id, placement.y) for placement in screen.graphics.placements
    )


def test_plain_scrolling_keeps_placement_rows():
    # Without margins the data buffer keeps growing, so absolute rows
    # stay valid and placements need no adjustment.
    screen, stream, _ = make_screen()
    place(screen, stream, 1)
    for _ in range(30):
        stream.feed("\r\n")
    assert placement_rows(screen) == [(1, 0)]


def test_scroll_region_moves_placements_up():
    screen, stream, _ = make_screen()
    stream.feed("\x1b[1;10r")  # Margins: rows 0..9.
    stream.feed("\x1b[5;1H")  # Row 4.
    place(screen, stream, 1)
    stream.feed("\x1b[10;1H")  # Bottom margin; the next linefeed scrolls.
    stream.feed("\n")
    assert placement_rows(screen) == [(1, 3)]


def test_placement_scrolled_out_of_the_region_is_dropped():
    screen, stream, _ = make_screen()
    stream.feed("\x1b[1;10r")
    stream.feed("\x1b[1;1H")  # Top of the region.
    place(screen, stream, 1)
    stream.feed("\x1b[10;1H")
    stream.feed("\n")
    assert placement_rows(screen) == []


def test_reverse_index_moves_placements_down():
    screen, stream, _ = make_screen()
    stream.feed("\x1b[1;10r")
    stream.feed("\x1b[5;1H")
    place(screen, stream, 1)
    stream.feed("\x1b[1;1H")  # Top of the region.
    stream.feed("\x1bM")  # Reverse index: the region scrolls down.
    assert placement_rows(screen) == [(1, 5)]


def test_delete_lines_moves_placements_up():
    screen, stream, _ = make_screen()
    stream.feed("\x1b[6;1H")  # Row 5.
    place(screen, stream, 1)
    stream.feed("\x1b[3;1H")  # Row 2.
    stream.feed("\x1b[2M")  # Delete two lines.
    assert placement_rows(screen) == [(1, 3)]


def test_insert_lines_moves_placements_down():
    screen, stream, _ = make_screen()
    stream.feed("\x1b[6;1H")
    place(screen, stream, 1)
    stream.feed("\x1b[3;1H")
    stream.feed("\x1b[2L")  # Insert two lines.
    assert placement_rows(screen) == [(1, 7)]


def test_a_torn_placement_is_dropped():
    # A placement that crosses the edge of the scrolling region cannot
    # move as a whole. It goes away instead of being torn.
    screen, stream, _ = make_screen()
    stream.feed("\x1b[5;1H")  # Row 4.
    place(screen, stream, 1, rows=4)  # Rows 4..7.
    stream.feed("\x1b[7;10r")  # Margins: rows 6..9.
    stream.feed("\x1b[10;1H")
    stream.feed("\n")
    assert placement_rows(screen) == []


def test_erase_saved_lines_removes_placements():
    screen, stream, _ = make_screen()
    place(screen, stream, 1)
    stream.feed("\x1b[3J")
    assert placement_rows(screen) == []


def test_history_trimming_drops_old_placements():
    screen, stream, _ = make_screen()
    place(screen, stream, 1)
    screen.get_history_limit = lambda: 10
    stream.feed("\x1b[100;1H")
    screen._remove_old_lines_from_history()
    assert placement_rows(screen) == []
