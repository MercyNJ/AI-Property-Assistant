"""In-memory sliding-window rate limits for /api/chat: per client IP plus a global daily cap."""

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

MINUTE = 60
DAY = 24 * 3600


@dataclass
class Limited:
    message: str
    retry_after: int  # seconds


def _prune(stamps: deque[float], cutoff: float) -> deque[float]:
    while stamps and stamps[0] <= cutoff:
        stamps.popleft()
    return stamps


class ChatRateLimiter:
    def __init__(self, per_minute: int, per_day: int, global_per_day: int,
                 clock: Callable[[], float] = time.monotonic):
        # Floor of 1: a zero limit would refuse everything and break Retry-After.
        self.per_minute = max(1, per_minute)
        self.per_day = max(1, per_day)
        self.global_per_day = max(1, global_per_day)
        self.clock = clock
        self._minute: dict[str, deque[float]] = {}
        self._day: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self, client: str) -> Limited | None:
        """Record a request from `client`, or return why it is refused (refusals are not counted)."""
        now = self.clock()
        with self._lock:
            minute = _prune(self._minute.get(client, deque()), now - MINUTE)
            day = _prune(self._day.get(client, deque()), now - DAY)
            _prune(self._global, now - DAY)

            if len(minute) >= self.per_minute:
                return Limited("You're sending messages too quickly. Please wait a minute and try again.",
                               _wait(minute[0] + MINUTE, now))
            if len(day) >= self.per_day:
                return Limited("You've reached today's message limit. Please try again tomorrow.",
                               _wait(day[0] + DAY, now))
            if len(self._global) >= self.global_per_day:
                return Limited("The assistant has reached its daily usage limit. Please try again tomorrow.",
                               _wait(self._global[0] + DAY, now))

            for stamps in (minute, day, self._global):
                stamps.append(now)
            self._minute[client], self._day[client] = minute, day
            if len(self._day) > self.global_per_day:
                self._forget_idle(now)
        return None

    def _forget_idle(self, now: float) -> None:
        for client in [c for c, stamps in self._day.items() if not _prune(stamps, now - DAY)]:
            del self._day[client]
            self._minute.pop(client, None)


def _wait(until: float, now: float) -> int:
    return max(1, math.ceil(until - now))
