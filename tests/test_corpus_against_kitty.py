"""
Real programs, compared cell by cell against kitty.

`tests/corpus/*.bin` holds what a program wrote to a plain pty of 24 by
80. Feeding the same bytes to ptterm and to kitty says whether a user
would see the same screen. This is where a bug like the missing green
of the htop header shows up.

A capture holds the answers that the program asked for as well, so a
difference can also come from a query that ptterm answers differently.
Keep that in mind when one of these fails.
"""
import pathlib

import pytest

from kitty_oracle import differences, kitty_is_available

CORPUS = pathlib.Path(__file__).parent / "corpus"

pytestmark = pytest.mark.skipif(
    not kitty_is_available(), reason="the kitty python package is not there"
)


def _captures():
    return sorted(path.name for path in CORPUS.glob("*.bin"))


@pytest.mark.parametrize("name", _captures())
def test_a_real_program_gives_the_same_screen(name):
    data = (CORPUS / name).read_bytes().decode("utf-8", "replace")
    found = differences(data, lines=24, columns=80)
    assert not found, "%d cells differ\n%s" % (len(found), "\n".join(found[:20]))
