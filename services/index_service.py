from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Iterable

from services.cache_service import (
    CacheService,
    get_cache_service,
)
from services.fyers_service import (
    FyersAPIError,
    FyersAuthenticationError,
    FyersService,
    get_fyers_service,
)
from services.market_data_service import (
    MarketDataService,
    get_market_data_service,
)
from utils.helpers import (
    build_cache_key,
    clean_text,
    percentage_change,
    safe_float,
    safe_int,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_api_call,
    log_exception,
)


logger = get_logger("services.index_service")


# ============================================================
# ERRORS
# ============================================================


class IndexDataError(RuntimeError):
    """Base exception for index-data failures."""


class IndexDataUnavailableError(IndexDataError):
    """Raised when verified index data is unavailable."""


# ============================================================
# INDEX SERVICE
# ============================================================


class IndexService:
    """
    Live market-index service for Eagle Smart Scanner.

    Responsibilities:
    - Fetch important Indian market indices from FYERS
    - Normalize prices and percentage changes
    - Cache index data for fast dashboard refresh
    - Retry alternate symbol formats where required
    - Automatically isolate bad FYERS symbols
    - Never generate dummy or estimated index prices
    """

    CACHE_SECONDS = 8
    STALE_FALLBACK_SECONDS = 90
    REQUEST_BATCH_SIZE = 25

    # ========================================================
    # INDEX DEFINITIONS
    # ========================================================

    INDEX_DEFINITIONS: dict[str, dict[str, Any]] = {
        "nifty_50": {
            "name": "NIFTY 50",
            "short_name": "NIFTY",
            "exchange": "NSE",
            "candidates": (
                "NSE:NIFTY50-INDEX",
            ),
        },
        "bank_nifty": {
            "name": "NIFTY BANK",
            "short_name": "BANK NIFTY",
            "exchange": "NSE",
            "candidates": (
                "NSE:NIFTYBANK-INDEX",
            ),
        },
        "sensex": {
            "name": "SENSEX",
            "short_name": "SENSEX",
            "exchange": "BSE",
            "candidates": (
                "BSE:SENSEX-INDEX",
                "BSE:SENSEX",
            ),
        },
        "fin_nifty": {
            "name": "NIFTY FIN SERVICE",
            "short_name": "FINNIFTY",
            "exchange": "NSE",
            "candidates": (
                "NSE:FINNIFTY-INDEX",
                "NSE:NIFTYFINSERVICE-INDEX",
            ),
        },
        "nifty_next_50": {
            "name": "NIFTY NEXT 50",
            "short_name": "NEXT 50",
            "exchange": "NSE",
            "candidates": (
                "NSE:NIFTYNXT50-INDEX",
                "NSE:NIFTYNEXT50-INDEX",
            ),
        },
        "nifty_midcap": {
            "name": "NIFTY MIDCAP SELECT",
            "short_name": "MIDCAP",
            "exchange": "NSE",
            "candidates": (
                "NSE:MIDCPNIFTY-INDEX",
                "NSE:NIFTY_MID_SELECT-INDEX",
                "NSE:NIFTYMIDCAP50-INDEX",
            ),
        },
        "india_vix": {
            "name": "INDIA VIX",
            "short_name": "VIX",
            "exchange": "NSE",
            "candidates": (
                "NSE:INDIAVIX-INDEX",
            ),
        },
    }

    DEFAULT_INDEX_ORDER = (
        "nifty_50",
        "bank_nifty",
        "sensex",
        "fin_nifty",
        "nifty_next_50",
        "nifty_midcap",
        "india_vix",
    )

    # ========================================================
    # INITIALIZATION
    # ========================================================

    def __init__(
        self,
        *,
        fyers_service: FyersService | None = None,
        market_data_service: MarketDataService | None = None,
        cache_service: CacheService | None = None,
    ) -> None:

        self.fyers_service = (
            fyers_service
            or get_fyers_service()
        )

        self.market_data_service = (
            market_data_service
            or get_market_data_service()
        )

        self.cache_service = (
            cache_service
            or get_cache_service()
        )

        self._refresh_lock = (
            threading.RLock()
        )

    # ========================================================
    # BASIC HELPERS
    # ========================================================

    @staticmethod
    def _normalize_full_symbol(
        value: Any,
    ) -> str:

        return (
            clean_text(value)
            .upper()
        )

    @staticmethod
    def _extract_epoch_datetime(
        value: Any,
    ) -> datetime | None:

        if isinstance(
            value,
            datetime,
        ):

            if value.tzinfo is None:
                return value.replace(
                    tzinfo=timezone.utc
                )

            return value.astimezone(
                timezone.utc
            )

        epoch_value = (
            safe_int(value)
        )

        if epoch_value is None:
            return None

        try:

            if epoch_value > 10_000_000_000:
                epoch_value = int(
                    epoch_value / 1000
                )

            return datetime.fromtimestamp(
                epoch_value,
                tz=timezone.utc,
            )

        except (
            ValueError,
            OSError,
            OverflowError,
        ):
            return None

    # ========================================================
    # SUPPORTED INDICES
    # ========================================================

    @classmethod
    def get_supported_indices(
        cls,
    ) -> list[dict[str, Any]]:

        supported: list[
            dict[str, Any]
        ] = []

        for index_key in (
            cls.DEFAULT_INDEX_ORDER
        ):

            definition = (
                cls.INDEX_DEFINITIONS[
                    index_key
                ]
            )

            supported.append(
                {
                    "key": index_key,
                    "name": (
                        definition["name"]
                    ),
                    "short_name": (
                        definition[
                            "short_name"
                        ]
                    ),
                    "exchange": (
                        definition[
                            "exchange"
                        ]
                    ),
                }
            )

        return supported

    # ========================================================
    # INDEX KEY NORMALIZATION
    # ========================================================

    @classmethod
    def normalize_index_key(
        cls,
        value: Any,
    ) -> str | None:

        text = (
            clean_text(value)
            .casefold()
        )

        if not text:
            return None

        normalized = (
            text
            .replace(" ", "_")
            .replace("-", "_")
            .replace("&", "and")
        )

        aliases = {
            "nifty": "nifty_50",
            "nifty50": "nifty_50",
            "nifty_50": "nifty_50",

            "banknifty": "bank_nifty",
            "bank_nifty": "bank_nifty",
            "nifty_bank": "bank_nifty",

            "sensex": "sensex",
            "bse_sensex": "sensex",

            "finnifty": "fin_nifty",
            "fin_nifty": "fin_nifty",
            "nifty_fin_service": (
                "fin_nifty"
            ),

            "next50": (
                "nifty_next_50"
            ),
            "next_50": (
                "nifty_next_50"
            ),
            "nifty_next_50": (
                "nifty_next_50"
            ),

            "midcap": (
                "nifty_midcap"
            ),
            "midcap_nifty": (
                "nifty_midcap"
            ),
            "midcpnifty": (
                "nifty_midcap"
            ),
            "nifty_midcap": (
                "nifty_midcap"
            ),

            "vix": "india_vix",
            "india_vix": (
                "india_vix"
            ),
            "indiavix": (
                "india_vix"
            ),
        }

        if normalized in (
            cls.INDEX_DEFINITIONS
        ):
            return normalized

        return aliases.get(
            normalized
        )

    # ========================================================
    # FIND INDEX BY FYERS SYMBOL
    # ========================================================

    @classmethod
    def _find_index_key_by_symbol(
        cls,
        symbol: Any,
    ) -> str | None:

        normalized_symbol = (
            cls._normalize_full_symbol(
                symbol
            )
        )

        if not normalized_symbol:
            return None

        for (
            index_key,
            definition,
        ) in (
            cls.INDEX_DEFINITIONS.items()
        ):

            candidates = {
                cls._normalize_full_symbol(
                    item
                )
                for item in (
                    definition[
                        "candidates"
                    ]
                )
            }

            if (
                normalized_symbol
                in candidates
            ):
                return index_key

        return None

    # ========================================================
    # EXTRACT FYERS QUOTE ITEMS
    # ========================================================

    @staticmethod
    def _extract_quote_items(
        response: dict[str, Any],
    ) -> list[dict[str, Any]]:

        if not isinstance(
            response,
            dict,
        ):
            return []

        response_data: Any = (
            response.get("d")
            or response.get("data")
            or response.get("quotes")
        )

        if isinstance(
            response_data,
            dict,
        ):

            nested_data = (
                response_data.get("d")
                or response_data.get(
                    "data"
                )
                or response_data.get(
                    "quotes"
                )
            )

            if isinstance(
                nested_data,
                list,
            ):
                response_data = (
                    nested_data
                )

            else:
                response_data = [
                    response_data
                ]

        if not isinstance(
            response_data,
            list,
        ):
            return []

        return [
            item
            for item in response_data
            if isinstance(
                item,
                dict,
            )
        ]

    # ========================================================
    # NORMALIZE INDEX QUOTE
    # ========================================================

    def _normalize_index_quote(
        self,
        item: dict[str, Any],
        *,
        fallback_index_key: (
            str | None
        ) = None,
    ) -> dict[str, Any] | None:

        values = item.get(
            "v"
        )

        if not isinstance(
            values,
            dict,
        ):
            values = item.get(
                "data"
            )

        if not isinstance(
            values,
            dict,
        ):
            values = item

        full_symbol = (
            self._normalize_full_symbol(
                item.get("n")
                or item.get(
                    "symbol"
                )
                or values.get(
                    "symbol"
                )
            )
        )

        index_key = (
            self._find_index_key_by_symbol(
                full_symbol
            )
            or fallback_index_key
        )

        if (
            not index_key
            or index_key
            not in self.INDEX_DEFINITIONS
        ):
            return None

        definition = (
            self.INDEX_DEFINITIONS[
                index_key
            ]
        )

        current_price = safe_float(
            values.get("lp")
            or values.get("ltp")
            or values.get(
                "last_price"
            )
            or values.get(
                "current_price"
            )
        )

        previous_close = safe_float(
            values.get(
                "prev_close_price"
            )
            or values.get(
                "previous_close"
            )
            or values.get(
                "prev_close"
            )
            or values.get(
                "close"
            )
        )

        change = safe_float(
            values.get("ch")
            or values.get(
                "change"
            )
        )

        change_percent = safe_float(
            values.get("chp")
            or values.get(
                "change_percent"
            )
            or values.get(
                "percent_change"
            )
        )

        open_price = safe_float(
            values.get(
                "open_price"
            )
            or values.get(
                "open"
            )
            or values.get("o")
        )

        high_price = safe_float(
            values.get(
                "high_price"
            )
            or values.get(
                "high"
            )
            or values.get("h")
        )

        low_price = safe_float(
            values.get(
                "low_price"
            )
            or values.get(
                "low"
            )
            or values.get("l")
        )

        if (
            current_price is None
            or current_price <= 0
        ):
            return None

        if (
            change is None
            and previous_close
            is not None
        ):
            change = (
                current_price
                - previous_close
            )

        if (
            change_percent is None
            and previous_close
            not in {
                None,
                0.0,
            }
        ):
            change_percent = (
                percentage_change(
                    current_price,
                    previous_close,
                )
            )

        timestamp_value = (
            values.get(
                "exchange_timestamp"
            )
            or values.get(
                "timestamp"
            )
            or values.get(
                "last_traded_time"
            )
            or values.get("tt")
            or item.get(
                "timestamp"
            )
        )

        timestamp = (
            self._extract_epoch_datetime(
                timestamp_value
            )
            or utc_now()
        )

        direction = "NEUTRAL"

        if (
            change_percent is not None
            and change_percent > 0
        ):
            direction = "POSITIVE"

        elif (
            change_percent is not None
            and change_percent < 0
        ):
            direction = "NEGATIVE"

        return {
            "key": index_key,

            "name": (
                definition["name"]
            ),

            "short_name": (
                definition[
                    "short_name"
                ]
            ),

            "exchange": (
                definition[
                    "exchange"
                ]
            ),

            "symbol": (
                full_symbol
                or definition[
                    "candidates"
                ][0]
            ),

            "current_price": round(
                current_price,
                2,
            ),

            "previous_close": (
                round(
                    previous_close,
                    2,
                )
                if previous_close
                is not None
                else None
            ),

            "open": (
                round(
                    open_price,
                    2,
                )
                if open_price
                is not None
                else None
            ),

            "high": (
                round(
                    high_price,
                    2,
                )
                if high_price
                is not None
                else None
            ),

            "low": (
                round(
                    low_price,
                    2,
                )
                if low_price
                is not None
                else None
            ),

            "change": (
                round(
                    change,
                    2,
                )
                if change is not None
                else None
            ),

            "change_percent": (
                round(
                    change_percent,
                    2,
                )
                if change_percent
                is not None
                else None
            ),

            "direction": direction,

            "timestamp": (
                timestamp.isoformat()
            ),

            "updated_at": (
                utc_now().isoformat()
            ),

            "source": "FYERS",

            "verified": True,

            "stale": False,
        }

    # ========================================================
    # CACHE KEYS
    # ========================================================

    @staticmethod
    def _index_cache_key(
        index_key: str,
    ) -> str:

        return build_cache_key(
            "index",
            index_key,
            prefix="market-index",
        )

    @staticmethod
    def _dashboard_cache_key(
    ) -> str:

        return build_cache_key(
            "dashboard-indices",
            prefix="market-index",
        )

    # ========================================================
    # CACHE INDEX
    # ========================================================

    def _cache_index(
        self,
        index_data: dict[str, Any],
    ) -> None:

        index_key = clean_text(
            index_data.get(
                "key"
            )
        )

        if not index_key:
            return

        self.cache_service.set(
            self._index_cache_key(
                index_key
            ),
            index_data,
            ttl_seconds=(
                self.CACHE_SECONDS
            ),
        )

        stale_key = (
            "market-index-stale:"
            f"{index_key}"
        )

        self.cache_service.set(
            stale_key,
            index_data,
            ttl_seconds=(
                self.STALE_FALLBACK_SECONDS
            ),
        )

    # ========================================================
    # GET CACHED INDEX
    # ========================================================

    def _get_cached_index(
        self,
        index_key: str,
        *,
        allow_stale: bool = False,
    ) -> dict[str, Any] | None:

        cached = (
            self.cache_service.get(
                self._index_cache_key(
                    index_key
                )
            )
        )

        if isinstance(
            cached,
            dict,
        ):
            return cached

        if allow_stale:

            stale = (
                self.cache_service.get(
                    (
                        "market-index-stale:"
                        f"{index_key}"
                    )
                )
            )

            if isinstance(
                stale,
                dict,
            ):

                stale_result = dict(
                    stale
                )

                stale_result[
                    "stale"
                ] = True

                stale_result[
                    "verified"
                ] = False

                return stale_result

        return None

    # ========================================================
    # SAFE FYERS SYMBOL BATCH
    # ========================================================

    def _fetch_symbol_batch(
        self,
        access_token: str,
        symbols: Iterable[str],
    ) -> list[dict[str, Any]]:
        """
        Safely fetch FYERS quote data.

        Flow:
        1. Clean and deduplicate symbols.
        2. Try normal batch request first.
        3. If FYERS rejects entire batch,
           automatically retry each symbol individually.
        4. Skip only bad/unavailable symbols.
        5. Never create estimated or dummy market data.
        """

        clean_symbols: list[
            str
        ] = []

        for symbol in symbols:

            normalized = (
                self._normalize_full_symbol(
                    symbol
                )
            )

            if (
                normalized
                and normalized
                not in clean_symbols
            ):
                clean_symbols.append(
                    normalized
                )

        if not clean_symbols:
            return []

        # ====================================================
        # FIRST TRY: NORMAL BATCH REQUEST
        # ====================================================

        started_at = utc_now()

        try:

            response = (
                self.fyers_service.get_quotes(
                    access_token,
                    clean_symbols,
                )
            )

            duration_ms = (
                (
                    utc_now()
                    - started_at
                )
                .total_seconds()
                * 1000
            )

            quote_items = (
                self._extract_quote_items(
                    response
                )
            )

            log_api_call(
                logger,
                service=(
                    "index_service"
                ),
                endpoint="quotes",
                status="success",
                duration_ms=(
                    duration_ms
                ),
                requested_symbols=(
                    len(
                        clean_symbols
                    )
                ),
            )

            logger.info(
                (
                    "FYERS index batch "
                    "quote success | "
                    "requested=%s | "
                    "received=%s"
                ),
                len(
                    clean_symbols
                ),
                len(
                    quote_items
                ),
                extra=build_log_extra(
                    component=(
                        "index_service"
                    ),
                    event=(
                        "index_batch_success"
                    ),
                    status="success",
                    requested_symbols=(
                        len(
                            clean_symbols
                        )
                    ),
                    received_quotes=(
                        len(
                            quote_items
                        )
                    ),
                ),
            )

            return quote_items

        except FyersAuthenticationError:
            raise

        except Exception as (
            batch_exception
        ):

            duration_ms = (
                (
                    utc_now()
                    - started_at
                )
                .total_seconds()
                * 1000
            )

            logger.warning(
                (
                    "FYERS index batch "
                    "quote failed; "
                    "switching to individual "
                    "symbol fallback | "
                    "symbols=%s | error=%s"
                ),
                clean_symbols,
                batch_exception,
                extra=build_log_extra(
                    component=(
                        "index_service"
                    ),
                    event=(
                        "index_batch_fallback"
                    ),
                    status="warning",
                    requested_symbols=(
                        len(
                            clean_symbols
                        )
                    ),
                    duration_ms=round(
                        duration_ms,
                        2,
                    ),
                    error=str(
                        batch_exception
                    ),
                ),
            )

        # ====================================================
        # FALLBACK: ONE SYMBOL AT A TIME
        # ====================================================

        collected_items: list[
            dict[str, Any]
        ] = []

        successful_symbols: list[
            str
        ] = []

        failed_symbols: list[
            str
        ] = []

        for symbol in clean_symbols:

            symbol_started_at = (
                utc_now()
            )

            try:

                response = (
                    self.fyers_service.get_quotes(
                        access_token,
                        [symbol],
                    )
                )

                symbol_duration_ms = (
                    (
                        utc_now()
                        - symbol_started_at
                    )
                    .total_seconds()
                    * 1000
                )

                quote_items = (
                    self._extract_quote_items(
                        response
                    )
                )

                if not quote_items:

                    failed_symbols.append(
                        symbol
                    )

                    logger.warning(
                        (
                            "FYERS returned no "
                            "quote data for "
                            "index symbol | "
                            "symbol=%s"
                        ),
                        symbol,
                        extra=build_log_extra(
                            component=(
                                "index_service"
                            ),
                            event=(
                                "index_symbol_empty"
                            ),
                            status="warning",
                            candidate_symbol=(
                                symbol
                            ),
                        ),
                    )

                    continue

                collected_items.extend(
                    quote_items
                )

                successful_symbols.append(
                    symbol
                )

                log_api_call(
                    logger,
                    service=(
                        "index_service"
                    ),
                    endpoint="quotes",
                    status="success",
                    duration_ms=(
                        symbol_duration_ms
                    ),
                    requested_symbols=1,
                )

                logger.info(
                    (
                        "FYERS individual "
                        "index quote success | "
                        "symbol=%s"
                    ),
                    symbol,
                    extra=build_log_extra(
                        component=(
                            "index_service"
                        ),
                        event=(
                            "index_symbol_success"
                        ),
                        status="success",
                        candidate_symbol=(
                            symbol
                        ),
                    ),
                )

            except FyersAuthenticationError:
                raise

            except Exception as (
                symbol_exception
            ):

                failed_symbols.append(
                    symbol
                )

                logger.warning(
                    (
                        "FYERS index symbol "
                        "failed and was "
                        "skipped | "
                        "symbol=%s | "
                        "error=%s"
                    ),
                    symbol,
                    symbol_exception,
                    extra=build_log_extra(
                        component=(
                            "index_service"
                        ),
                        event=(
                            "index_symbol_failed"
                        ),
                        status="warning",
                        candidate_symbol=(
                            symbol
                        ),
                        error=str(
                            symbol_exception
                        ),
                    ),
                )

        # ====================================================
        # FALLBACK SUMMARY
        # ====================================================

        logger.info(
            (
                "FYERS index fallback "
                "completed | "
                "success=%s | "
                "failed=%s | "
                "quotes=%s"
            ),
            successful_symbols,
            failed_symbols,
            len(
                collected_items
            ),
            extra=build_log_extra(
                component=(
                    "index_service"
                ),
                event=(
                    "index_fallback_complete"
                ),
                status=(
                    "success"
                    if collected_items
                    else "failed"
                ),
                successful_count=(
                    len(
                        successful_symbols
                    )
                ),
                failed_count=(
                    len(
                        failed_symbols
                    )
                ),
            ),
        )

        return collected_items

    # ========================================================
    # FETCH PRIMARY INDICES
    # ========================================================

    def _fetch_primary_indices(
        self,
        access_token: str,
        index_keys: Iterable[str],
    ) -> dict[str, dict[str, Any]]:

        requested_keys = [
            key
            for key in index_keys
            if key
            in self.INDEX_DEFINITIONS
        ]

        if not requested_keys:
            return {}

        primary_symbols = [
            self.INDEX_DEFINITIONS[
                key
            ]["candidates"][0]
            for key in requested_keys
        ]

        results: dict[
            str,
            dict[str, Any],
        ] = {}

        try:

            quote_items = (
                self._fetch_symbol_batch(
                    access_token,
                    primary_symbols,
                )
            )

            for item in quote_items:

                normalized = (
                    self._normalize_index_quote(
                        item
                    )
                )

                if normalized is None:
                    continue

                results[
                    normalized["key"]
                ] = normalized

        except FyersAuthenticationError:
            raise

        except Exception as exception:

            log_exception(
                logger,
                (
                    "Primary index "
                    "quote batch failed"
                ),
                exception=exception,
                component=(
                    "index_service"
                ),
                error_code=(
                    "INDEX_PRIMARY_BATCH_FAILED"
                ),
            )

        return results

    # ========================================================
    # FETCH INDEX WITH CANDIDATES
    # ========================================================

    def _fetch_index_with_candidates(
        self,
        access_token: str,
        index_key: str,
    ) -> dict[str, Any] | None:

        definition = (
            self.INDEX_DEFINITIONS[
                index_key
            ]
        )

        for candidate_symbol in (
            definition["candidates"]
        ):

            try:

                quote_items = (
                    self._fetch_symbol_batch(
                        access_token,
                        [candidate_symbol],
                    )
                )

                for item in quote_items:

                    normalized = (
                        self._normalize_index_quote(
                            item,
                            fallback_index_key=(
                                index_key
                            ),
                        )
                    )

                    if (
                        normalized
                        is not None
                    ):
                        return normalized

            except FyersAuthenticationError:
                raise

            except Exception as exception:

                logger.warning(
                    (
                        "Index candidate "
                        "failed | "
                        "symbol=%s | "
                        "index=%s | "
                        "error=%s"
                    ),
                    candidate_symbol,
                    index_key,
                    exception,
                    extra=build_log_extra(
                        component=(
                            "index_service"
                        ),
                        event=(
                            "index_candidate_failed"
                        ),
                        status="warning",
                        index_key=(
                            index_key
                        ),
                        candidate_symbol=(
                            candidate_symbol
                        ),
                        error=str(
                            exception
                        ),
                    ),
                )

        return None

    # ========================================================
    # GET SINGLE INDEX
    # ========================================================

    def get_index(
        self,
        access_token: str,
        index_key: str,
        *,
        force_refresh: bool = False,
        allow_stale_on_error: (
            bool
        ) = True,
    ) -> dict[str, Any]:

        normalized_key = (
            self.normalize_index_key(
                index_key
            )
        )

        if normalized_key is None:
            raise ValueError(
                (
                    "Unsupported index: "
                    f"{index_key}"
                )
            )

        if not force_refresh:

            cached = (
                self._get_cached_index(
                    normalized_key
                )
            )

            if cached is not None:
                return cached

        with self._refresh_lock:

            if not force_refresh:

                cached = (
                    self._get_cached_index(
                        normalized_key
                    )
                )

                if cached is not None:
                    return cached

            try:

                index_data = (
                    self._fetch_index_with_candidates(
                        access_token,
                        normalized_key,
                    )
                )

                if index_data is None:

                    raise (
                        IndexDataUnavailableError(
                            (
                                "No valid live "
                                "data was returned "
                                "for "
                                f"{normalized_key}."
                            )
                        )
                    )

                self._cache_index(
                    index_data
                )

                return index_data

            except (
                FyersAPIError,
                FyersAuthenticationError,
                IndexDataError,
            ) as exception:

                if (
                    allow_stale_on_error
                ):

                    stale = (
                        self._get_cached_index(
                            normalized_key,
                            allow_stale=True,
                        )
                    )

                    if stale is not None:
                        return stale

                raise (
                    IndexDataUnavailableError(
                        (
                            "Live index data is "
                            "unavailable for "
                            f"{normalized_key}."
                        )
                    )
                ) from exception

    # ========================================================
    # GET DASHBOARD INDICES
    # ========================================================

    def get_dashboard_indices(
        self,
        access_token: str,
        *,
        force_refresh: bool = False,
        allow_stale_on_error: (
            bool
        ) = True,
    ) -> list[dict[str, Any]]:

        dashboard_cache_key = (
            self._dashboard_cache_key()
        )

        # ----------------------------------------------------
        # FIRST CACHE CHECK
        # ----------------------------------------------------

        if not force_refresh:

            cached_dashboard = (
                self.cache_service.get(
                    dashboard_cache_key
                )
            )

            if (
                isinstance(
                    cached_dashboard,
                    list,
                )
                and cached_dashboard
            ):
                return cached_dashboard

        # ----------------------------------------------------
        # REFRESH LOCK
        # ----------------------------------------------------

        with self._refresh_lock:

            if not force_refresh:

                cached_dashboard = (
                    self.cache_service.get(
                        dashboard_cache_key
                    )
                )

                if (
                    isinstance(
                        cached_dashboard,
                        list,
                    )
                    and cached_dashboard
                ):
                    return (
                        cached_dashboard
                    )

            requested_keys = list(
                self.DEFAULT_INDEX_ORDER
            )

            # ------------------------------------------------
            # PRIMARY SYMBOL REQUEST
            # ------------------------------------------------

            live_results = (
                self._fetch_primary_indices(
                    access_token,
                    requested_keys,
                )
            )

            # ------------------------------------------------
            # FIND MISSING INDICES
            # ------------------------------------------------

            missing_keys = [
                key
                for key in requested_keys
                if key not in live_results
            ]

            # ------------------------------------------------
            # TRY ALTERNATE SYMBOLS
            # ------------------------------------------------

            for missing_key in (
                missing_keys
            ):

                try:

                    alternate_result = (
                        self._fetch_index_with_candidates(
                            access_token,
                            missing_key,
                        )
                    )

                    if (
                        alternate_result
                        is not None
                    ):

                        live_results[
                            missing_key
                        ] = (
                            alternate_result
                        )

                except FyersAuthenticationError:
                    raise

                except Exception as exception:

                    logger.warning(
                        (
                            "Alternate index "
                            "lookup failed | "
                            "index=%s | "
                            "error=%s"
                        ),
                        missing_key,
                        exception,
                    )

            # ------------------------------------------------
            # BUILD DASHBOARD RESULT
            # ------------------------------------------------

            dashboard_results: list[
                dict[str, Any]
            ] = []

            for index_key in (
                requested_keys
            ):

                index_data = (
                    live_results.get(
                        index_key
                    )
                )

                if (
                    index_data
                    is not None
                ):

                    self._cache_index(
                        index_data
                    )

                    dashboard_results.append(
                        index_data
                    )

                    continue

                # --------------------------------------------
                # OPTIONAL STALE FALLBACK
                # --------------------------------------------

                if (
                    allow_stale_on_error
                ):

                    stale_result = (
                        self._get_cached_index(
                            index_key,
                            allow_stale=True,
                        )
                    )

                    if (
                        stale_result
                        is not None
                    ):
                        dashboard_results.append(
                            stale_result
                        )

            # ------------------------------------------------
            # DASHBOARD CACHE
            # ------------------------------------------------

            if dashboard_results:

                self.cache_service.set(
                    dashboard_cache_key,
                    dashboard_results,
                    ttl_seconds=(
                        self.CACHE_SECONDS
                    ),
                )

            return dashboard_results

    # ========================================================
    # REFRESH DASHBOARD
    # ========================================================

    def refresh_dashboard_indices(
        self,
        access_token: str,
    ) -> dict[str, Any]:

        started_at = utc_now()

        try:

            indices = (
                self.get_dashboard_indices(
                    access_token,
                    force_refresh=True,
                    allow_stale_on_error=True,
                )
            )

            verified_count = sum(
                1
                for item in indices
                if (
                    item.get(
                        "verified"
                    )
                    is True
                    and not item.get(
                        "stale"
                    )
                )
            )

            stale_count = sum(
                1
                for item in indices
                if item.get(
                    "stale"
                )
                is True
            )

            duration_ms = (
                (
                    utc_now()
                    - started_at
                )
                .total_seconds()
                * 1000
            )

            return {
                "success": bool(
                    indices
                ),

                "indices": indices,

                "total_count": len(
                    indices
                ),

                "verified_count": (
                    verified_count
                ),

                "stale_count": (
                    stale_count
                ),

                "duration_ms": round(
                    duration_ms,
                    2,
                ),

                "refreshed_at": (
                    utc_now()
                    .isoformat()
                ),
            }

        except Exception as exception:

            log_exception(
                logger,
                (
                    "Index dashboard "
                    "refresh failed"
                ),
                exception=exception,
                component=(
                    "index_service"
                ),
                error_code=(
                    "INDEX_REFRESH_FAILED"
                ),
            )

            return {
                "success": False,
                "indices": [],
                "total_count": 0,
                "verified_count": 0,
                "stale_count": 0,
                "error": str(
                    exception
                ),
                "refreshed_at": (
                    utc_now()
                    .isoformat()
                ),
            }

    # ========================================================
    # CLEAR INDEX CACHE
    # ========================================================

    def clear_index_cache(
        self,
    ) -> int:

        deleted_count = 0

        for index_key in (
            self.INDEX_DEFINITIONS.keys()
        ):

            keys = (
                self._index_cache_key(
                    index_key
                ),
                (
                    "market-index-stale:"
                    f"{index_key}"
                ),
            )

            for key in keys:

                if (
                    self.cache_service.delete(
                        key
                    )
                ):
                    deleted_count += 1

        if self.cache_service.delete(
            self._dashboard_cache_key()
        ):
            deleted_count += 1

        return deleted_count

    # ========================================================
    # HEALTH
    # ========================================================

    def health(
        self,
        access_token: (
            str | None
        ) = None,
    ) -> dict[str, Any]:

        configured = bool(
            self.fyers_service
            .configuration_status()
            .get(
                "configured",
                False,
            )
        )

        authenticated = False
        live_index_count = 0

        normalized_token = (
            clean_text(
                access_token
            )
        )

        if normalized_token:

            token_status = (
                self.fyers_service
                .validate_access_token(
                    normalized_token
                )
            )

            authenticated = bool(
                token_status.get(
                    "valid"
                )
            )

            if authenticated:

                try:

                    live_indices = (
                        self.get_dashboard_indices(
                            normalized_token,
                            allow_stale_on_error=False,
                        )
                    )

                    live_index_count = (
                        len(
                            live_indices
                        )
                    )

                except Exception:
                    live_index_count = 0

        healthy = (
            configured
            and (
                not normalized_token
                or authenticated
            )
        )

        return {
            "service": (
                "Index Service"
            ),

            "status": (
                "healthy"
                if healthy
                else "unhealthy"
            ),

            "is_healthy": (
                healthy
            ),

            "configured": (
                configured
            ),

            "authenticated": (
                authenticated
            ),

            "live_index_count": (
                live_index_count
            ),

            "supported_indices": (
                self.get_supported_indices()
            ),

            "cache_seconds": (
                self.CACHE_SECONDS
            ),

            "checked_at": (
                utc_now()
                .isoformat()
            ),
        }


# ============================================================
# GLOBAL INSTANCE
# ============================================================

_global_index_service: (
    IndexService | None
) = None

_global_index_lock = (
    threading.Lock()
)


def get_index_service(
) -> IndexService:

    global _global_index_service

    if (
        _global_index_service
        is not None
    ):
        return (
            _global_index_service
        )

    with _global_index_lock:

        if (
            _global_index_service
            is None
        ):
            _global_index_service = (
                IndexService()
            )

    return (
        _global_index_service
    )
