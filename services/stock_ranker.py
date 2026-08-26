from __future__ import annotations

"""
Eagle Smart Scanner - Stock Ranker

Ranks official constituents of each selected strong NSE sector and chooses
the Top N stocks per sector for deep Intraday / BTST / Swing scanning.

Pure technical pre-ranking only:
- Live momentum
- EMA trend structure
- RSI
- 5D / 20D momentum
- Relative strength vs sector
- Volume expansion
- 20-day breakout proximity
- 52-week-high proximity

No fundamentals. No NIFTY500 master universe. No fake/random data.
"""

import threading
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from config import Config
from services.market_data_service import (
    MarketDataService,
    get_market_data_service,
)
from services.nse_sector_universe_service import (
    NSESectorUniverseService,
    SectorConstituent,
    get_nse_sector_universe_service,
)
from services.sector_scanner import (
    SectorScanResult,
    get_sector_scanner,
)


class StockRankerError(RuntimeError):
    """Stock pre-ranking error."""


@dataclass(frozen=True)
class RankedStock:
    rank: int
    sector_rank: int
    sector_key: str
    sector_name: str
    sector_score: float

    symbol: str
    fyers_symbol: str
    company_name: str
    industry: str

    ltp: float
    change_percent: float

    return_5d: float
    return_20d: float
    sector_return_20d: float
    relative_strength_vs_sector: float

    ema20: float
    ema50: float
    ema200: float
    bullish_ema_structure: bool

    rsi14: float
    volume_ratio: float

    distance_from_20d_high_pct: float
    distance_from_52w_high_pct: float

    score: float
    eligible: bool
    reasons: tuple[str, ...]


class StockRanker:
    """
    Selects the strongest stocks from official constituents of strong sectors.
    """

    def __init__(
        self,
        market_data: MarketDataService | None = None,
        universe_service: NSESectorUniverseService | None = None,
    ) -> None:
        self.market_data = (
            market_data
            or get_market_data_service()
        )
        self.universe_service = (
            universe_service
            or get_nse_sector_universe_service()
        )

        self._lock = threading.RLock()
        self._last_results: dict[
            str,
            list[RankedStock],
        ] = {}

    # ========================================================
    # MAIN RANKING
    # ========================================================

    def rank_sector(
        self,
        sector: SectorScanResult,
        *,
        top_n: int | None = None,
    ) -> list[RankedStock]:
        constituents = (
            self.universe_service
            .get_sector_constituents(
                sector.sector_key
            )
        )

        if not constituents:
            return []

        # Sector historical frame is the benchmark for stock RS.
        sector_df = self.market_data.get_dataframe(
            symbol=sector.fyers_symbol,
            resolution="D",
            candle_count=260,
            min_required=220,
        )

        sector_return_20d = self._period_return(
            sector_df["close"].astype(float),
            Config.RELATIVE_STRENGTH_LOOKBACK,
        )

        # Batch live quotes first to avoid one REST call per stock.
        quotes = self.market_data.get_quotes(
            [
                item.fyers_symbol
                for item in constituents
            ],
            prefer_websocket=True,
        )

        quote_map = {
            quote.fyers_symbol.upper(): quote
            for quote in quotes
        }

        ranked: list[RankedStock] = []

        for constituent in constituents:
            quote = quote_map.get(
                constituent.fyers_symbol.upper()
            )

            if quote is None:
                continue

            try:
                item = self._evaluate_stock(
                    constituent=constituent,
                    sector=sector,
                    quote=quote,
                    sector_return_20d=sector_return_20d,
                )
            except Exception:
                # Never fabricate missing stock data.
                continue

            ranked.append(item)

        ranked.sort(
            key=lambda item: (
                1 if item.eligible else 0,
                item.score,
                item.relative_strength_vs_sector,
                item.change_percent,
                item.return_20d,
                item.volume_ratio,
            ),
            reverse=True,
        )

        final: list[RankedStock] = []

        for rank, item in enumerate(
            ranked,
            start=1,
        ):
            final.append(
                RankedStock(
                    rank=rank,
                    sector_rank=sector.rank,
                    sector_key=item.sector_key,
                    sector_name=item.sector_name,
                    sector_score=item.sector_score,
                    symbol=item.symbol,
                    fyers_symbol=item.fyers_symbol,
                    company_name=item.company_name,
                    industry=item.industry,
                    ltp=item.ltp,
                    change_percent=item.change_percent,
                    return_5d=item.return_5d,
                    return_20d=item.return_20d,
                    sector_return_20d=(
                        item.sector_return_20d
                    ),
                    relative_strength_vs_sector=(
                        item.relative_strength_vs_sector
                    ),
                    ema20=item.ema20,
                    ema50=item.ema50,
                    ema200=item.ema200,
                    bullish_ema_structure=(
                        item.bullish_ema_structure
                    ),
                    rsi14=item.rsi14,
                    volume_ratio=item.volume_ratio,
                    distance_from_20d_high_pct=(
                        item.distance_from_20d_high_pct
                    ),
                    distance_from_52w_high_pct=(
                        item.distance_from_52w_high_pct
                    ),
                    score=item.score,
                    eligible=item.eligible,
                    reasons=item.reasons,
                )
            )

        with self._lock:
            self._last_results[
                sector.sector_key
            ] = list(final)

        limit = int(
            top_n
            if top_n is not None
            else Config.TOP_STOCKS_PER_SECTOR
        )

        if limit <= 0:
            return []

        return [
            item
            for item in final
            if item.eligible
        ][:limit]

    def rank_top_sectors(
        self,
        sectors: list[SectorScanResult] | None = None,
    ) -> dict[str, list[RankedStock]]:
        if sectors is None:
            sectors = (
                get_sector_scanner()
                .scan(
                    top_n=Config.TOP_SECTORS_COUNT
                )
            )

        result: dict[
            str,
            list[RankedStock],
        ] = {}

        for sector in sectors[
            : Config.TOP_SECTORS_COUNT
        ]:
            try:
                stocks = self.rank_sector(
                    sector,
                    top_n=(
                        Config.TOP_STOCKS_PER_SECTOR
                    ),
                )
            except Exception:
                continue

            if stocks:
                result[
                    sector.sector_key
                ] = stocks

        return result

    def build_scanner_universe(
        self,
        sectors: list[SectorScanResult] | None = None,
    ) -> list[RankedStock]:
        grouped = self.rank_top_sectors(
            sectors=sectors
        )

        universe: list[RankedStock] = []

        for stocks in grouped.values():
            universe.extend(stocks)

        # Hard safety ceiling from Config.
        return universe[
            : Config.MAX_SCANNER_UNIVERSE
        ]

    # ========================================================
    # STOCK EVALUATION
    # ========================================================

    def _evaluate_stock(
        self,
        *,
        constituent: SectorConstituent,
        sector: SectorScanResult,
        quote: Any,
        sector_return_20d: float,
    ) -> RankedStock:
        df = self.market_data.get_dataframe(
            symbol=constituent.fyers_symbol,
            resolution="D",
            candle_count=260,
            min_required=220,
        )

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        volume = df["volume"].astype(float)

        ema20 = float(
            close.ewm(
                span=Config.EMA_FAST,
                adjust=False,
            ).mean().iloc[-1]
        )

        ema50 = float(
            close.ewm(
                span=Config.EMA_MEDIUM,
                adjust=False,
            ).mean().iloc[-1]
        )

        ema200 = float(
            close.ewm(
                span=Config.EMA_LONG,
                adjust=False,
            ).mean().iloc[-1]
        )

        ltp = float(quote.ltp)

        bullish_ema = (
            ltp > ema20
            and ema20 > ema50
            and ema50 > ema200
        )

        rsi = self._rsi(
            close,
            Config.RSI_PERIOD,
        )

        return_5d = self._period_return(
            close,
            5,
        )

        return_20d = self._period_return(
            close,
            Config.RELATIVE_STRENGTH_LOOKBACK,
        )

        rs_sector = (
            return_20d
            - sector_return_20d
        )

        avg_volume = float(
            volume.tail(
                Config.VOLUME_AVG_PERIOD
            ).mean()
        )

        current_volume = float(
            quote.volume
            if float(quote.volume) > 0
            else volume.iloc[-1]
        )

        volume_ratio = (
            current_volume / avg_volume
            if avg_volume > 0
            else 0.0
        )

        high20 = float(
            high.tail(20).max()
        )

        high52 = float(
            high.tail(252).max()
        )

        distance20 = self._distance_below_high(
            ltp,
            high20,
        )

        distance52 = self._distance_below_high(
            ltp,
            high52,
        )

        score, reasons = self._score_stock(
            ltp=ltp,
            change_percent=float(
                quote.change_percent
            ),
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            bullish_ema=bullish_ema,
            rsi=rsi,
            return_5d=return_5d,
            return_20d=return_20d,
            relative_strength_vs_sector=(
                rs_sector
            ),
            volume_ratio=volume_ratio,
            distance20=distance20,
            distance52=distance52,
        )

        eligible = self._is_eligible(
            ltp=ltp,
            ema20=ema20,
            ema50=ema50,
            rsi=rsi,
            return_20d=return_20d,
            relative_strength_vs_sector=(
                rs_sector
            ),
            score=score,
        )

        if not eligible:
            reasons.append(
                "Failed stock pre-ranking eligibility"
            )

        return RankedStock(
            rank=0,
            sector_rank=sector.rank,
            sector_key=sector.sector_key,
            sector_name=sector.sector_name,
            sector_score=sector.score,
            symbol=constituent.symbol,
            fyers_symbol=(
                constituent.fyers_symbol
            ),
            company_name=(
                constituent.company_name
            ),
            industry=constituent.industry,
            ltp=ltp,
            change_percent=float(
                quote.change_percent
            ),
            return_5d=return_5d,
            return_20d=return_20d,
            sector_return_20d=(
                sector_return_20d
            ),
            relative_strength_vs_sector=(
                rs_sector
            ),
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            bullish_ema_structure=(
                bullish_ema
            ),
            rsi14=rsi,
            volume_ratio=volume_ratio,
            distance_from_20d_high_pct=(
                distance20
            ),
            distance_from_52w_high_pct=(
                distance52
            ),
            score=score,
            eligible=eligible,
            reasons=tuple(reasons),
        )

    # ========================================================
    # SCORE
    # ========================================================

    @staticmethod
    def _score_stock(
        *,
        ltp: float,
        change_percent: float,
        ema20: float,
        ema50: float,
        ema200: float,
        bullish_ema: bool,
        rsi: float,
        return_5d: float,
        return_20d: float,
        relative_strength_vs_sector: float,
        volume_ratio: float,
        distance20: float,
        distance52: float,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        # Trend: 25
        if bullish_ema:
            score += 25.0
            reasons.append(
                "Bullish EMA20 > EMA50 > EMA200"
            )
        else:
            if ltp > ema20:
                score += 8.0
            if ltp > ema50:
                score += 6.0
            if ltp > ema200:
                score += 4.0

        # RSI: 10
        if 55.0 <= rsi <= 70.0:
            score += 10.0
            reasons.append("Healthy bullish RSI")
        elif 50.0 <= rsi < 55.0:
            score += 7.0
        elif 70.0 < rsi <= 75.0:
            score += 5.0

        # Momentum: 15
        if return_5d > 0:
            score += 5.0
        if return_5d >= 2.0:
            score += 2.0
        if return_20d > 0:
            score += 5.0
        if return_20d >= 5.0:
            score += 3.0

        # RS vs sector: 15
        if relative_strength_vs_sector >= 5.0:
            score += 15.0
            reasons.append(
                "Strongly outperforming sector"
            )
        elif relative_strength_vs_sector >= 2.0:
            score += 12.0
            reasons.append(
                "Outperforming sector"
            )
        elif relative_strength_vs_sector > 0:
            score += 8.0

        # Volume: 15
        if volume_ratio >= Config.STRONG_VOLUME_RATIO:
            score += 15.0
            reasons.append(
                "Strong volume expansion"
            )
        elif volume_ratio >= Config.SWING_MIN_VOLUME_RATIO:
            score += 10.0
        elif volume_ratio >= 1.0:
            score += 5.0

        # Breakout proximity: 10
        if distance20 <= 1.0:
            score += 10.0
            reasons.append(
                "Near 20-day breakout"
            )
        elif distance20 <= 3.0:
            score += 7.0
        elif distance20 <= 5.0:
            score += 4.0

        # 52-week position: 5
        if distance52 <= 5.0:
            score += 5.0
        elif distance52 <= 10.0:
            score += 3.0

        # Live momentum: 5
        if change_percent >= 1.0:
            score += 5.0
        elif change_percent > 0:
            score += 3.0

        return (
            round(
                min(max(score, 0.0), 100.0),
                2,
            ),
            reasons,
        )

    # ========================================================
    # PRE-RANK ELIGIBILITY
    # ========================================================

    @staticmethod
    def _is_eligible(
        *,
        ltp: float,
        ema20: float,
        ema50: float,
        rsi: float,
        return_20d: float,
        relative_strength_vs_sector: float,
        score: float,
    ) -> bool:
        if ltp <= 0:
            return False

        # Pre-ranking is intentionally less strict than final signal logic.
        # Deep technical scanner will apply mode-specific mandatory rules.
        if ltp <= ema20:
            return False

        if ltp <= ema50:
            return False

        if rsi < 48.0 or rsi > 78.0:
            return False

        if return_20d <= -3.0:
            return False

        if relative_strength_vs_sector < -3.0:
            return False

        if score < Config.MIN_STOCK_RANK_SCORE:
            return False

        return True

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _period_return(
        close: pd.Series,
        periods: int,
    ) -> float:
        if len(close) <= periods:
            return 0.0

        previous = float(
            close.iloc[-(periods + 1)]
        )
        current = float(
            close.iloc[-1]
        )

        if previous <= 0:
            return 0.0

        return (
            (current - previous)
            / previous
        ) * 100.0

    @staticmethod
    def _rsi(
        close: pd.Series,
        period: int,
    ) -> float:
        if len(close) <= period:
            return 50.0

        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)

        avg_gain = gain.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        avg_loss = loss.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        latest_gain = float(
            avg_gain.iloc[-1]
        )
        latest_loss = float(
            avg_loss.iloc[-1]
        )

        if latest_loss == 0:
            return (
                100.0
                if latest_gain > 0
                else 50.0
            )

        rs = (
            latest_gain
            / latest_loss
        )

        return float(
            100.0
            - (
                100.0
                / (1.0 + rs)
            )
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
            (
                (high - price)
                / high
            ) * 100.0,
        )

    # ========================================================
    # LAST RESULTS / SERIALIZATION
    # ========================================================

    def get_last_results(
        self,
    ) -> dict[str, list[RankedStock]]:
        with self._lock:
            return {
                key: list(value)
                for key, value
                in self._last_results.items()
            }

    def rank_top_sectors_as_dicts(
        self,
        sectors: list[SectorScanResult] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        grouped = self.rank_top_sectors(
            sectors=sectors
        )

        return {
            sector: [
                asdict(item)
                for item in stocks
            ]
            for sector, stocks
            in grouped.items()
        }


# ============================================================
# SINGLETON
# ============================================================

_default_stock_ranker: StockRanker | None = None
_default_stock_ranker_lock = threading.Lock()


def get_stock_ranker() -> StockRanker:
    global _default_stock_ranker

    if _default_stock_ranker is not None:
        return _default_stock_ranker

    with _default_stock_ranker_lock:
        if _default_stock_ranker is None:
            _default_stock_ranker = (
                StockRanker()
            )

    return _default_stock_ranker


# ============================================================
# MODULE HELPERS
# ============================================================

def rank_sector_stocks(
    sector: SectorScanResult,
    *,
    top_n: int | None = None,
) -> list[RankedStock]:
    return (
        get_stock_ranker()
        .rank_sector(
            sector,
            top_n=top_n,
        )
    )


def build_scanner_universe(
    sectors: list[SectorScanResult] | None = None,
) -> list[RankedStock]:
    return (
        get_stock_ranker()
        .build_scanner_universe(
            sectors=sectors
        )
    )
