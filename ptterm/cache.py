"""
A cache for the small immutable objects that a screen makes by the
thousand.
"""
from collections import deque
from typing import Callable, Deque, Dict, Hashable, Tuple, TypeVar

__all__ = ("FastDictCache",)

_K = TypeVar("_K", bound=Tuple[Hashable, ...])
_V = TypeVar("_V")


class FastDictCache(Dict[_K, _V]):
    """
    A dictionary that makes what it does not hold, and keeps `size`.

    The key is the argument list of `get_value`, so a lookup that
    misses calls it and keeps the answer. Nothing counts accesses: the
    oldest key goes when the cache is full.

    It is for a small object that is cheap to make and expensive to
    make a million times. A cell is that: a screen of 80 by 24 makes
    1920 of them, and nearly every one is a repeat.

    This is `prompt_toolkit.cache.FastDictCache`, copied because a
    screen is not a toolkit's. Lillecarl/pymux#11.
    """

    def __init__(self, get_value: Callable[..., _V], size: int = 1000000) -> None:
        assert size > 0

        self._keys: Deque[_K] = deque()
        self.get_value = get_value
        self.size = size

    def __missing__(self, key: _K) -> _V:
        # Remove the oldest key when the size is exceeded.
        if len(self) > self.size:
            key_to_remove = self._keys.popleft()
            if key_to_remove in self:
                del self[key_to_remove]

        result = self.get_value(*key)
        self[key] = result
        self._keys.append(key)
        return result
