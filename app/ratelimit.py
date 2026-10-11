"""Slow down guessing at sign-in and sign-up: a count of recent attempts per key (an address, an email).

Kept in memory per process (several workers each keep their own count, so the real limit is a little looser),
which is enough to make guessing impractical; it forgets on restart and never locks anybody out for long.
"""

import math
import threading
import time
from collections import deque


class AttemptLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str, limit: int, window_seconds: float, now: float | None = None) -> int | None:
        """Seconds until another attempt is allowed, or None when the key is within its limit (0 = no limit)."""
        if not limit:
            return None
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return None
            while hits and now - hits[0] >= window_seconds:
                hits.popleft()
            if len(hits) < limit:
                return None
            return max(1, math.ceil(hits[0] + window_seconds - now))

    def hit(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._hits.setdefault(key, deque()).append(now)
            if len(self._hits) > 10_000:  # forget keys that have gone quiet
                for stale in [k for k, v in self._hits.items() if not v or now - v[-1] > 3600]:
                    del self._hits[stale]

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


# One shared limiter for the sign-in and sign-up pages.
attempts = AttemptLimiter()


def minutes(seconds: int) -> int:
    return max(1, math.ceil(seconds / 60))
