from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd

from config import Config

from scanners.technical_scanner import (
    analyze_stock,
)

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

from utils.helpers import (
    build_cache_key,
    chunked,
    clean_text,
    normalize_symbol,
    percentage_change,
    safe_float,
    safe_int,
    to_fyers_symbol,
    utc_now,
)

from utils.logger import (
    build_log_extra,
    get_logger,
    log_exception,
)

from utils.validators import (
    validate_quote_data,
)


logger = get_logger(
    "services.market_data_service"
)


# ============================================================
# ERRORS
# ============================================================


class MarketDataError(
    RuntimeError
):
    """Base market-data error."""


class MarketDataUnavailableError(
    MarketDataError
):
    """Raised when verified market data is unavailable."""


class MarketDataValidationError(
    MarketDataError
):
    """Raised when returned market data fails validation."""


# ============================================================
# MARKET DATA SERVICE
# ============================================================


class MarketDataService:
    """
    Verified FYERS market-data bridge.

    Supported modes:

    INTRADAY
        Primary       = 5 minute
        Confirmation  = 15 minute
        Higher        = Daily

    BTST
        Primary       = 15 minute
        Confirmation  = 60 minute
        Higher        = Daily

    SWING
        Primary       = Daily
        Confirmation  = Weekly derived from Daily
        Higher        = Weekly derived from Daily

    Important:

    - Live displayed price comes from FYERS Quotes.
    - Technical candles come from FYERS History.
    - No fundamental data.
    - No synthetic / fake data.
    """

    # ========================================================
    # CACHE
    # ========================================================

    QUOTE_CACHE_SECONDS = 10

    INTRADAY_CANDLE_CACHE_SECONDS = 30

    BTST_CANDLE_CACHE_SECONDS = 120

    SWING_CANDLE_CACHE_SECONDS = 300

    QUOTE_BATCH_SIZE = 40


    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        *,
        fyers_service: (
            FyersService | None
        ) = None,
        cache_service: (
            CacheService | None
        ) = None,
    ) -> None:

        self.fyers_service = (
            fyers_service
            or get_fyers_service()
        )

        self.cache_service = (
            cache_service
            or get_cache_service()
        )

        self._quote_lock = (
            threading.RLock()
        )

        self._history_lock = (
            threading.RLock()
        )


    # ========================================================
    # HELPERS
    # ========================================================

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

            return value

        epoch_value = safe_int(
            value
        )

        if epoch_value is None:
            return None

        try:

            if (
                epoch_value
                > 10_000_000_000
            ):

                epoch_value = int(
                    epoch_value
                    / 1000
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


    @staticmethod
    def _normalize_fyers_symbol(
        symbol: Any,
    ) -> str:

        raw_symbol = (
            clean_text(
                symbol
            )
            .upper()
        )

        if not raw_symbol:
            return ""

        if (
            ":" in raw_symbol
            and "-" in raw_symbol
        ):

            return raw_symbol

        return to_fyers_symbol(
            raw_symbol
        )


    @staticmethod
    def _safe_sort_number(
        value: Any,
    ) -> float:

        number = safe_float(
            value,
            default=0.0,
        )

        return float(
            number
            or 0.0
        )


    # ========================================================
    # QUOTE NORMALIZATION
    # ========================================================

    def _normalize_quote_item(
        self,
        item: Any,
    ) -> dict[str, Any] | None:

        if not isinstance(
            item,
            dict,
        ):
            return None

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

        raw_symbol = (
            item.get("n")
            or item.get("symbol")
            or values.get("symbol")
            or values.get("short_name")
        )

        symbol = normalize_symbol(
            raw_symbol
        )

        if not symbol:
            return None

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

        open_price = safe_float(
            values.get(
                "open_price"
            )
            or values.get("open")
            or values.get("o")
        )

        high_price = safe_float(
            values.get(
                "high_price"
            )
            or values.get("high")
            or values.get("h")
        )

        low_price = safe_float(
            values.get(
                "low_price"
            )
            or values.get("low")
            or values.get("l")
        )

        volume = safe_float(
            values.get(
                "volume"
            )
            or values.get(
                "vol_traded_today"
            )
            or values.get(
                "vol"
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

        if (
            change_percent is None
            and current_price is not None
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

        if (
            change is None
            and current_price
            is not None
            and previous_close
            is not None
        ):

            change = (
                current_price
                - previous_close
            )

        if (
            current_price is None
            or current_price <= 0
        ):

            return None

        quote = {
            "symbol": (
                symbol
            ),

            "fyers_symbol": (
                self
                ._normalize_fyers_symbol(
                    raw_symbol
                )
            ),

            "current_price": (
                current_price
            ),

            "previous_close": (
                previous_close
            ),

            "open": (
                open_price
            ),

            "high": (
                high_price
            ),

            "low": (
                low_price
            ),

            "volume": (
                volume
            ),

            "change": (
                round(
                    change,
                    2,
                )
                if change
                is not None
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

            "updated_at": (
                utc_now()
                .isoformat()
            ),

            "source": "FYERS",
        }

        validation = (
            validate_quote_data(
                quote,
                require_fresh=False,
            )
        )

        if not validation.is_valid:

            logger.warning(
                (
                    "Quote rejected for "
                    "%s: %s"
                ),
                symbol,
                "; ".join(
                    validation.errors
                ),
                extra=build_log_extra(
                    component=(
                        "market_data_service"
                    ),
                    event=(
                        "quote_rejected"
                    ),
                    status="rejected",
                    symbol=symbol,
                    validation_errors=(
                        validation.errors
                    ),
                ),
            )

            return None

        return {
            **quote,
            **validation.cleaned_data,
            "source": "FYERS",
        }


    def _parse_quotes_response(
        self,
        response: dict[str, Any],
    ) -> list[dict[str, Any]]:

        if not isinstance(
            response,
            dict,
        ):

            raise (
                MarketDataValidationError(
                    (
                        "Invalid FYERS "
                        "quote response."
                    )
                )
            )

        response_data = (
            response.get(
                "d"
            )
        )

        if response_data is None:

            response_data = (
                response.get(
                    "data"
                )
            )

        if isinstance(
            response_data,
            dict,
        ):

            nested = (
                response_data.get("d")
                or response_data.get(
                    "quotes"
                )
                or response_data.get(
                    "data"
                )
            )

            if isinstance(
                nested,
                list,
            ):

                response_data = nested

            else:

                response_data = [
                    response_data
                ]

        if not isinstance(
            response_data,
            list,
        ):

            raise (
                MarketDataValidationError(
                    (
                        "Invalid FYERS "
                        "quote response."
                    )
                )
            )

        quotes: list[
            dict[str, Any]
        ] = []

        for item in response_data:

            normalized = (
                self
                ._normalize_quote_item(
                    item
                )
            )

            if normalized is not None:

                quotes.append(
                    normalized
                )

        if not quotes:

            raise (
                MarketDataUnavailableError(
                    (
                        "FYERS returned "
                        "no valid quote."
                    )
                )
            )

        return quotes


    # ========================================================
    # ONE QUOTE
    # ========================================================

    def get_quote(
        self,
        access_token: str,
        symbol: str,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:

        normalized_symbol = (
            normalize_symbol(
                symbol
            )
        )

        if not normalized_symbol:

            raise ValueError(
                (
                    "Valid stock "
                    "symbol required."
                )
            )

        cache_key = (
            build_cache_key(
                "quote",
                normalized_symbol,
                prefix="market",
            )
        )

        if not force_refresh:

            cached = (
                self.cache_service
                .get(
                    cache_key
                )
            )

            if isinstance(
                cached,
                dict,
            ):

                return cached

        with self._quote_lock:

            if not force_refresh:

                cached = (
                    self.cache_service
                    .get(
                        cache_key
                    )
                )

                if isinstance(
                    cached,
                    dict,
                ):

                    return cached

            try:

                response = (
                    self.fyers_service
                    .get_quotes(
                        access_token,
                        [
                            normalized_symbol
                        ],
                    )
                )

                quotes = (
                    self
                    ._parse_quotes_response(
                        response
                    )
                )

                quote = (
                    quotes[0]
                )

                self.cache_service.set(
                    cache_key,
                    quote,
                    ttl_seconds=(
                        self
                        .QUOTE_CACHE_SECONDS
                    ),
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
                    (
                        "Live quote "
                        "fetch failed"
                    ),
                    exception=exception,
                    symbol=(
                        normalized_symbol
                    ),
                    component=(
                        "market_data_service"
                    ),
                    error_code=(
                        "QUOTE_FETCH_FAILED"
                    ),
                )

                raise (
                    MarketDataUnavailableError(
                        (
                            "Verified live "
                            "quote unavailable "
                            "for "
                            f"{normalized_symbol}."
                        )
                    )
                ) from exception


    # ========================================================
    # BULK QUOTES
    # ========================================================

    def get_bulk_quotes(
        self,
        access_token: str,
        symbols: Iterable[str],
        *,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:

        normalized_symbols: list[
            str
        ] = []

        for symbol in symbols:

            clean_symbol = (
                normalize_symbol(
                    symbol
                )
            )

            if (
                clean_symbol
                and clean_symbol
                not in normalized_symbols
            ):

                normalized_symbols.append(
                    clean_symbol
                )

        if not normalized_symbols:
            return []

        results: dict[
            str,
            dict[str, Any],
        ] = {}

        missing: list[
            str
        ] = []

        for symbol in (
            normalized_symbols
        ):

            cache_key = (
                build_cache_key(
                    "quote",
                    symbol,
                    prefix="market",
                )
            )

            cached = (
                None
                if force_refresh
                else (
                    self.cache_service
                    .get(
                        cache_key
                    )
                )
            )

            if isinstance(
                cached,
                dict,
            ):

                results[
                    symbol
                ] = cached

            else:

                missing.append(
                    symbol
                )

        for batch in chunked(
            missing,
            self.QUOTE_BATCH_SIZE,
        ):

            try:

                response = (
                    self.fyers_service
                    .get_quotes(
                        access_token,
                        batch,
                    )
                )

                quotes = (
                    self
                    ._parse_quotes_response(
                        response
                    )
                )

                for quote in quotes:

                    symbol = (
                        normalize_symbol(
                            quote.get(
                                "symbol"
                            )
                        )
                    )

                    if not symbol:
                        continue

                    results[
                        symbol
                    ] = quote

                    cache_key = (
                        build_cache_key(
                            "quote",
                            symbol,
                            prefix="market",
                        )
                    )

                    self.cache_service.set(
                        cache_key,
                        quote,
                        ttl_seconds=(
                            self
                            .QUOTE_CACHE_SECONDS
                        ),
                    )

            except Exception as exception:

                log_exception(
                    logger,
                    (
                        "Bulk quote "
                        "request failed"
                    ),
                    exception=exception,
                    component=(
                        "market_data_service"
                    ),
                    error_code=(
                        "BULK_QUOTE_FAILED"
                    ),
                    batch_size=(
                        len(
                            batch
                        )
                    ),
                )

        return [
            results[
                symbol
            ]
            for symbol
            in normalized_symbols
            if symbol in results
        ]


    # ========================================================
    # CANDLE VALIDATION
    # ========================================================

    @staticmethod
    def _validate_candles(
        candles: list[
            dict[str, Any]
        ],
        *,
        minimum: int,
    ) -> list[
        dict[str, Any]
    ]:

        if not isinstance(
            candles,
            list,
        ):

            raise (
                MarketDataValidationError(
                    (
                        "Candle data "
                        "must be a list."
                    )
                )
            )

        valid: list[
            dict[str, Any]
        ] = []

        seen: set[
            int
        ] = set()

        for candle in candles:

            if not isinstance(
                candle,
                dict,
            ):
                continue

            try:

                timestamp = int(
                    candle[
                        "timestamp"
                    ]
                )

                open_price = float(
                    candle[
                        "open"
                    ]
                )

                high_price = float(
                    candle[
                        "high"
                    ]
                )

                low_price = float(
                    candle[
                        "low"
                    ]
                )

                close_price = float(
                    candle[
                        "close"
                    ]
                )

                volume = float(
                    candle.get(
                        "volume",
                        0.0,
                    )
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):

                continue

            if timestamp in seen:
                continue

            if min(
                open_price,
                high_price,
                low_price,
                close_price,
            ) <= 0:

                continue

            if (
                high_price
                < max(
                    open_price,
                    close_price,
                    low_price,
                )
            ):

                continue

            if (
                low_price
                > min(
                    open_price,
                    close_price,
                    high_price,
                )
            ):

                continue

            if volume < 0:
                continue

            seen.add(
                timestamp
            )

            valid.append(
                {
                    "timestamp": (
                        timestamp
                    ),
                    "open": (
                        open_price
                    ),
                    "high": (
                        high_price
                    ),
                    "low": (
                        low_price
                    ),
                    "close": (
                        close_price
                    ),
                    "volume": (
                        volume
                    ),
                }
            )

        valid.sort(
            key=lambda item: (
                item[
                    "timestamp"
                ]
            )
        )

        if (
            len(valid)
            < minimum
        ):

            raise (
                MarketDataUnavailableError(
                    (
                        f"Only {len(valid)} "
                        "valid candles "
                        "available; "
                        f"{minimum} required."
                    )
                )
            )

        return valid


    # ========================================================
    # DAILY -> WEEKLY
    # ========================================================

    @staticmethod
    def resample_daily_to_weekly(
        daily_candles: list[
            dict[str, Any]
        ],
    ) -> list[
        dict[str, Any]
    ]:

        if not daily_candles:
            return []

        dataframe = (
            pd.DataFrame(
                daily_candles
            )
        )

        dataframe[
            "datetime"
        ] = pd.to_datetime(
            dataframe[
                "timestamp"
            ],
            unit="s",
            utc=True,
        )

        dataframe = (
            dataframe
            .set_index(
                "datetime"
            )
            .sort_index()
        )

        weekly = (
            dataframe
            .resample(
                "W-FRI"
            )
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna(
                subset=[
                    "open",
                    "high",
                    "low",
                    "close",
                ]
            )
        )

        output: list[
            dict[str, Any]
        ] = []

        for (
            timestamp,
            row,
        ) in weekly.iterrows():

            output.append(
                {
                    "timestamp": int(
                        timestamp
                        .timestamp()
                    ),

                    "open": float(
                        row[
                            "open"
                        ]
                    ),

                    "high": float(
                        row[
                            "high"
                        ]
                    ),

                    "low": float(
                        row[
                            "low"
                        ]
                    ),

                    "close": float(
                        row[
                            "close"
                        ]
                    ),

                    "volume": float(
                        row[
                            "volume"
                        ]
                    ),
                }
            )

        return output


    # ========================================================
    # CACHE TTL BY MODE
    # ========================================================

    def _mode_cache_ttl(
        self,
        mode: str,
    ) -> int:

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

        if (
            normalized_mode
            == Config.MODE_INTRADAY
        ):

            return (
                self
                .INTRADAY_CANDLE_CACHE_SECONDS
            )

        if (
            normalized_mode
            == Config.MODE_BTST
        ):

            return (
                self
                .BTST_CANDLE_CACHE_SECONDS
            )

        return (
            self
            .SWING_CANDLE_CACHE_SECONDS
        )


    # ========================================================
    # MODE MARKET DATA
    # ========================================================

    def get_mode_market_data(
        self,
        access_token: str,
        symbol: str,
        *,
        mode: str,
        force_refresh: bool = False,
    ) -> dict[str, Any]:

        normalized_symbol = (
            normalize_symbol(
                symbol
            )
        )

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

        if not normalized_symbol:

            raise ValueError(
                (
                    "Valid stock "
                    "symbol required."
                )
            )

        cache_key = (
            build_cache_key(
                "mode_data",
                normalized_symbol,
                normalized_mode,
                prefix="market",
            )
        )

        cache_ttl = (
            self
            ._mode_cache_ttl(
                normalized_mode
            )
        )

        if not force_refresh:

            cached = (
                self.cache_service
                .get(
                    cache_key
                )
            )

            if isinstance(
                cached,
                dict,
            ):

                return cached

        with self._history_lock:

            if not force_refresh:

                cached = (
                    self.cache_service
                    .get(
                        cache_key
                    )
                )

                if isinstance(
                    cached,
                    dict,
                ):

                    return cached

            try:

                mode_data = (
                    self.fyers_service
                    .get_mode_candles(
                        access_token,
                        symbol=(
                            normalized_symbol
                        ),
                        mode=(
                            normalized_mode
                        ),
                    )
                )

                if not isinstance(
                    mode_data,
                    dict,
                ):

                    raise (
                        MarketDataValidationError(
                            (
                                "FYERS mode "
                                "candle response "
                                "is invalid."
                            )
                        )
                    )


                # =================================================
                # INTRADAY
                # =================================================

                if (
                    normalized_mode
                    == Config.MODE_INTRADAY
                ):

                    primary = (
                        self
                        ._validate_candles(
                            mode_data.get(
                                "primary",
                                [],
                            ),
                            minimum=(
                                Config
                                .MIN_REQUIRED_CANDLES_INTRADAY
                            ),
                        )
                    )

                    confirmation = (
                        self
                        ._validate_candles(
                            mode_data.get(
                                "confirmation",
                                [],
                            ),
                            minimum=80,
                        )
                    )

                    higher = (
                        self
                        ._validate_candles(
                            mode_data.get(
                                "higher_timeframe",
                                [],
                            ),
                            minimum=(
                                Config
                                .MIN_REQUIRED_CANDLES_SWING
                            ),
                        )
                    )

                    result = {
                        "symbol": (
                            normalized_symbol
                        ),

                        "mode": (
                            normalized_mode
                        ),

                        "primary_resolution": (
                            Config
                            .INTRADAY_PRIMARY_RESOLUTION
                        ),

                        "confirmation_resolution": (
                            Config
                            .INTRADAY_CONFIRMATION_RESOLUTION
                        ),

                        "higher_resolution": (
                            Config
                            .INTRADAY_HIGHER_TIMEFRAME_RESOLUTION
                        ),

                        "primary": (
                            primary
                        ),

                        "confirmation": (
                            confirmation
                        ),

                        "higher_timeframe": (
                            higher
                        ),

                        "weekly": [],

                        "verified": True,

                        "source": "FYERS",

                        "updated_at": (
                            utc_now()
                            .isoformat()
                        ),
                    }


                # =================================================
                # BTST
                # =================================================

                elif (
                    normalized_mode
                    == Config.MODE_BTST
                ):

                    primary = (
                        self
                        ._validate_candles(
                            mode_data.get(
                                "primary",
                                [],
                            ),
                            minimum=(
                                Config
                                .MIN_REQUIRED_CANDLES_BTST
                            ),
                        )
                    )

                    confirmation = (
                        self
                        ._validate_candles(
                            mode_data.get(
                                "confirmation",
                                [],
                            ),
                            minimum=80,
                        )
                    )

                    higher = (
                        self
                        ._validate_candles(
                            mode_data.get(
                                "higher_timeframe",
                                [],
                            ),
                            minimum=(
                                Config
                                .MIN_REQUIRED_CANDLES_SWING
                            ),
                        )
                    )

                    result = {
                        "symbol": (
                            normalized_symbol
                        ),

                        "mode": (
                            normalized_mode
                        ),

                        "primary_resolution": (
                            Config
                            .BTST_PRIMARY_RESOLUTION
                        ),

                        "confirmation_resolution": (
                            Config
                            .BTST_CONFIRMATION_RESOLUTION
                        ),

                        "higher_resolution": (
                            Config
                            .BTST_HIGHER_TIMEFRAME_RESOLUTION
                        ),

                        "primary": (
                            primary
                        ),

                        "confirmation": (
                            confirmation
                        ),

                        "higher_timeframe": (
                            higher
                        ),

                        "weekly": [],

                        "btst": True,

                        "verified": True,

                        "source": "FYERS",

                        "updated_at": (
                            utc_now()
                            .isoformat()
                        ),
                    }


                # =================================================
                # SWING
                # =================================================

                else:

                    daily = (
                        self
                        ._validate_candles(
                            mode_data.get(
                                "primary",
                                [],
                            ),
                            minimum=(
                                Config
                                .MIN_REQUIRED_CANDLES_SWING
                            ),
                        )
                    )

                    weekly = (
                        self
                        .resample_daily_to_weekly(
                            daily
                        )
                    )

                    if (
                        len(weekly)
                        < 30
                    ):

                        raise (
                            MarketDataUnavailableError(
                                (
                                    "Insufficient "
                                    "weekly confirmation "
                                    "data for "
                                    f"{normalized_symbol}."
                                )
                            )
                        )

                    result = {
                        "symbol": (
                            normalized_symbol
                        ),

                        "mode": (
                            normalized_mode
                        ),

                        "primary_resolution": (
                            Config
                            .SWING_PRIMARY_RESOLUTION
                        ),

                        "confirmation_resolution": (
                            Config
                            .SWING_CONFIRMATION_RESOLUTION
                        ),

                        "higher_resolution": (
                            Config
                            .SWING_HIGHER_TIMEFRAME_RESOLUTION
                        ),

                        "primary": (
                            daily
                        ),

                        "confirmation": (
                            weekly
                        ),

                        "higher_timeframe": (
                            weekly
                        ),

                        "weekly": (
                            weekly
                        ),

                        "verified": True,

                        "source": "FYERS",

                        "updated_at": (
                            utc_now()
                            .isoformat()
                        ),
                    }


                self.cache_service.set(
                    cache_key,
                    result,
                    ttl_seconds=(
                        cache_ttl
                    ),
                )

                return result

            except (
                FyersAPIError,
                FyersAuthenticationError,
                MarketDataError,
            ):

                raise

            except Exception as exception:

                log_exception(
                    logger,
                    (
                        "Mode market data "
                        "fetch failed"
                    ),
                    exception=exception,
                    symbol=(
                        normalized_symbol
                    ),
                    component=(
                        "market_data_service"
                    ),
                    error_code=(
                        "MODE_DATA_FAILED"
                    ),
                    mode=(
                        normalized_mode
                    ),
                )

                raise (
                    MarketDataUnavailableError(
                        (
                            "Verified market "
                            "data unavailable "
                            "for "
                            f"{normalized_symbol}."
                        )
                    )
                ) from exception


    # ========================================================
    # MULTI-TIMEFRAME TECHNICAL ANALYSIS
    # ========================================================

    def analyze_stock(
        self,
        access_token: str,
        symbol: str,
        *,
        sector: str,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:

        normalized_symbol = (
            normalize_symbol(
                symbol
            )
        )

        normalized_sector = (
            clean_text(
                sector
            )
        )

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

        if not normalized_symbol:

            raise ValueError(
                (
                    "Valid stock "
                    "symbol required."
                )
            )

        if not normalized_sector:

            raise ValueError(
                (
                    "Valid stock "
                    "sector required."
                )
            )

        quote = (
            self.get_quote(
                access_token,
                normalized_symbol,
                force_refresh=(
                    force_refresh
                ),
            )
        )

        mode_data = (
            self
            .get_mode_market_data(
                access_token,
                normalized_symbol,
                mode=(
                    normalized_mode
                ),
                force_refresh=(
                    force_refresh
                ),
            )
        )

        technical_result = (
            analyze_stock(
                symbol=(
                    normalized_symbol
                ),

                sector=(
                    normalized_sector
                ),

                mode=(
                    normalized_mode
                ),

                benchmark_change_pct=(
                    benchmark_change_pct
                ),

                primary_candles=(
                    mode_data[
                        "primary"
                    ]
                ),

                confirmation_candles=(
                    mode_data[
                        "confirmation"
                    ]
                ),

                higher_timeframe_candles=(
                    mode_data[
                        "higher_timeframe"
                    ]
                ),
            )
        )

        if hasattr(
            technical_result,
            "to_dict",
        ):

            result = (
                technical_result
                .to_dict()
            )

        elif isinstance(
            technical_result,
            dict,
        ):

            result = dict(
                technical_result
            )

        else:

            raise (
                MarketDataValidationError(
                    (
                        "Technical scanner "
                        "returned invalid data."
                    )
                )
            )

        live_price = safe_float(
            quote.get(
                "current_price"
            )
        )

        if (
            live_price is None
            or live_price <= 0
        ):

            raise (
                MarketDataUnavailableError(
                    (
                        "Live FYERS price "
                        "is unavailable."
                    )
                )
            )

        # ====================================================
        # LIVE LTP OVERRIDE
        # ====================================================

        result[
            "current_price"
        ] = round(
            live_price,
            2,
        )

        result[
            "symbol"
        ] = (
            normalized_symbol
        )

        result[
            "sector"
        ] = (
            normalized_sector
        )

        result[
            "mode"
        ] = (
            normalized_mode
        )

        result[
            "company_market_data"
        ] = {
            "change": (
                quote.get(
                    "change"
                )
            ),

            "change_percent": (
                quote.get(
                    "change_percent"
                )
            ),

            "volume": (
                quote.get(
                    "volume"
                )
            ),

            "open": (
                quote.get(
                    "open"
                )
            ),

            "high": (
                quote.get(
                    "high"
                )
            ),

            "low": (
                quote.get(
                    "low"
                )
            ),

            "previous_close": (
                quote.get(
                    "previous_close"
                )
            ),

            "source": "FYERS",
        }

        result[
            "primary_resolution"
        ] = (
            mode_data[
                "primary_resolution"
            ]
        )

        result[
            "confirmation_resolution"
        ] = (
            mode_data[
                "confirmation_resolution"
            ]
        )

        result[
            "higher_resolution"
        ] = (
            mode_data[
                "higher_resolution"
            ]
        )

        result[
            "multi_timeframe_data"
        ] = {
            "primary_candles": len(
                mode_data[
                    "primary"
                ]
            ),

            "confirmation_candles": len(
                mode_data[
                    "confirmation"
                ]
            ),

            "higher_timeframe_candles": len(
                mode_data[
                    "higher_timeframe"
                ]
            ),
        }

        result[
            "verified"
        ] = True

        result[
            "source"
        ] = "FYERS"

        result[
            "updated_at"
        ] = (
            utc_now()
            .isoformat()
        )

        return result


    # ========================================================
    # STRONG BUY ONLY
    # ========================================================

    def analyze_strong_buy(
        self,
        access_token: str,
        symbol: str,
        *,
        sector: str,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:

        result = (
            self.analyze_stock(
                access_token,
                symbol,
                sector=(
                    sector
                ),
                mode=(
                    mode
                ),
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
                force_refresh=(
                    force_refresh
                ),
            )
        )

        signal = (
            clean_text(
                result.get(
                    "signal"
                )
            )
            .upper()
        )

        if (
            signal
            != "STRONG BUY"
        ):

            return None

        if not bool(
            result.get(
                "multi_timeframe_confirmed"
            )
        ):

            return None

        return result


    # ========================================================
    # BULK FINAL TECHNICAL SCAN
    # ========================================================

    def scan_stocks(
        self,
        access_token: str,
        stocks: Iterable[
            dict[str, Any]
        ],
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
    ) -> list[
        dict[str, Any]
    ]:

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

        results: list[
            dict[str, Any]
        ] = []

        seen_symbols: set[
            str
        ] = set()

        for stock in stocks:

            if not isinstance(
                stock,
                dict,
            ):
                continue

            symbol = (
                normalize_symbol(
                    stock.get(
                        "symbol"
                    )
                )
            )

            sector = (
                clean_text(
                    stock.get(
                        "sector"
                    )
                )
            )

            if (
                not symbol
                or not sector
            ):

                continue

            if (
                symbol
                in seen_symbols
            ):

                continue

            seen_symbols.add(
                symbol
            )

            try:

                result = (
                    self
                    .analyze_strong_buy(
                        access_token,
                        symbol,
                        sector=(
                            sector
                        ),
                        mode=(
                            normalized_mode
                        ),
                        benchmark_change_pct=(
                            benchmark_change_pct
                        ),
                    )
                )

                if result:

                    if not result.get(
                        "company_name"
                    ):

                        result[
                            "company_name"
                        ] = (
                            stock.get(
                                "company_name"
                            )
                            or symbol
                        )

                    results.append(
                        result
                    )

            except Exception as exception:

                log_exception(
                    logger,
                    (
                        "Technical "
                        "scan failed"
                    ),
                    exception=exception,
                    symbol=(
                        symbol
                    ),
                    component=(
                        "market_data_service"
                    ),
                    error_code=(
                        "TECHNICAL_SCAN_FAILED"
                    ),
                    mode=(
                        normalized_mode
                    ),
                )

                continue

        results.sort(
            key=lambda item: (
                -self._safe_sort_number(
                    item.get(
                        "technical_score"
                    )
                ),

                -self._safe_sort_number(
                    item.get(
                        "risk_reward"
                    )
                ),

                clean_text(
                    item.get(
                        "symbol"
                    )
                ),
            )
        )

        return results


    # ========================================================
    # CLEAR SYMBOL CACHE
    # ========================================================

    def clear_symbol_cache(
        self,
        symbol: str,
    ) -> int:

        normalized_symbol = (
            normalize_symbol(
                symbol
            )
        )

        if not normalized_symbol:

            return 0

        deleted_count = 0

        for key in (
            self.cache_service
            .list_keys()
        ):

            if (
                normalized_symbol
                .casefold()
                in key
                .casefold()
            ):

                if (
                    self
                    .cache_service
                    .delete(
                        key
                    )
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

        token_available = bool(
            clean_text(
                access_token
            )
        )

        fyers_health = (
            self
            .fyers_service
            .health(
                access_token
                if token_available
                else None
            )
        )

        cache_health = (
            self
            .cache_service
            .health()
        )

        healthy = (
            bool(
                fyers_health.get(
                    "configured"
                )
            )
            and bool(
                cache_health.get(
                    "is_healthy"
                )
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
            "service": (
                "Market Data Service"
            ),

            "status": (
                "healthy"
                if healthy
                else "unhealthy"
            ),

            "is_healthy": (
                healthy
            ),

            "fyers": (
                fyers_health
            ),

            "cache": (
                cache_health
            ),

            "supported_modes": [
                Config.MODE_INTRADAY,
                Config.MODE_BTST,
                Config.MODE_SWING,
            ],

            "intraday": {
                "primary": (
                    Config
                    .INTRADAY_PRIMARY_RESOLUTION
                ),

                "confirmation": (
                    Config
                    .INTRADAY_CONFIRMATION_RESOLUTION
                ),

                "higher": (
                    Config
                    .INTRADAY_HIGHER_TIMEFRAME_RESOLUTION
                ),
            },

            "btst": {
                "primary": (
                    Config
                    .BTST_PRIMARY_RESOLUTION
                ),

                "confirmation": (
                    Config
                    .BTST_CONFIRMATION_RESOLUTION
                ),

                "higher": (
                    Config
                    .BTST_HIGHER_TIMEFRAME_RESOLUTION
                ),
            },

            "swing": {
                "primary": (
                    Config
                    .SWING_PRIMARY_RESOLUTION
                ),

                "confirmation": (
                    Config
                    .SWING_CONFIRMATION_RESOLUTION
                ),

                "higher": (
                    Config
                    .SWING_HIGHER_TIMEFRAME_RESOLUTION
                ),
            },

            "technical_only": True,

            "multi_timeframe": True,

            "fake_data_allowed": (
                Config.ALLOW_FAKE_DATA
            ),

            "checked_at": (
                utc_now()
                .isoformat()
            ),
        }


# ============================================================
# GLOBAL INSTANCE
# ============================================================


_global_market_data_service: (
    MarketDataService | None
) = None


_global_market_data_lock = (
    threading.Lock()
)


def get_market_data_service(
) -> MarketDataService:

    global _global_market_data_service

    if (
        _global_market_data_service
        is not None
    ):

        return (
            _global_market_data_service
        )

    with _global_market_data_lock:

        if (
            _global_market_data_service
            is None
        ):

            _global_market_data_service = (
                MarketDataService()
            )

    return (
        _global_market_data_service
    )
