"""
Real programs, put to the whole panel.

`tests/corpus/*.bin` holds what a program wrote to a plain pty of 24 by
80. The grammar of the hunt covers what somebody thought to put in it;
a real program writes what a real program writes, which is the part
nobody thinks of.

Four judges answer here instead of one. A difference from all of them
is a bug of ptterm; a difference from some of them is a choice, and
the tally says who is on which side.

xterm answers as well, on its own and not as a judge. It holds only
where a character landed, and that is most of what a real program
does: every cursor move, every scroll and every wrap ends as a
character in a place.

`ptterm-record` makes a capture. A recording belongs to the
terminal it was made on, because a program asks what the terminal can
do and draws what the answers allow.
"""

import codecs
import json
import pathlib

import pytest

from kitty_oracle import ptterm_cells, ptterm_cells_in_pieces
from panel import (
    judges,
    report,
    verdict,
    what_ptterm_draws,
    what_xterm_draws,
    xterm_is_here,
)

CORPUS = pathlib.Path(__file__).parent / "corpus"

#: The panel is worth asking with two judges. With one it is the
#: comparison that `test_corpus_against_kitty` already does.
pytestmark = pytest.mark.skipif(
    len(judges()) < 2, reason="fewer than two judges are here"
)


def captures():
    return sorted(path.name for path in CORPUS.glob("*.bin"))


def text_of(name):
    return (CORPUS / name).read_bytes().decode("utf-8", "replace")


@pytest.mark.parametrize("name", captures())
def test_no_judge_stands_against_ptterm_alone(name):
    "Every judge agreeing against ptterm is a bug with nothing to decide."
    data = text_of(name)
    said = verdict(data, lines=24, columns=80)
    if said == "ptterm-wrong":
        answers = report(data, lines=24, columns=80)
        pytest.fail(
            "%s\n%s"
            % (
                name,
                "\n".join(
                    "%s: %s" % (judge, found[0])
                    for judge, found in answers.items()
                    if found
                ),
            )
        )


@pytest.mark.skipif(not xterm_is_here(), reason="xterm has no display here")
@pytest.mark.parametrize("name", captures())
def test_xterm_draws_the_same_characters(name):
    """
    The same capture, put to xterm itself.

    xterm holds no colour and no underline, so it is not on the panel
    and `verdict()` never sees it. It holds where a character landed,
    which is what a whole program of a real terminal is mostly about:
    every cursor move, every scroll, every wrap and every erase shows
    up as a character in the wrong place.

    A capture is 24 by 80, so this is 1920 queries and 1920 answers per
    file, and it costs about ten milliseconds each.
    `tests/xterm_oracle.py` says how it is asked.
    """
    data = text_of(name)
    assert what_xterm_draws(data, 24, 80) == what_ptterm_draws(data, 24, 80)


@pytest.mark.parametrize("name", captures())
def test_the_reads_of_the_capture_draw_the_same_screen(name):
    """
    The bytes arrive the way the pty handed them over.

    A capture keeps the size of every read, so the replay can cut the
    stream where the terminal cut it. A parser that loses a sequence
    across a read shows up here and nowhere else.
    """
    path = CORPUS / ("%s.reads.json" % name[: -len(".bin")])
    if not path.exists():
        pytest.skip("this capture holds no sizes")

    kept = json.loads(path.read_text())
    raw = (CORPUS / name).read_bytes()
    data = raw.decode("utf-8", "replace")

    # The sizes count bytes, and a character of several bytes may sit
    # across two of them. The decoder holds the half it has, the way
    # the reader of a pty does.
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    pieces = []
    at = 0
    for size in kept["sizes"]:
        pieces.append(decoder.decode(raw[at : at + size]))
        at += size
    pieces.append(decoder.decode(raw[at:], True))

    lines, columns = kept["lines"], kept["columns"]
    assert ptterm_cells_in_pieces(pieces, lines, columns) == ptterm_cells(
        data, lines, columns
    )
