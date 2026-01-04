"""Small in-memory LRU cache for conversion outputs."""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LruCache(Generic[K, V]):
    """Thread-safe LRU cache.

    This is intentionally small and in-memory only. It reduces repeated conversions when
    users copy the same SVG multiple times.
    """

    def __init__(self, max_items: int) -> None:
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        self._max_items = int(max_items)
        self._lock = Lock()
        self._data: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key: K, value: V) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value
            while len(self._data) > self._max_items:
                self._data.popitem(last=False)




