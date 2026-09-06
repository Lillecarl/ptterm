"""
That a coroutine test runs at all.

Three things have to hold together, and each one is somewhere else:
anyio is in the test environment (`nix/checks.nix`), `anyio_mode` is
`"auto"` (`pyproject.toml`), and that file reaches the directory the
suite runs in (`testSources` in `default.nix`). Take any one away and
every `async def test` in this repository stops running.

The third is the one that bit. The suite copies what `testSources`
names into a directory of its own, and pytest reads its settings from
the root it finds there. `pyproject.toml` was not in that set, so
`anyio_mode` was set in the repository and unset in the sandbox: the
tests here passed by hand and failed in the check.

pytest says so out loud rather than skipping. A coroutine test with no
plugin to run it fails with "async def functions are not natively
supported", which is a real failure and not a silent pass. This file is
here to make that failure say which of the three is missing, and
because a plain test can read a mark that a coroutine left.
"""
import anyio

#: What the coroutine below leaves behind.
RAN = []


async def test_a_coroutine_test_runs():
    "The mark, left from inside a running event loop."
    await anyio.sleep(0)
    RAN.append(anyio.get_current_task().name)


def test_the_coroutine_test_really_ran():
    "Read the mark. Empty means the test above never got to run."
    assert RAN, "the coroutine test did not run: is anyio_mode still auto?"


async def test_a_task_group_carries_what_a_child_raised():
    """
    The reason for anyio, in one test.

    A task group ends with its scope, and an error in a child reaches
    the code that started it. `asyncio.create_task` gives neither: a
    task nobody holds can be collected mid-flight, and what it raised
    goes nowhere.
    """

    async def fails():
        raise ValueError("from the child")

    try:
        async with anyio.create_task_group() as group:
            group.start_soon(fails)
    except* ValueError as caught:
        assert str(caught.exceptions[0]) == "from the child"
    else:
        raise AssertionError("the task group swallowed what the child raised")
