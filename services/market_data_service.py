from __future__ import annotations

"""
Eagle Smart Scanner - Market Data Service

Unified data layer for the scanner.

Responsibilities
----------------
- Prefer fresh FYERS WebSocket prices
- Fall back ONLY to real FYERS REST quotes when needed
- Fetch historical OHLCV candles
- Support mode-specific primary / confirmation / higher timeframes
- Derive weekly candles from daily candles for Swing
- Validate candle quality and minimum history
- Provide pandas DataFrames for technical calculation
- Never generate fake/random market data

This module is intentionally scanner-facing. Other scanner modules should
use MarketDataService instead of directly talking to FYERS REST/WebSocket.
"""

import threading
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable

import pandas as pd

from config import Config
from services.fyers_service import (
    Candle,
    FyersAPIError,
    FyersDataError,
    FyersService,
    Quote,
    get_fyers_service,
)
from services.live_market_store import (
    LiveMarketStore,
    LiveTick,
    get_live_market_store,
)


class MarketDataError(RuntimeError):
    """Base market-data service error."""


class InsufficientMarketDataError(MarketDataError):
    """Raised when enough valid candles are not available."""


class StaleMarketDataError(MarketDataError):
    """Raised when live data is required but available data is stale."""


class MarketDataService:
    """
    Unified market data provider for Eagle Smart Scanner.
    """

    def __init__(
        self,
        fyers_service: FyersService | None = None,
        live_store: LiveMarketStore | None = None,
    ) -> None:
        self.fyers = fyers_service or get_fyers_service()
        self.live_store = live_store or get_live_market_store()

        self._quote_lock = threading.RLock()

    # ========================================================
    # LIVE / REST QUOTES
    # ========================================================

    def get_live_tick(
        self,
        symbol: str,
        *,
        allow_stale: bool = False,
    ) -> LiveTick | None:
        return self.live_store.get_tick(
            symbol,
            allow_stale=allow_stale,
        )

    def get_live_price(
        self,
        symbol: str,
        *,
        allow_rest_fallback: bool = True,
        require_fresh: bool = True,
    ) -> float:
        tick = self.live_store.get_tick(
            symbol,
            allow_stale=not require_fresh,
        )

        if tick is not None:
            if tick.ltp <= 0 and not Config.ALLOW_ZERO_PRICE:
                raise MarketDataError(
                    f"Invalid live price for {symbol}: {tick.ltp}"
                )

            return float(tick.ltp)

        if not allow_rest_fallback:
            raise StaleMarketDataError(
                f"No fresh WebSocket price available for {symbol}."
            )

        quote = self.get_quote(
            symbol,
            prefer_websocket=False,
        )

        if quote.ltp <= 0 and not Config.ALLOW_ZERO_PRICE:
            raise MarketDataError(
                f"Invalid REST price for {symbol}: {quote.ltp}"
            )

        return float(quote.ltp)

    def get_quote(
        self,
        symbol: str,
        *,
        prefer_websocket: bool = True,
    ) -> Quote:
        """
        Return a normalized Quote.

        Fresh WebSocket values are preferred. If unavailable, fetch a real
        FYERS REST quote. No synthetic fallback is used.
        """
        if prefer_websocket:
            tick = self.live_store.get_tick(
                symbol,
                allow_stale=False,
            )

            if tick is not None:
                return self._quote_from_live_tick(tick)

        quote = self.fyers.get_quote(symbol)

        # Cache real REST quote only when no fresher WebSocket tick exists.
        self.live_store.ingest_rest_quote(quote)

        return quote

    def get_quotes(
        self,
        symbols: Iterable[str],
        *,
        prefer_websocket: bool = True,
    ) -> list[Quote]:
        symbol_list = [
            str(item).strip()
            for item in symbols
            if str(item).strip()
        ]

        if not symbol_list:
            return []

        result: list[Quote] = []
        missing: list[str] = []

        if prefer_websocket:
            for symbol in symbol_list:
                tick = self.live_store.get_tick(
                    symbol,
                    allow_stale=False,
                )

                if tick is None:
                    missing.append(symbol)
                else:
                    result.append(
                        self._quote_from_live_tick(tick)
                    )
        else:
            missing = symbol_list

        if missing:
            rest_quotes = self.fyers.get_quotes(missing)

            for quote in rest_quotes:
                self.live_store.ingest_rest_quote(quote)

            result.extend(rest_quotes)

        return result

    # ========================================================
    # HISTORY - PUBLIC API
    # ========================================================

    def get_candles(
        self,
        symbol: str,
        resolution: str,
        *,
        candle_count: int | None = None,
        min_required: int | None = None,
    ) -> list[Candle]:
        """
        Fetch sufficient historical candles for the requested resolution.

        `weekly_from_daily` is derived locally from daily FYERS candles.
        """
        resolution_value = str(resolution or "").strip()

        if not resolution_value:
            raise MarketDataError(
                "Resolution is required."
            )

        if resolution_value == "weekly_from_daily":
            return self._get_weekly_from_daily(
                symbol=symbol,
                candle_count=candle_count,
                min_required=min_required,
            )

        requested = int(candle_count or 0)

        if requested <= 0:
            requested = 300

        required = int(
            min_required
            if min_required is not None
            else min(requested, 200)
        )

        days = self._estimate_history_days(
            resolution=resolution_value,
            candle_count=requested,
        )

        candles = self.fyers.get_recent_history(
            symbol=symbol,
            resolution=resolution_value,
            days=days,
        )

        candles = self._deduplicate_candles(candles)

        if len(candles) < required:
            # One broader retry for holidays, weekends and sparse symbols.
            days = max(
                days * 2,
                self._estimate_history_days(
                    resolution=resolution_value,
                    candle_count=requested * 2,
                ),
            )

            candles = self.fyers.get_recent_history(
                symbol=symbol,
                resolution=resolution_value,
                days=days,
            )

            candles = self._deduplicate_candles(candles)

        if len(candles) < required:
            raise InsufficientMarketDataError(
                f"{symbol}: only {len(candles)} valid candles available "
                f"for resolution {resolution_value}; "
                f"minimum required is {required}."
            )

        if len(candles) > requested:
            candles = candles[-requested:]

        return candles

    def get_dataframe(
        self,
        symbol: str,
        resolution: str,
        *,
        candle_count: int | None = None,
        min_required: int | None = None,
    ) -> pd.DataFrame:
        candles = self.get_candles(
            symbol=symbol,
            resolution=resolution,
            candle_count=candle_count,
            min_required=min_required,
        )

        return self.candles_to_dataframe(candles)

    # ========================================================
    # MODE-SPECIFIC DATA
    # ========================================================

    def get_primary_dataframe(
        self,
        symbol: str,
        mode: str,
    ) -> pd.DataFrame:
        mode = Config.normalize_trading_mode(mode)

        return self.get_dataframe(
            symbol=symbol,
            resolution=Config.get_primary_resolution(mode),
            candle_count=Config.get_history_candles(mode),
            min_required=Config.get_min_required_candles(mode),
        )

    def get_confirmation_dataframe(
        self,
        symbol: str,
        mode: str,
    ) -> pd.DataFrame:
        mode = Config.normalize_trading_mode(mode)

        resolution = Config.get_confirmation_resolution(mode)

        requested = self._confirmation_candle_count(mode)

        return self.get_dataframe(
            symbol=symbol,
            resolution=resolution,
            candle_count=requested,
            min_required=min(
                requested,
                Config.get_min_required_candles(mode),
            ),
        )

    def get_higher_timeframe_dataframe(
        self,
        symbol: str,
        mode: str,
    ) -> pd.DataFrame:
        mode = Config.normalize_trading_mode(mode)

        resolution = Config.get_higher_timeframe_resolution(mode)

        requested = self._higher_timeframe_candle_count(mode)

        return self.get_dataframe(
            symbol=symbol,
            resolution=resolution,
            candle_count=requested,
            min_required=min(
                requested,
                Config.get_min_required_candles(mode),
            ),
        )

    def get_multi_timeframe_data(
        self,
        symbol: str,
        mode: str,
    ) -> dict[str, pd.DataFrame]:
        """
        Fetch all frames needed by TechnicalScanner in one standard shape.
        """
        mode = Config.normalize_trading_mode(mode)

        primary = self.get_primary_dataframe(
            symbol=symbol,
            mode=mode,
        )

        confirmation = self.get_confirmation_dataframe(
            symbol=symbol,
            mode=mode,
        )

        higher = self.get_higher_timeframe_dataframe(
            symbol=symbol,
            mode=mode,
        )

        return {
            "primary": primary,
            "confirmation": confirmation,
            "higher": higher,
        }

    # ========================================================
    # DATAFRAME CONVERSION
    # ========================================================

    @staticmethod
    def candles_to_dataframe(
        candles: Iterable[Candle],
    ) -> pd.DataFrame:
        rows = [
            {
                "timestamp": int(candle.timestamp),
                "open": float(candle.open),
                "high": float(candle.high),
                "low": float(candle.low),
                "close": float(candle.close),
                "volume": float(candle.volume),
            }
            for candle in candles
        ]

        df = pd.DataFrame(
            rows,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
        )

        if df.empty:
            raise InsufficientMarketDataError(
                "Candle DataFrame is empty."
            )

        df = (
            df.drop_duplicates(
                subset=["timestamp"],
                keep="last",
            )
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        df["datetime"] = pd.to_datetime(
            df["timestamp"],
            unit="s",
            utc=True,
        ).dt.tz_convert(Config.MARKET_TIMEZONE)

        numeric_columns = [
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        for column in numeric_columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

        df = df.dropna(
            subset=[
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        ).reset_index(drop=True)

        if not Config.ALLOW_ZERO_PRICE:
            df = df[
                (df["open"] > 0)
                & (df["high"] > 0)
                & (df["low"] > 0)
                & (df["close"] > 0)
            ].reset_index(drop=True)

        if df.empty:
            raise InsufficientMarketDataError(
                "No valid OHLCV rows remained after validation."
            )

        invalid_hilo = df["high"] < df["low"]

        if invalid_hilo.any():
            df = df[~invalid_hilo].reset_index(drop=True)

        return df

    # ========================================================
    # WEEKLY DERIVATION
    # ========================================================

    def _get_weekly_from_daily(
        self,
        symbol: str,
        *,
        candle_count: int | None,
        min_required: int | None,
    ) -> list[Candle]:
        requested_weekly = int(candle_count or 120)

        if requested_weekly <= 0:
            requested_weekly = 120

        required_weekly = int(
            min_required
            if min_required is not None
            else min(requested_weekly, 60)
        )

        # Request more than 5x because market holidays can reduce sessions.
        daily_count = max(
            requested_weekly * 6,
            required_weekly * 6,
            320,
        )

        daily = self.get_candles(
            symbol=symbol,
            resolution="D",
            candle_count=daily_count,
            min_required=min(
                daily_count,
                max(required_weekly * 4, 220),
            ),
        )

        daily_df = self.candles_to_dataframe(daily)

        # Use Indian market week ending Friday.
        indexed = daily_df.set_index("datetime")

        weekly = indexed.resample(
            "W-FRI",
            label="right",
            closed="right",
        ).agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )

        weekly = weekly.dropna(
            subset=["open", "high", "low", "close"]
        )

        candles: list[Candle] = []

        for idx, row in weekly.iterrows():
            timestamp = int(idx.timestamp())

            candle = Candle(
                timestamp=timestamp,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )

            candles.append(candle)

        candles = self._deduplicate_candles(candles)

        if len(candles) < required_weekly:
            raise InsufficientMarketDataError(
                f"{symbol}: only {len(candles)} weekly candles could be "
                f"derived; minimum required is {required_weekly}."
            )

        if len(candles) > requested_weekly:
            candles = candles[-requested_weekly:]

        return candles

    # ========================================================
    # QUOTE ADAPTER
    # ========================================================

    @staticmethod
    def _quote_from_live_tick(
        tick: LiveTick,
    ) -> Quote:
        return Quote(
            symbol=tick.symbol,
            fyers_symbol=tick.fyers_symbol,
            ltp=tick.ltp,
            change=tick.change,
            change_percent=tick.change_percent,
            open=tick.open,
            high=tick.high,
            low=tick.low,
            previous_close=tick.previous_close,
            volume=tick.volume,
            bid=tick.bid,
            ask=tick.ask,
            timestamp=tick.exchange_timestamp,
            raw={
                "source": tick.source,
                "received_timestamp": tick.received_timestamp,
                "age_seconds": tick.age_seconds,
            },
        )

    # ========================================================
    # HISTORY RANGE ESTIMATION
    # ========================================================

    @staticmethod
    def _estimate_history_days(
        resolution: str,
        candle_count: int,
    ) -> int:
        """
        Estimate a safe date-range size for FYERS History API.

        Intraday requests are kept comfortably below the FYERS 100-day
        intraday request limit, while daily requests can span much longer.
        """
        resolution = str(resolution or "").strip().upper()
        count = max(int(candle_count), 1)

        if resolution == "D":
            # ~252 trading days/year; add holiday/weekend buffer.
            return max(
                365,
                int(count * 1.65) + 30,
            )

        if resolution in {"1", "2", "3", "5", "10", "15", "20", "30", "60", "120", "240"}:
            minutes = int(resolution)

            market_minutes_per_day = (
                (Config.MARKET_CLOSE_HOUR * 60 + Config.MARKET_CLOSE_MINUTE)
                - (Config.MARKET_OPEN_HOUR * 60 + Config.MARKET_OPEN_MINUTE)
            )

            candles_per_day = max(
                1,
                market_minutes_per_day // minutes,
            )

            trading_days = max(
                1,
                (count + candles_per_day - 1)
                // candles_per_day,
            )

            calendar_days = int(
                trading_days * 1.6
            ) + 7

            # FYERS intraday History API requests are constrained by range.
            return max(
                7,
                min(calendar_days, 95),
            )

        # Conservative fallback for other valid FYERS resolutions.
        return max(
            30,
            int(count * 1.5) + 10,
        )

    # ========================================================
    # MODE CANDLE COUNTS
    # ========================================================

    @staticmethod
    def _confirmation_candle_count(
        mode: str,
    ) -> int:
        mode = Config.normalize_trading_mode(mode)

        if mode == Config.MODE_INTRADAY:
            return 220

        if mode == Config.MODE_BTST:
            return 220

        return 120

    @staticmethod
    def _higher_timeframe_candle_count(
        mode: str,
    ) -> int:
        mode = Config.normalize_trading_mode(mode)

        if mode == Config.MODE_INTRADAY:
            return 260

        if mode == Config.MODE_BTST:
            return 260

        return 120

    # ========================================================
    # CANDLE VALIDATION
    # ========================================================

    @staticmethod
    def _deduplicate_candles(
        candles: Iterable[Candle],
    ) -> list[Candle]:
        by_timestamp: dict[int, Candle] = {}

        for candle in candles:
            if candle.timestamp <= 0:
                continue

            if not Config.ALLOW_ZERO_PRICE:
                if min(
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                ) <= 0:
                    continue

            if candle.high < candle.low:
                continue

            if candle.high < max(
                candle.open,
                candle.close,
            ):
                continue

            if candle.low > min(
                candle.open,
                candle.close,
            ):
                continue

            if candle.volume < 0:
                continue

            by_timestamp[candle.timestamp] = candle

        return [
            by_timestamp[key]
            for key in sorted(by_timestamp)
        ]

    # ========================================================
    # HEALTH
    # ========================================================

    def health(self) -> dict[str, Any]:
        return {
            "fyers_configured": self.fyers.is_app_configured(),
            "access_token_present": self.fyers.has_access_token(),
            "websocket_enabled": bool(
                Config.FYERS_WEBSOCKET_ENABLED
            ),
            "live_store": self.live_store.status(),
            "fake_data_allowed": bool(
                Config.ALLOW_FAKE_DATA
            ),
            "random_fallback_allowed": bool(
                Config.ALLOW_FALLBACK_RANDOM_DATA
            ),
        }


# ============================================================
# SINGLETON
# ============================================================

_default_market_data_service: MarketDataService | None = None
_default_market_data_lock = threading.Lock()


def get_market_data_service() -> MarketDataService:
    global _default_market_data_service

    if _default_market_data_service is not None:
        return _default_market_data_service

    with _default_market_data_lock:
        if _default_market_data_service is None:
            _default_market_data_service = MarketDataService()

    return _default_market_data_service


# ============================================================
# BACKWARD-COMPATIBLE MODULE HELPERS
# ============================================================

def get_live_price(
    symbol: str,
    *,
    allow_rest_fallback: bool = True,
    require_fresh: bool = True,
) -> float:
    return get_market_data_service().get_live_price(
        symbol=symbol,
        allow_rest_fallback=allow_rest_fallback,
        require_fresh=require_fresh,
    )


def get_quote(
    symbol: str,
    *,
    prefer_websocket: bool = True,
) -> Quote:
    return get_market_data_service().get_quote(
        symbol=symbol,
        prefer_websocket=prefer_websocket,
    )


def get_candles(
    symbol: str,
    resolution: str,
    *,
    candle_count: int | None = None,
    min_required: int | None = None,
) -> list[Candle]:
    return get_market_data_service().get_candles(
        symbol=symbol,
        resolution=resolution,
        candle_count=candle_count,
        min_required=min_required,
    )


def get_dataframe(
    symbol: str,
    resolution: str,
    *,
    candle_count: int | None = None,
    min_required: int | None = None,
) -> pd.DataFrame:
    return get_market_data_service().get_dataframe(
        symbol=symbol,
        resolution=resolution,
        candle_count=candle_count,
        min_required=min_required,
    )
