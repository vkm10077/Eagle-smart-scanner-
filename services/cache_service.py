from __future__ import annotations

"""
Eagle Smart Scanner - Cache Service

Lightweight thread-safe TTL cache used across the project.

Responsibilities
----------------
- Cache real API/scanner results for short periods
- Prevent repeated expensive calls
- Support per-key TTL
- Safe get/set/delete/clear
- Never create or substitute fake market data

This cache is process-local and suitable for Render/free-plan deployment.
Persistent scanner outputs are handled separately by scanner_orchestrator.py.
"""

import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class _CacheItem:
    value: Any
    expires_at: float | None


class CacheService:
    """
    Simple in-memory TTL cache.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, _CacheItem] = {}

    # ========================================================
    # BASIC OPERATIONS
    # ========================================================

    def set(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: int | float | None = None,
    ) -> None:
        cache_key = self._normalize_key(key)

        expires_at: float | None = None

        if ttl_seconds is not None:
            ttl = float(ttl_seconds)

            if ttl <= 0:
                self.delete(cache_key)
                return

            expires_at = time.time() + ttl

        with self._lock:
            self._items[cache_key] = _CacheItem(
                value=value,
                expires_at=expires_at,
            )

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        cache_key = self._normalize_key(key)

        with self._lock:
            item = self._items.get(cache_key)

            if item is None:
                return default

            if self._is_expired(item):
                self._items.pop(
                    cache_key,
                    None,
                )
                return default

            return item.value

    def has(
        self,
        key: str,
    ) -> bool:
        marker = object()

        return self.get(
            key,
            marker,
        ) is not marker

    def delete(
        self,
        key: str,
    ) -> bool:
        cache_key = self._normalize_key(key)

        with self._lock:
            existed = (
                cache_key
                in self._items
            )

            self._items.pop(
                cache_key,
                None,
            )

        return existed

    def clear(
        self,
        *,
        prefix: str | None = None,
    ) -> int:
        with self._lock:
            if prefix is None:
                count = len(
                    self._items
                )

                self._items.clear()

                return count

            normalized_prefix = str(
                prefix
            ).strip()

            keys = [
                key
                for key in self._items
                if key.startswith(
                    normalized_prefix
                )
            ]

            for key in keys:
                self._items.pop(
                    key,
                    None,
                )

            return len(keys)

    # ========================================================
    # TTL HELPERS
    # ========================================================

    def get_ttl(
        self,
        key: str,
    ) -> float | None:
        cache_key = self._normalize_key(key)

        with self._lock:
            item = self._items.get(
                cache_key
            )

            if item is None:
                return None

            if self._is_expired(item):
                self._items.pop(
                    cache_key,
                    None,
                )
                return None

            if item.expires_at is None:
                return None

            return max(
                0.0,
                item.expires_at
                - time.time(),
            )

    def touch(
        self,
        key: str,
        *,
        ttl_seconds: int | float,
    ) -> bool:
        cache_key = self._normalize_key(key)

        ttl = float(
            ttl_seconds
        )

        if ttl <= 0:
            return self.delete(
                cache_key
            )

        with self._lock:
            item = self._items.get(
                cache_key
            )

            if item is None:
                return False

            if self._is_expired(item):
                self._items.pop(
                    cache_key,
                    None,
                )
                return False

            item.expires_at = (
                time.time()
                + ttl
            )

            return True

    # ========================================================
    # CLEANUP
    # ========================================================

    def purge_expired(
        self,
    ) -> int:
        now = time.time()

        with self._lock:
            expired = [
                key
                for key, item
                in self._items.items()
                if (
                    item.expires_at
                    is not None
                    and now
                    >= item.expires_at
                )
            ]

            for key in expired:
                self._items.pop(
                    key,
                    None,
                )

            return len(
                expired
            )

    # ========================================================
    # GET-OR-SET
    # ========================================================

    def get_or_set(
        self,
        key: str,
        factory,
        *,
        ttl_seconds: int | float | None = None,
    ) -> Any:
        marker = object()

        existing = self.get(
            key,
            marker,
        )

        if existing is not marker:
            return existing

        value = factory()

        self.set(
            key,
            value,
            ttl_seconds=ttl_seconds,
        )

        return value

    # ========================================================
    # STATUS
    # ========================================================

    def stats(
        self,
    ) -> dict[str, Any]:
        self.purge_expired()

        with self._lock:
            permanent = 0
            expiring = 0

            for item in self._items.values():
                if item.expires_at is None:
                    permanent += 1
                else:
                    expiring += 1

            return {
                "items": len(
                    self._items
                ),
                "permanent_items": (
                    permanent
                ),
                "expiring_items": (
                    expiring
                ),
            }

    # ========================================================
    # INTERNAL
    # ========================================================

    @staticmethod
    def _normalize_key(
        key: str,
    ) -> str:
        value = str(
            key or ""
        ).strip()

        if not value:
            raise ValueError(
                "Cache key cannot be empty"
            )

        return value

    @staticmethod
    def _is_expired(
        item: _CacheItem,
    ) -> bool:
        if item.expires_at is None:
            return False

        return (
            time.time()
            >= item.expires_at
        )


# ============================================================
# SINGLETON
# ============================================================

_default_cache_service = CacheService()


def get_cache_service(
) -> CacheService:
    return _default_cache_service


# ============================================================
# MODULE HELPERS
# ============================================================

def cache_get(
    key: str,
    default: Any = None,
) -> Any:
    return (
        _default_cache_service
        .get(
            key,
            default,
        )
    )


def cache_set(
    key: str,
    value: Any,
    *,
    ttl_seconds: int | float | None = None,
) -> None:
    _default_cache_service.set(
        key,
        value,
        ttl_seconds=ttl_seconds,
    )


def cache_delete(
    key: str,
) -> bool:
    return (
        _default_cache_service
        .delete(key)
    )


def cache_clear(
    *,
    prefix: str | None = None,
) -> int:
    return (
        _default_cache_service
        .clear(
            prefix=prefix
        )
    )
