import threading
from dataclasses import dataclass
from time import time


@dataclass
class RateWindow:
    count: int
    expires_at: float


class InMemoryRateLimiter:
    """Простой лимитер в памяти процесса. Для нескольких воркеров заменить на Redis."""

    _PRUNE_EVERY = 1000

    def __init__(self) -> None:
        self._store: dict[str, RateWindow] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def _prune(self, now: float) -> None:
        expired = [key for key, window in self._store.items() if window.expires_at <= now]
        for key in expired:
            self._store.pop(key, None)

    def allow(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time()
        with self._lock:
            self._calls += 1
            if self._calls % self._PRUNE_EVERY == 0:
                self._prune(now)
            current = self._store.get(key)
            if current is None or current.expires_at <= now:
                self._store[key] = RateWindow(count=1, expires_at=now + window_seconds)
                return True, 0
            if current.count >= limit:
                return False, max(int(current.expires_at - now), 1)
            current.count += 1
            return True, 0
