from __future__ import annotations

"""
Eagle Smart Scanner - Index Service

Provides standardized live + historical technical data for:
- NIFTY 50 benchmark
- NIFTY BANK
- Candidate NSE sector indices

This service does NOT decide BUY/STRONG BUY stock signals.
It prepares index/sector data for sector_scanner.py.
"""

import threading
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import pandas as pd

from config import Config
from data.sector_map import (
    BENCHMARK_INDICES,
    get_candidate_sectors,
    normalize_sector_key,
    sector_key_from_fyers_symbol,
)
from services.market_data_service import (
    MarketDataService,
    get_market_data_service,
)


class IndexServiceError(RuntimeError):
    """Index/sector data service error."""


@dataclass(frozen=True)
class IndexSnapshot:
    key: str
    name: str
    fyers_symbol: str
    ltp: float
    change: float
    change_percent: float
    open: float
    high: float
    low: float
    previous_close: float
    volume: float
    source: str
    timestamp: int | None


@dataclass(frozen=True)
class IndexTechnicalSnapshot:
    key: str
    name: str
    fyers_symbol: str
    ltp: float
    change_percent: float

    return_5d: float
    return_20d: float

    ema20: float
    ema50: float
    ema200: float

    above_ema20: bool
    above_ema50: bool
    above_ema200: bool
    bullish_ema_structure: bool

    rsi14: float
    relative_strength_20d: float

    distance_from_20d_high_pct: float
    distance_from_52w_high_pct: float

    trend_score: float
    source: str


class IndexService:
    """
    Scanner-facing index and sector data provider.
    """

    def __init__(
        self,
        market_data: MarketDataService | None = None,
    ) -> None:
        self.market_data = (
            market_data
            or get_market_data_service()
        )

    # ========================================================
    # LIVE SNAPSHOTS
    # ========================================================

    def get_index_snapshot(
        self,
        symbol: str,
        *,
        key: str = "",
        name: str = "",
    ) -> IndexSnapshot:
        quote = self.market_data.get_quote(
            symbol,
            prefer_websocket=True,
        )

        source = str(
            quote.raw.get("source", "rest")
            if isinstance(quote.raw, dict)
            else "rest"
        )

        return IndexSnapshot(
            key=key,
            name=name or key or quote.fyers_symbol,
            fyers_symbol=quote.fyers_symbol,
            ltp=float(quote.ltp),
            change=float(quote.change),
            change_percent=float(quote.change_percent),
            open=float(quote.open),
            high=float(quote.high),
            low=float(quote.low),
            previous_close=float(quote.previous_close),
            volume=float(quote.volume),
            source=source,
            timestamp=quote.timestamp,
        )

    def get_benchmark_snapshots(
        self,
    ) -> list[IndexSnapshot]:
        result: list[IndexSnapshot] = []

        for key, info in BENCHMARK_INDICES.items():
            result.append(
                self.get_index_snapshot(
                    info["fyers_symbol"],
                    key=key,
                    name=info["name"],
                )
            )

        return result

    def get_sector_snapshots(
        self,
    ) -> list[IndexSnapshot]:
        sectors = get_candidate_sectors()

        symbols = [
            sector["fyers_symbol"]
            for sector in sectors
        ]

        quotes = self.market_data.get_quotes(
            symbols,
            prefer_websocket=True,
        )

        quote_map = {
            quote.fyers_symbol.upper(): quote
            for quote in quotes
        }

        result: list[IndexSnapshot] = []

        for sector in sectors:
            symbol = sector["fyers_symbol"]
            quote = quote_map.get(symbol.upper())

            if quote is None:
                # Missing real data is skipped, never fabricated.
                continue

            source = str(
                quote.raw.get("source", "rest")
                if isinstance(quote.raw, dict)
                else "rest"
            )

            result.append(
                IndexSnapshot(
                    key=sector["key"],
                    name=sector["name"],
                    fyers_symbol=quote.fyers_symbol,
                    ltp=float(quote.ltp),
                    change=float(quote.change),
                    change_percent=float(
                        quote.change_percent
                    ),
                    open=float(quote.open),
                    high=float(quote.high),
                    low=float(quote.low),
                    previous_close=float(
                        quote.previous_close
                    ),
                    volume=float(quote.volume),
                    source=source,
                    timestamp=quote.timestamp,
                )
            )

        return result

    # ========================================================
    # HISTORICAL DATA
    # ========================================================

    def get_daily_dataframe(
        self,
        symbol: str,
        *,
        candle_count: int = 260,
        min_required: int = 220,
    ) -> pd.DataFrame:
        return self.market_data.get_dataframe(
            symbol=symbol,
            resolution="D",
            candle_count=candle_count,
            min_required=min_required,
        )

    # ========================================================
    # TECHNICAL SNAPSHOT
    # ========================================================

    def get_technical_snapshot(
        self,
        symbol: str,
        *,
        key: str = "",
        name: str = "",
        benchmark_df: pd.DataFrame | None = None,
    ) -> IndexTechnicalSnapshot:
        live = self.get_index_snapshot(
            symbol,
            key=key,
            name=name,
        )

        df = self.get_daily_dataframe(
            symbol,
            candle_count=260,
            min_required=220,
        ).copy()

        close = df["close"].astype(float)

        ema20_series = close.ewm(
            span=20,
            adjust=False,
        ).mean()

        ema50_series = close.ewm(
            span=50,
            adjust=False,
        ).mean()

        ema200_series = close.ewm(
            span=200,
            adjust=False,
        ).mean()

        ema20 = float(ema20_series.iloc[-1])
        ema50 = float(ema50_series.iloc[-1])
        ema200 = float(ema200_series.iloc[-1])

        # During market hours use live LTP for current positioning.
        current_price = (
            float(live.ltp)
            if live.ltp > 0
            else float(close.iloc[-1])
        )

        rsi14 = self._rsi(
            close,
            period=Config.RSI_PERIOD,
        )

        return_5d = self._period_return(
            close,
            periods=5,
        )

        return_20d = self._period_return(
            close,
            periods=Config.RELATIVE_STRENGTH_LOOKBACK,
        )

        rs20 = 0.0

        if benchmark_df is not None and not benchmark_df.empty:
            benchmark_close = (
                benchmark_df["close"]
                .astype(float)
            )

            benchmark_return = self._period_return(
                benchmark_close,
                periods=Config.RELATIVE_STRENGTH_LOOKBACK,
            )

            rs20 = return_20d - benchmark_return

        high20 = float(
            df["high"]
            .astype(float)
            .tail(20)
            .max()
        )

        high52 = float(
            df["high"]
            .astype(float)
            .tail(252)
            .max()
        )

        distance20 = self._distance_below_high(
            current_price,
            high20,
        )

        distance52 = self._distance_below_high(
            current_price,
            high52,
        )

        above20 = current_price > ema20
        above50 = current_price > ema50
        above200 = current_price > ema200

        bullish_structure = (
            current_price > ema20
            and ema20 > ema50
            and ema50 > ema200
        )

        trend_score = self._calculate_trend_score(
            current_price=current_price,
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            rsi=rsi14,
            return_5d=return_5d,
            return_20d=return_20d,
            relative_strength=rs20,
        )

        return IndexTechnicalSnapshot(
            key=key,
            name=name or key or live.name,
            fyers_symbol=live.fyers_symbol,
            ltp=current_price,
            change_percent=live.change_percent,
            return_5d=return_5d,
            return_20d=return_20d,
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            above_ema20=above20,
            above_ema50=above50,
            above_ema200=above200,
            bullish_ema_structure=bullish_structure,
            rsi14=rsi14,
            relative_strength_20d=rs20,
            distance_from_20d_high_pct=distance20,
            distance_from_52w_high_pct=distance52,
            trend_score=trend_score,
            source=live.source,
        )

    # ========================================================
    # ALL SECTOR TECHNICAL DATA
    # ========================================================

    def get_all_sector_technical_snapshots(
        self,
    ) -> list[IndexTechnicalSnapshot]:
        nifty = BENCHMARK_INDICES["NIFTY_50"]

        benchmark_df = self.get_daily_dataframe(
            nifty["fyers_symbol"],
            candle_count=260,
            min_required=220,
        )

        result: list[IndexTechnicalSnapshot] = []

        for sector in get_candidate_sectors():
            try:
                snapshot = self.get_technical_snapshot(
                    sector["fyers_symbol"],
                    key=sector["key"],
                    name=sector["name"],
                    benchmark_df=benchmark_df,
                )
            except Exception:
                # One unavailable index must not fabricate data or destroy
                # ranking of other valid sector indices.
                continue

            result.append(snapshot)

        return result

    # ========================================================
    # DASHBOARD SERIALIZATION
    # ========================================================

    def dashboard_indices(
        self,
    ) -> list[dict[str, Any]]:
        return [
            asdict(item)
            for item in self.get_benchmark_snapshots()
        ]

    def dashboard_sectors(
        self,
    ) -> list[dict[str, Any]]:
        return [
            asdict(item)
            for item in self.get_sector_snapshots()
        ]

    # ========================================================
    # TECHNICAL HELPERS
    # ========================================================

    @staticmethod
    def _period_return(
        close: pd.Series,
        *,
        periods: int,
    ) -> float:
        if len(close) <= periods:
            return 0.0

        previous = float(
            close.iloc[-(periods + 1)]
        )

        current = float(close.iloc[-1])

        if previous <= 0:
            return 0.0

        return (
            (current - previous)
            / previous
        ) * 100.0

    @staticmethod
    def _rsi(
        close: pd.Series,
        *,
        period: int = 14,
    ) -> float:
        if len(close) <= period:
            return 50.0

        delta = close.diff()

        gains = delta.clip(lower=0.0)
        losses = -delta.clip(upper=0.0)

        avg_gain = gains.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        avg_loss = losses.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        loss = float(avg_loss.iloc[-1])
        gain = float(avg_gain.iloc[-1])

        if loss == 0.0:
            if gain > 0.0:
                return 100.0
            return 50.0

        rs = gain / loss

        return float(
            100.0
            - (100.0 / (1.0 + rs))
        )

    @staticmethod
    def _distance_below_high(
        price: float,
        high: float,
    ) -> float:
        if high <= 0:
            return 0.0

        return max(
            0.0,
            ((high - price) / high) * 100.0,
        )

    @staticmethod
    def _calculate_trend_score(
        *,
        current_price: float,
        ema20: float,
        ema50: float,
        ema200: float,
        rsi: float,
        return_5d: float,
        return_20d: float,
        relative_strength: float,
    ) -> float:
        """
        0-100 technical trend score.

        SectorScanner applies its own sector-selection conditions on top.
        """
        score = 0.0

        if current_price > ema20:
            score += 15.0

        if ema20 > ema50:
            score += 15.0

        if ema50 > ema200:
            score += 15.0

        if 50.0 <= rsi <= 75.0:
            score += 15.0
        elif rsi > 75.0:
            score += 7.5

        if return_5d > 0:
            score += 10.0

        if return_20d > 0:
            score += 15.0

        if relative_strength > Config.MIN_RELATIVE_STRENGTH_PCT:
            score += 15.0

        return round(
            min(max(score, 0.0), 100.0),
            2,
        )


# ============================================================
# SINGLETON
# ============================================================

_default_index_service: IndexService | None = None
_default_index_service_lock = threading.Lock()


def get_index_service() -> IndexService:
    global _default_index_service

    if _default_index_service is not None:
        return _default_index_service

    with _default_index_service_lock:
        if _default_index_service is None:
            _default_index_service = IndexService()

    return _default_index_service


# ============================================================
# BACKWARD-COMPATIBLE HELPERS
# ============================================================

def get_index_snapshot(
    symbol: str,
    *,
    key: str = "",
    name: str = "",
) -> IndexSnapshot:
    return get_index_service().get_index_snapshot(
        symbol=symbol,
        key=key,
        name=name,
    )


def get_sector_snapshots() -> list[IndexSnapshot]:
    return get_index_service().get_sector_snapshots()


def get_all_sector_technical_snapshots(
) -> list[IndexTechnicalSnapshot]:
    return (
        get_index_service()
        .get_all_sector_technical_snapshots()
    )
