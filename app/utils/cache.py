"""Server-side TTL cache for expensive API computations.

Provides a simple time-based cache with explicit invalidation.
Used by dashboard summary and strategy detection to avoid
redundant DB queries + external API calls on every request.
"""

import time
from threading import Lock


class TTLCache:
    """Thread-safe TTL cache with explicit invalidation support."""

    def __init__(self, ttl: float = 30.0, max_size: int = 64):
        self._store: dict[tuple, tuple[float, object]] = {}
        self._ttl = ttl
        self._max_size = max_size
        self._lock = Lock()

    def get(self, key: tuple) -> object | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, key: tuple, value: object) -> None:
        with self._lock:
            self._store[key] = (value, time.monotonic())
            # Evict oldest entries if over max size
            if len(self._store) > self._max_size:
                oldest_key = min(self._store, key=lambda k: self._store[k][1])
                del self._store[oldest_key]

    def invalidate(self, prefix: tuple | None = None) -> None:
        """Invalidate entries. If prefix is given, only clear matching keys."""
        with self._lock:
            if prefix is None:
                self._store.clear()
            else:
                keys_to_remove = [k for k in self._store if k[: len(prefix)] == prefix]
                for k in keys_to_remove:
                    del self._store[k]


# Shared caches — long TTLs are safe because sync/import operations
# explicitly call invalidate_all_caches() on data changes.
dashboard_summary_cache = TTLCache(ttl=3600.0, max_size=32)
strategies_cache = TTLCache(ttl=3600.0, max_size=16)


def user_cache_key(user_account_ids: list[int] | None) -> object:
    """Build a cache-safe key from user account IDs."""
    if user_account_ids is None:
        return "all"
    return tuple(sorted(user_account_ids))


def invalidate_all_caches() -> None:
    """Invalidate all caches — call after data mutations (import, sync, delete)."""
    dashboard_summary_cache.invalidate()
    strategies_cache.invalidate()
