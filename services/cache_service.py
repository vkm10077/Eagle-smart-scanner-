from __future__ import annotations

import copy
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from cachetools import TTLCache

from utils.helpers import (
    build_cache_key,
    clean_text,
    safe_int,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_exception,
)


logger = get_logger("services.cache_service")


@dataclass
class CacheRecord:
    key: str
    value: Any
    created_at: datetime
    expires_at: datetime
    ttl_seconds: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": copy.deepcopy(self.value),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "ttl_seconds": self.ttl_seconds,
        }


class CacheService:
    """
    Thread-safe in-memory cache for Eagle Smart Scanner.

    This cache is designed for:
    - Live index data
    - Stock quotes
    - Historical candles
    - Fundamental data
    - Scan results
    - Search results
    - Scanner health status
    """

    DEFAULT_TTL_SECONDS = 60
    DEFAULT_MAX_SIZE = 5000

    def __init__(
        self,
        *,
        default_ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_size: int = DEFAULT_MAX_SIZE,
    ) -> None:
        self.default_ttl_seconds = max(
            1,
            safe_int(
                default_ttl_seconds,
                default=self.DEFAULT_TTL_SECONDS,
            )
            or self.DEFAULT_TTL_SECONDS,
        )

        self.max_size = max(
            100,
            safe_int(
                max_size,
                default=self.DEFAULT_MAX_SIZE,
            )
            or self.DEFAULT_MAX_SIZE,
        )

        self._cache = TTLCache(
            maxsize=self.max_size,
            ttl=self.default_ttl_seconds,
        )

        self._records: dict[str, CacheRecord] = {}
        self._lock = threading.RLock()

        self._stats: dict[str, int] = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "expirations": 0,
            "errors": 0,
        }

        logger.info(
            "Cache service initialized.",
            extra=build_log_extra(
                component="cache_service",
                event="cache_initialized",
                status="success",
                default_ttl_seconds=self.default_ttl_seconds,
                max_size=self.max_size,
            ),
        )

    def _normalize_key(
        self,
        key: Any,
    ) -> str:
        normalized_key = clean_text(key)

        if not normalized_key:
            raise ValueError(
                "Cache key cannot be empty."
            )

        return normalized_key

    def _build_record(
        self,
        *,
        key: str,
        value: Any,
        ttl_seconds: int,
    ) -> CacheRecord:
        created_at = utc_now()

        expires_at = datetime.fromtimestamp(
            created_at.timestamp() + ttl_seconds,
            tz=timezone.utc,
        )

        return CacheRecord(
            key=key,
            value=copy.deepcopy(value),
            created_at=created_at,
            expires_at=expires_at,
            ttl_seconds=ttl_seconds,
        )

    def set(
        self,
        key: Any,
        value: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> bool:
        try:
            normalized_key = self._normalize_key(
                key
            )

            resolved_ttl = max(
                1,
                safe_int(
                    ttl_seconds,
                    default=self.default_ttl_seconds,
                )
                or self.default_ttl_seconds,
            )

            record = self._build_record(
                key=normalized_key,
                value=value,
                ttl_seconds=resolved_ttl,
            )

            with self._lock:
                if resolved_ttl == self.default_ttl_seconds:
                    self._cache[normalized_key] = copy.deepcopy(
                        value
                    )
                else:
                    self._cache[normalized_key] = copy.deepcopy(
                        value
                    )

                self._records[normalized_key] = record
                self._stats["sets"] += 1

            return True

        except Exception as exception:
            with self._lock:
                self._stats["errors"] += 1

            log_exception(
                logger,
                "Unable to write cache value",
                exception=exception,
                component="cache_service",
                cache_key=clean_text(key),
            )

            return False

    def get(
        self,
        key: Any,
        *,
        default: Any = None,
    ) -> Any:
        try:
            normalized_key = self._normalize_key(
                key
            )

            with self._lock:
                record = self._records.get(
                    normalized_key
                )

                if record is not None:
                    if utc_now() >= record.expires_at:
                        self._delete_unlocked(
                            normalized_key,
                            expired=True,
                        )

                        self._stats["misses"] += 1
                        return copy.deepcopy(default)

                    self._stats["hits"] += 1
                    return copy.deepcopy(
                        record.value
                    )

                try:
                    cached_value = self._cache[
                        normalized_key
                    ]

                    self._stats["hits"] += 1

                    return copy.deepcopy(
                        cached_value
                    )

                except KeyError:
                    self._stats["misses"] += 1
                    return copy.deepcopy(default)

        except Exception as exception:
            with self._lock:
                self._stats["errors"] += 1

            log_exception(
                logger,
                "Unable to read cache value",
                exception=exception,
                component="cache_service",
                cache_key=clean_text(key),
            )

            return copy.deepcopy(default)

    def get_record(
        self,
        key: Any,
    ) -> CacheRecord | None:
        try:
            normalized_key = self._normalize_key(
                key
            )

            with self._lock:
                record = self._records.get(
                    normalized_key
                )

                if record is None:
                    return None

                if utc_now() >= record.expires_at:
                    self._delete_unlocked(
                        normalized_key,
                        expired=True,
                    )
                    return None

                return CacheRecord(
                    key=record.key,
                    value=copy.deepcopy(record.value),
                    created_at=record.created_at,
                    expires_at=record.expires_at,
                    ttl_seconds=record.ttl_seconds,
                )

        except Exception:
            return None

    def has(
        self,
        key: Any,
    ) -> bool:
        return self.get_record(key) is not None

    def remaining_ttl(
        self,
        key: Any,
    ) -> int:
        record = self.get_record(key)

        if record is None:
            return 0

        remaining_seconds = int(
            (
                record.expires_at - utc_now()
            ).total_seconds()
        )

        return max(
            0,
            remaining_seconds,
        )

    def delete(
        self,
        key: Any,
    ) -> bool:
        try:
            normalized_key = self._normalize_key(
                key
            )

            with self._lock:
                return self._delete_unlocked(
                    normalized_key
                )

        except Exception as exception:
            with self._lock:
                self._stats["errors"] += 1

            log_exception(
                logger,
                "Unable to delete cache value",
                exception=exception,
                component="cache_service",
                cache_key=clean_text(key),
            )

            return False

    def _delete_unlocked(
        self,
        key: str,
        *,
        expired: bool = False,
    ) -> bool:
        existed = False

        if key in self._records:
            self._records.pop(
                key,
                None,
            )
            existed = True

        try:
            del self._cache[key]
            existed = True
        except KeyError:
            pass

        if existed:
            self._stats["deletes"] += 1

            if expired:
                self._stats["expirations"] += 1

        return existed

    def clear(
        self,
    ) -> None:
        with self._lock:
            self._cache.clear()
            self._records.clear()

        logger.info(
            "All cache entries cleared.",
            extra=build_log_extra(
                component="cache_service",
                event="cache_cleared",
                status="success",
            ),
        )

    def clear_prefix(
        self,
        prefix: Any,
    ) -> int:
        normalized_prefix = clean_text(
            prefix
        )

        if not normalized_prefix:
            return 0

        deleted_count = 0

        with self._lock:
            matching_keys = [
                key
                for key in self._records.keys()
                if key.startswith(
                    normalized_prefix
                )
            ]

            for key in matching_keys:
                if self._delete_unlocked(key):
                    deleted_count += 1

        return deleted_count

    def clear_expired(
        self,
    ) -> int:
        current_time = utc_now()
        deleted_count = 0

        with self._lock:
            expired_keys = [
                key
                for key, record in self._records.items()
                if current_time >= record.expires_at
            ]

            for key in expired_keys:
                if self._delete_unlocked(
                    key,
                    expired=True,
                ):
                    deleted_count += 1

        return deleted_count

    def get_or_set(
        self,
        key: Any,
        loader: Callable[[], Any],
        *,
        ttl_seconds: int | None = None,
        use_stale_on_error: bool = False,
    ) -> Any:
        normalized_key = self._normalize_key(
            key
        )

        cached_value = self.get(
            normalized_key,
            default=None,
        )

        if cached_value is not None:
            return cached_value

        stale_record = None

        if use_stale_on_error:
            with self._lock:
                stale_record = self._records.get(
                    normalized_key
                )

        try:
            loaded_value = loader()

            if loaded_value is not None:
                self.set(
                    normalized_key,
                    loaded_value,
                    ttl_seconds=ttl_seconds,
                )

            return copy.deepcopy(
                loaded_value
            )

        except Exception as exception:
            with self._lock:
                self._stats["errors"] += 1

            log_exception(
                logger,
                "Cache loader failed",
                exception=exception,
                component="cache_service",
                cache_key=normalized_key,
            )

            if (
                use_stale_on_error
                and stale_record is not None
            ):
                logger.warning(
                    "Using stale cache value after loader failure.",
                    extra=build_log_extra(
                        component="cache_service",
                        event="stale_cache_used",
                        status="warning",
                        cache_key=normalized_key,
                    ),
                )

                return copy.deepcopy(
                    stale_record.value
                )

            raise

    def increment(
        self,
        key: Any,
        *,
        amount: int = 1,
        ttl_seconds: int | None = None,
    ) -> int:
        normalized_key = self._normalize_key(
            key
        )

        safe_amount = safe_int(
            amount,
            default=1,
        ) or 1

        with self._lock:
            current_value = self.get(
                normalized_key,
                default=0,
            )

            current_number = safe_int(
                current_value,
                default=0,
            ) or 0

            new_value = current_number + safe_amount

            self.set(
                normalized_key,
                new_value,
                ttl_seconds=ttl_seconds,
            )

            return new_value

    def set_json(
        self,
        key: Any,
        value: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> bool:
        try:
            json_value = json.loads(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    default=str,
                )
            )

            return self.set(
                key,
                json_value,
                ttl_seconds=ttl_seconds,
            )

        except Exception as exception:
            log_exception(
                logger,
                "Unable to serialize cache value",
                exception=exception,
                component="cache_service",
                cache_key=clean_text(key),
            )

            return False

    def get_json(
        self,
        key: Any,
        *,
        default: Any = None,
    ) -> Any:
        value = self.get(
            key,
            default=default,
        )

        try:
            return json.loads(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    default=str,
                )
            )

        except Exception:
            return copy.deepcopy(default)

    def list_keys(
        self,
        *,
        prefix: str | None = None,
    ) -> list[str]:
        with self._lock:
            keys = list(
                self._records.keys()
            )

        if prefix:
            normalized_prefix = clean_text(
                prefix
            )

            keys = [
                key
                for key in keys
                if key.startswith(
                    normalized_prefix
                )
            ]

        return sorted(keys)

    def stats(
        self,
    ) -> dict[str, Any]:
        self.clear_expired()

        with self._lock:
            total_requests = (
                self._stats["hits"]
                + self._stats["misses"]
            )

            hit_rate = (
                (
                    self._stats["hits"]
                    / total_requests
                )
                * 100
                if total_requests > 0
                else 0.0
            )

            return {
                **self._stats,
                "hit_rate_percent": round(
                    hit_rate,
                    2,
                ),
                "active_entries": len(
                    self._records
                ),
                "max_size": self.max_size,
                "default_ttl_seconds": (
                    self.default_ttl_seconds
                ),
                "generated_at": utc_now().isoformat(),
            }

    def health(
        self,
    ) -> dict[str, Any]:
        try:
            test_key = build_cache_key(
                "health",
                time.time(),
                prefix="eagle-cache",
            )

            test_value = {
                "status": "ok",
                "timestamp": utc_now().isoformat(),
            }

            write_success = self.set(
                test_key,
                test_value,
                ttl_seconds=5,
            )

            read_value = self.get(
                test_key
            )

            delete_success = self.delete(
                test_key
            )

            is_healthy = (
                write_success
                and read_value == test_value
                and delete_success
            )

            return {
                "status": (
                    "healthy"
                    if is_healthy
                    else "unhealthy"
                ),
                "is_healthy": is_healthy,
                "stats": self.stats(),
                "checked_at": utc_now().isoformat(),
            }

        except Exception as exception:
            return {
                "status": "unhealthy",
                "is_healthy": False,
                "error": str(exception),
                "checked_at": utc_now().isoformat(),
            }


_global_cache_service: CacheService | None = None
_global_cache_lock = threading.Lock()


def get_cache_service() -> CacheService:
    global _global_cache_service

    if _global_cache_service is not None:
        return _global_cache_service

    with _global_cache_lock:
        if _global_cache_service is None:
            _global_cache_service = CacheService()

    return _global_cache_service


def cache_get(
    key: Any,
    *,
    default: Any = None,
) -> Any:
    return get_cache_service().get(
        key,
        default=default,
    )


def cache_set(
    key: Any,
    value: Any,
    *,
    ttl_seconds: int | None = None,
) -> bool:
    return get_cache_service().set(
        key,
        value,
        ttl_seconds=ttl_seconds,
    )


def cache_delete(
    key: Any,
) -> bool:
    return get_cache_service().delete(
        key
    )


def cache_clear() -> None:
    get_cache_service().clear()
