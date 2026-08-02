from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from services.cache_service import CacheService, get_cache_service
from services.fyers_service import (
    FyersAPIError,
    FyersAuthenticationError,
    FyersService,
    get_fyers_service,
)
from utils.helpers import (
    build_cache_key,
    chunked,
    clean_text,
    normalize_symbol,
    normalize_timeframe,
    parse_datetime,
    percentage_change,
    safe_float,
    safe_int,
    to_fyers_symbol,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_api_call,
    log_exception,
)
from utils.validators import (
    validate_candle_series,
    validate_quote_data,
)


logger = get_logger("services.market_data_service")


class MarketDataError(RuntimeError):
    """Raised when verified market data cannot be produced."""


class MarketDataUnavailableError(MarketDataError):
    """Raised when live or historical market data is unavailable."""


class MarketDataValidationError(MarketDataError):
    """Raised when returned market data fails validation."""


class MarketDataService:
    """
    Verified market-data layer for Eagle Smart Scanner.

    Responsibilities:
    - Fetch live quotes from FYERS
    - Fetch historical OHLCV candles
    - Normalize different FYERS response formats
    - Validate price and candle data
    - Cache verified responses
    - Reject missing, malformed and stale data
    - Support bulk quote requests
    """

    QUOTE_CACHE_SECONDS = 12
    INDEX_CACHE_SECONDS = 8

    HISTORY_CACHE_SECONDS = {
        "15_30_days": 15 * 60,
        "3_month": 30 * 60,
        "6_month": 60 * 60,
        "1_year": 2 * 60 * 60,
        "3_year": 4 * 60 * 60,
    }

    HISTORY_DAYS = {
        "15_30_days": 320,
        "3_month": 450,
        "6_month": 650,
        "1_year": 1000,
        "3_year": 1800,
    }

    QUOTE_BATCH_SIZE = 40

    def __init__(
        self,
        *,
        fyers_service: FyersService | None = None,
        cache_service: CacheService | None = None,
    ) -> None:
        self.fyers_service = (
            fyers_service or get_fyers_service()
        )

        self.cache_service = (
            cache_service or get_cache_service()
        )

        self._quote_lock = threading.RLock()
        self._history_lock = threading.RLock()

    # ==========================================================
    # GENERAL HELPERS
    # ==========================================================

    @staticmethod
    def _normalize_fyers_symbol(
        symbol: Any,
    ) -> str:
        raw_symbol = clean_text(symbol).upper()

        if not raw_symbol:
            return ""

        if ":" in raw_symbol and "-" in raw_symbol:
            return raw_symbol

        return to_fyers_symbol(raw_symbol)

    @staticmethod
    def _extract_epoch_datetime(
        value: Any,
    ) -> datetime | None:
        parsed = parse_datetime(value)

        if parsed is not None:
            return parsed

        epoch_value = safe_int(value)

        if epoch_value is None:
            return None

        try:
            if epoch_value > 10_000_000_000:
                epoch_value = int(epoch_value / 1000)

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

    @staticmethod
    def _extract_response_data(
        response: dict[str, Any],
    ) -> Any:
        if not isinstance(response, dict):
            return None

        for key in (
            "d",
            "data",
            "quotes",
            "candles",
        ):
            if key in response:
                return response[key]

        return response

    # ==========================================================
    # QUOTE PARSING
    # ==========================================================

    def _normalize_quote_item(
        self,
        item: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None

        values = item.get("v")

        if not isinstance(values, dict):
            values = item.get("data")

        if not isinstance(values, dict):
            values = item

        raw_symbol = (
            item.get("n")
            or item.get("symbol")
            or values.get("symbol")
            or values.get("short_name")
        )

        symbol = normalize_symbol(raw_symbol)

        current_price = safe_float(
            values.get("lp")
            or values.get("ltp")
            or values.get("last_price")
            or values.get("current_price")
        )

        previous_close = safe_float(
            values.get("prev_close_price")
            or values.get("previous_close")
            or values.get("prev_close")
            or values.get("close")
        )

        open_price = safe_float(
            values.get("open_price")
            or values.get("open")
            or values.get("o")
        )

        high_price = safe_float(
            values.get("high_price")
            or values.get("high")
            or values.get("h")
        )

        low_price = safe_float(
            values.get("low_price")
            or values.get("low")
            or values.get("l")
        )

        volume = safe_float(
            values.get("volume")
            or values.get("vol_traded_today")
            or values.get("vol")
            or values.get("v")
        )

        change = safe_float(
            values.get("ch")
            or values.get("change")
        )

        change_percent = safe_float(
            values.get("chp")
            or values.get("change_percent")
            or values.get("percent_change")
        )

        if (
            change_percent is None
            and current_price is not None
            and previous_close not in {None, 0.0}
        ):
            change_percent = percentage_change(
                current_price,
                previous_close,
            )

        if (
            change is None
            and current_price is not None
            and previous_close is not None
        ):
            change = current_price - previous_close

        timestamp_value = (
            values.get("exchange_timestamp")
            or values.get("timestamp")
            or values.get("last_traded_time")
            or values.get("tt")
            or item.get("timestamp")
        )

        parsed_timestamp = (
            self._extract_epoch_datetime(
                timestamp_value
            )
        )

        if parsed_timestamp is None:
            parsed_timestamp = utc_now()

        quote = {
            "symbol": symbol,
            "fyers_symbol": (
                self._normalize_fyers_symbol(
                    raw_symbol
                )
            ),
            "current_price": current_price,
            "previous_close": previous_close,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "volume": volume,
            "change": (
                round(change, 2)
                if change is not None
                else None
            ),
            "change_percent": (
                round(change_percent, 2)
                if change_percent is not None
                else None
            ),
            "timestamp": parsed_timestamp.isoformat(),
            "updated_at": utc_now().isoformat(),
            "source": "FYERS",
        }

        validation = validate_quote_data(
            quote,
            require_fresh=False,
        )

        if not validation.is_valid:
            logger.warning(
                "Quote rejected for %s: %s",
                symbol or "unknown",
                "; ".join(validation.errors),
                extra=build_log_extra(
                    component="market_data_service",
                    event="quote_rejected",
                    status="rejected",
                    symbol=symbol,
                    validation_errors=validation.errors,
                ),
            )

            return None

        return {
            **quote,
            **validation.cleaned_data,
            "change": quote["change"],
            "change_percent": quote[
                "change_percent"
            ],
            "fyers_symbol": quote[
                "fyers_symbol"
            ],
            "source": "FYERS",
            "updated_at": quote["updated_at"],
        }

    def _parse_quotes_response(
        self,
        response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        response_data = self._extract_response_data(
            response
        )

        if isinstance(response_data, dict):
            possible_list = (
                response_data.get("d")
                or response_data.get("quotes")
                or response_data.get("data")
            )

            if isinstance(possible_list, list):
                response_data = possible_list
            else:
                response_data = [
                    response_data
                ]

        if not isinstance(response_data, list):
            raise MarketDataValidationError(
                "FYERS quote response does not contain a valid list."
            )

        quotes: list[dict[str, Any]] = []

        for item in response_data:
            normalized_quote = (
                self._normalize_quote_item(item)
            )

            if normalized_quote is not None:
                quotes.append(normalized_quote)

        if not quotes:
            raise MarketDataUnavailableError(
                "No valid stock quote was returned."
            )

        return quotes

    # ==========================================================
    # LIVE QUOTES
    # ==========================================================

    def get_quote(
        self,
        access_token: str,
        symbol: str,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(
            symbol
        )

        if not normalized_symbol:
            raise ValueError(
                "A valid stock symbol is required."
            )

        cache_key = build_cache_key(
            "quote",
            normalized_symbol,
            prefix="market",
        )

        if not force_refresh:
            cached_quote = self.cache_service.get(
                cache_key
            )

            if isinstance(cached_quote, dict):
                return cached_quote

        with self._quote_lock:
            if not force_refresh:
                cached_quote = (
                    self.cache_service.get(
                        cache_key
                    )
                )

                if isinstance(
                    cached_quote,
                    dict,
                ):
                    return cached_quote

            started_at = utc_now()

            try:
                response = (
                    self.fyers_service.get_quotes(
                        access_token,
                        [normalized_symbol],
                    )
                )

                quotes = (
                    self._parse_quotes_response(
                        response
                    )
                )

                quote = quotes[0]

                self.cache_service.set(
                    cache_key,
                    quote,
                    ttl_seconds=(
                        self.QUOTE_CACHE_SECONDS
                    ),
                )

                duration_ms = (
                    utc_now() - started_at
                ).total_seconds() * 1000

                log_api_call(
                    logger,
                    service="market_data_service",
                    endpoint="quotes",
                    status="success",
                    duration_ms=duration_ms,
                    symbol=normalized_symbol,
                )

                return quote

            except (
                FyersAPIError,
                FyersAuthenticationError,
                MarketDataError,
            ):
                raise

            except Exception as exception:
                log_exception(
                    logger,
                    "Unable to fetch stock quote",
                    exception=exception,
                    symbol=normalized_symbol,
                    component="market_data_service",
                    error_code="QUOTE_FETCH_FAILED",
                )

                raise MarketDataUnavailableError(
                    f"Live quote unavailable for {normalized_symbol}."
                ) from exception

    def get_bulk_quotes(
        self,
        access_token: str,
        symbols: Iterable[str],
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        normalized_symbols: list[str] = []

        for symbol in symbols:
            normalized_symbol = normalize_symbol(
                symbol
            )

            if (
                normalized_symbol
                and normalized_symbol
                not in normalized_symbols
            ):
                normalized_symbols.append(
                    normalized_symbol
                )

        if not normalized_symbols:
            return []

        results: dict[str, dict[str, Any]] = {}
        missing_symbols: list[str] = []

        for symbol in normalized_symbols:
            cache_key = build_cache_key(
                "quote",
                symbol,
                prefix="market",
            )

            cached_quote = (
                None
                if force_refresh
                else self.cache_service.get(
                    cache_key
                )
            )

            if isinstance(cached_quote, dict):
                results[symbol] = cached_quote
            else:
                missing_symbols.append(symbol)

        for symbol_batch in chunked(
            missing_symbols,
            self.QUOTE_BATCH_SIZE,
        ):
            try:
                response = (
                    self.fyers_service.get_quotes(
                        access_token,
                        symbol_batch,
                    )
                )

                quotes = (
                    self._parse_quotes_response(
                        response
                    )
                )

                for quote in quotes:
                    symbol = normalize_symbol(
                        quote.get("symbol")
                    )

                    if not symbol:
                        continue

                    results[symbol] = quote

                    cache_key = build_cache_key(
                        "quote",
                        symbol,
                        prefix="market",
                    )

                    self.cache_service.set(
                        cache_key,
                        quote,
                        ttl_seconds=(
                            self.QUOTE_CACHE_SECONDS
                        ),
                    )

            except Exception as exception:
                log_exception(
                    logger,
                    "Bulk quote batch failed",
                    exception=exception,
                    component="market_data_service",
                    error_code="BULK_QUOTE_FAILED",
                    batch_size=len(symbol_batch),
                )

                continue

        return [
            results[symbol]
            for symbol in normalized_symbols
            if symbol in results
        ]

    # ==========================================================
    # HISTORICAL CANDLES
    # ==========================================================

    def _normalize_candle(
        self,
        candle: Any,
    ) -> dict[str, Any] | None:
        if isinstance(candle, dict):
            timestamp = (
                candle.get("timestamp")
                or candle.get("time")
                or candle.get("date")
            )

            open_price = candle.get("open")
            high_price = candle.get("high")
            low_price = candle.get("low")
            close_price = candle.get("close")
            volume = candle.get("volume")

        elif (
            isinstance(candle, (list, tuple))
            and len(candle) >= 6
        ):
            timestamp = candle[0]
            open_price = candle[1]
            high_price = candle[2]
            low_price = candle[3]
            close_price = candle[4]
            volume = candle[5]

        else:
            return None

        parsed_timestamp = (
            self._extract_epoch_datetime(
                timestamp
            )
        )

        open_number = safe_float(open_price)
        high_number = safe_float(high_price)
        low_number = safe_float(low_price)
        close_number = safe_float(close_price)
        volume_number = safe_float(
            volume,
            default=0.0,
        )

        if (
            parsed_timestamp is None
            or open_number is None
            or high_number is None
            or low_number is None
            or close_number is None
            or volume_number is None
        ):
            return None

        if min(
            open_number,
            high_number,
            low_number,
            close_number,
        ) <= 0:
            return None

        if high_number < max(
            open_number,
            close_number,
            low_number,
        ):
            return None

        if low_number > min(
            open_number,
            close_number,
            high_number,
        ):
            return None

        if volume_number < 0:
            return None

        return {
            "timestamp": (
                parsed_timestamp.isoformat()
            ),
            "date": (
                parsed_timestamp
                .astimezone(timezone.utc)
                .date()
                .isoformat()
            ),
            "open": round(open_number, 2),
            "high": round(high_number, 2),
            "low": round(low_number, 2),
            "close": round(close_number, 2),
            "volume": volume_number,
        }

    def _parse_history_response(
        self,
        response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        candles_data = response.get("candles")

        if candles_data is None:
            response_data = response.get("data")

            if isinstance(response_data, dict):
                candles_data = (
                    response_data.get("candles")
                )
            elif isinstance(response_data, list):
                candles_data = response_data

        if not isinstance(candles_data, list):
            raise MarketDataValidationError(
                "FYERS history response does not contain candles."
            )

        normalized_candles: list[
            dict[str, Any]
        ] = []

        seen_timestamps: set[str] = set()

        for candle in candles_data:
            normalized_candle = (
                self._normalize_candle(candle)
            )

            if normalized_candle is None:
                continue

            timestamp = normalized_candle[
                "timestamp"
            ]

            if timestamp in seen_timestamps:
                continue

            seen_timestamps.add(timestamp)

            normalized_candles.append(
                normalized_candle
            )

        normalized_candles.sort(
            key=lambda item: item["timestamp"]
        )

        if not normalized_candles:
            raise MarketDataUnavailableError(
                "No valid historical candles were returned."
            )

        return normalized_candles

    def get_history(
        self,
        access_token: str,
        symbol: str,
        *,
        timeframe: str = "3_month",
        force_refresh: bool = False,
        resolution: str = "D",
    ) -> list[dict[str, Any]]:
        normalized_symbol = normalize_symbol(
            symbol
        )

        normalized_timeframe = (
            normalize_timeframe(timeframe)
        )

        if not normalized_symbol:
            raise ValueError(
                "A valid stock symbol is required."
            )

        cache_key = build_cache_key(
            "history",
            normalized_symbol,
            normalized_timeframe,
            resolution,
            prefix="market",
        )

        if not force_refresh:
            cached_candles = (
                self.cache_service.get(
                    cache_key
                )
            )

            if isinstance(
                cached_candles,
                list,
            ) and cached_candles:
                return cached_candles

        with self._history_lock:
            if not force_refresh:
                cached_candles = (
                    self.cache_service.get(
                        cache_key
                    )
                )

                if isinstance(
                    cached_candles,
                    list,
                ) and cached_candles:
                    return cached_candles

            history_days = (
                self.HISTORY_DAYS.get(
                    normalized_timeframe,
                    450,
                )
            )

            range_to_date = utc_now().date()

            range_from_date = (
                range_to_date
                - timedelta(days=history_days)
            )

            try:
                response = (
                    self.fyers_service.get_history(
                        access_token,
                        symbol=normalized_symbol,
                        resolution=resolution,
                        range_from=(
                            range_from_date.isoformat()
                        ),
                        range_to=(
                            range_to_date.isoformat()
                        ),
                        date_format="1",
                        continuous="1",
                    )
                )

                candles = (
                    self._parse_history_response(
                        response
                    )
                )

                validation = (
                    validate_candle_series(
                        candles,
                        timeframe=(
                            normalized_timeframe
                        ),
                    )
                )

                if not validation.is_valid:
                    raise (
                        MarketDataValidationError(
                            "; ".join(
                                validation.errors
                            )
                        )
                    )

                verified_candles = (
                    validation.cleaned_data[
                        "candles"
                    ]
                )

                cache_seconds = (
                    self.HISTORY_CACHE_SECONDS.get(
                        normalized_timeframe,
                        30 * 60,
                    )
                )

                self.cache_service.set(
                    cache_key,
                    verified_candles,
                    ttl_seconds=cache_seconds,
                )

                return verified_candles

            except (
                FyersAPIError,
                FyersAuthenticationError,
                MarketDataError,
            ):
                raise

            except Exception as exception:
                log_exception(
                    logger,
                    "Unable to fetch historical candles",
                    exception=exception,
                    symbol=normalized_symbol,
                    timeframe=(
                        normalized_timeframe
                    ),
                    component=(
                        "market_data_service"
                    ),
                    error_code=(
                        "HISTORY_FETCH_FAILED"
                    ),
                )

                raise MarketDataUnavailableError(
                    (
                        "Historical data unavailable "
                        f"for {normalized_symbol}."
                    )
                ) from exception

    # ==========================================================
    # COMBINED STOCK DATA
    # ==========================================================

    def get_stock_market_data(
        self,
        access_token: str,
        symbol: str,
        *,
        timeframe: str = "3_month",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(
            symbol
        )

        normalized_timeframe = (
            normalize_timeframe(timeframe)
        )

        quote = self.get_quote(
            access_token,
            normalized_symbol,
            force_refresh=force_refresh,
        )

        candles = self.get_history(
            access_token,
            normalized_symbol,
            timeframe=normalized_timeframe,
            force_refresh=force_refresh,
        )

        if not candles:
            raise MarketDataUnavailableError(
                "Verified candle data is unavailable."
            )

        latest_candle = candles[-1]

        return {
            "symbol": normalized_symbol,
            "fyers_symbol": to_fyers_symbol(
                normalized_symbol
            ),
            "timeframe": normalized_timeframe,
            "quote": quote,
            "candles": candles,
            "latest_candle": latest_candle,
            "candle_count": len(candles),
            "current_price": quote.get(
                "current_price"
            ),
            "updated_at": utc_now().isoformat(),
            "source": "FYERS",
            "verified": True,
        }

    # ==========================================================
    # CACHE MANAGEMENT
    # ==========================================================

    def clear_symbol_cache(
        self,
        symbol: str,
    ) -> int:
        normalized_symbol = normalize_symbol(
            symbol
        )

        if not normalized_symbol:
            return 0

        deleted_count = 0

        for key in self.cache_service.list_keys():
            if normalized_symbol.casefold() in (
                key.casefold()
            ):
                if self.cache_service.delete(key):
                    deleted_count += 1

        return deleted_count

    # ==========================================================
    # HEALTH
    # ==========================================================

    def health(
        self,
        access_token: str | None = None,
    ) -> dict[str, Any]:
        token_available = bool(
            clean_text(access_token)
        )

        fyers_health = (
            self.fyers_service.health(
                access_token
                if token_available
                else None
            )
        )

        cache_health = (
            self.cache_service.health()
        )

        healthy = (
            bool(fyers_health.get("configured"))
            and bool(
                cache_health.get("is_healthy")
            )
        )

        if token_available:
            healthy = (
                healthy
                and bool(
                    fyers_health.get(
                        "authenticated"
                    )
                )
            )

        return {
            "service": "Market Data Service",
            "status": (
                "healthy"
                if healthy
                else "unhealthy"
            ),
            "is_healthy": healthy,
            "fyers": fyers_health,
            "cache": cache_health,
            "quote_cache_seconds": (
                self.QUOTE_CACHE_SECONDS
            ),
            "supported_timeframes": list(
                self.HISTORY_DAYS.keys()
            ),
            "checked_at": utc_now().isoformat(),
        }


_global_market_data_service: (
    MarketDataService | None
) = None

_global_market_data_lock = threading.Lock()


def get_market_data_service(
) -> MarketDataService:
    global _global_market_data_service

    if _global_market_data_service is not None:
        return _global_market_data_service

    with _global_market_data_lock:
        if _global_market_data_service is None:
            _global_market_data_service = (
                MarketDataService()
            )

    return _global_market_data_service
