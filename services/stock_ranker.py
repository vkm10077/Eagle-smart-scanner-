from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from config import Config
from data.nse_universe import NSEStock


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RankedStock:
    symbol: str
    company_name: str
    sector: str
    score: float
    momentum_score: float
    trend_score: float
    volume_score: float
    rsi_score: float
    relative_strength_score: float

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "sector": self.sector,
            "score": round(self.score, 2),
            "momentum_score": round(
                self.momentum_score,
                2,
            ),
            "trend_score": round(
                self.trend_score,
                2,
            ),
            "volume_score": round(
                self.volume_score,
                2,
            ),
            "rsi_score": round(
                self.rsi_score,
                2,
            ),
            "relative_strength_score": round(
                self.relative_strength_score,
                2,
            ),
        }


def _clamp(
    value: float,
    minimum: float = 0.0,
    maximum: float = 100.0,
) -> float:
    return max(
        minimum,
        min(float(value), maximum),
    )


def _momentum_score(
    metrics: dict,
) -> float:
    change_1d = float(
        metrics.get("change_1d_pct", 0.0)
        or 0.0
    )

    change_5d = float(
        metrics.get("change_5d_pct", 0.0)
        or 0.0
    )

    change_20d = float(
        metrics.get("change_20d_pct", 0.0)
        or 0.0
    )

    score = (
        50.0
        + change_1d * 5.0
        + change_5d * 2.0
        + change_20d
    )

    return _clamp(score)


def _trend_score(
    metrics: dict,
) -> float:
    score = 0.0

    if metrics.get("above_ema20") is True:
        score += 30.0

    if metrics.get("above_ema50") is True:
        score += 30.0

    if metrics.get("above_ema200") is True:
        score += 25.0

    if metrics.get("bullish") is True:
        score += 15.0

    return _clamp(score)


def _volume_score(
    metrics: dict,
) -> float:
    ratio = float(
        metrics.get("volume_ratio", 0.0)
        or 0.0
    )

    return _clamp(
        ratio * 50.0
    )


def _rsi_score(
    metrics: dict,
) -> float:
    rsi = float(
        metrics.get("rsi", 0.0)
        or 0.0
    )

    if rsi <= 0:
        return 0.0

    if 55.0 <= rsi <= 70.0:
        return 100.0

    if 50.0 <= rsi < 55.0:
        return 75.0

    if 70.0 < rsi <= 75.0:
        return 70.0

    if 45.0 <= rsi < 50.0:
        return 50.0

    if 75.0 < rsi <= 80.0:
        return 40.0

    return 20.0


def _relative_strength_score(
    metrics: dict,
) -> float:
    rs = float(
        metrics.get(
            "relative_strength_pct",
            0.0,
        )
        or 0.0
    )

    return _clamp(
        50.0 + rs * 5.0
    )


def calculate_stock_score(
    stock: NSEStock,
    metrics: dict,
) -> RankedStock:
    momentum = _momentum_score(
        metrics
    )

    trend = _trend_score(
        metrics
    )

    volume = _volume_score(
        metrics
    )

    rsi = _rsi_score(
        metrics
    )

    relative_strength = (
        _relative_strength_score(
            metrics
        )
    )

    final_score = (
        momentum * 0.25
        + trend * 0.30
        + volume * 0.15
        + rsi * 0.15
        + relative_strength * 0.15
    )

    return RankedStock(
        symbol=stock.symbol,
        company_name=stock.company_name,
        sector=stock.sector,
        score=_clamp(final_score),
        momentum_score=momentum,
        trend_score=trend,
        volume_score=volume,
        rsi_score=rsi,
        relative_strength_score=relative_strength,
    )


def rank_sector_stocks(
    sector: str,
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[str, dict],
) -> list[RankedStock]:
    """
    Rank all technically available stocks
    inside one selected sector.
    """

    ranked: list[RankedStock] = []

    for stock in stocks:
        if stock.sector != sector:
            continue

        metrics = metrics_by_symbol.get(
            stock.symbol
        )

        if not metrics:
            continue

        ranked_stock = calculate_stock_score(
            stock=stock,
            metrics=metrics,
        )

        ranked.append(
            ranked_stock
        )

    ranked.sort(
        key=lambda item: (
            -item.score,
            -item.trend_score,
            -item.momentum_score,
            -item.volume_score,
            item.symbol,
        )
    )

    return ranked


def get_top_stocks_for_sector(
    sector: str,
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[str, dict],
    limit: int | None = None,
) -> list[RankedStock]:
    """
    Return only Top N stocks from one sector.

    Default:
        Config.TOP_STOCKS_PER_SECTOR = 10
    """

    if limit is None:
        limit = Config.TOP_STOCKS_PER_SECTOR

    safe_limit = max(
        1,
        int(limit),
    )

    ranked = rank_sector_stocks(
        sector=sector,
        stocks=stocks,
        metrics_by_symbol=metrics_by_symbol,
    )

    return ranked[:safe_limit]


def build_top_sector_stock_universe(
    top_sectors: Iterable[str],
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[str, dict],
) -> list[RankedStock]:
    """
    Build the final candidate universe:

    Top 10 sectors
    ×
    Top 10 stocks per sector

    Maximum = 100 stocks
    """

    stock_list = list(stocks)

    output: list[RankedStock] = []
    seen_symbols: set[str] = set()

    for sector in top_sectors:
        top_stocks = get_top_stocks_for_sector(
            sector=sector,
            stocks=stock_list,
            metrics_by_symbol=metrics_by_symbol,
            limit=Config.TOP_STOCKS_PER_SECTOR,
        )

        for stock in top_stocks:
            if stock.symbol in seen_symbols:
                continue

            seen_symbols.add(
                stock.symbol
            )

            output.append(
                stock
            )

    return output
