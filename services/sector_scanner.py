from __future__ import annotations

import logging
from dataclasses import dataclass
from statistics import mean
from typing import Iterable

from config import Config
from data.nse_universe import NSEStock


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SectorScore:
    sector: str
    score: float
    momentum_score: float
    trend_score: float
    breadth_score: float
    volume_score: float
    relative_strength_score: float
    stock_count: int

    def to_dict(self) -> dict:
        return {
            "sector": self.sector,
            "score": round(self.score, 2),
            "momentum_score": round(self.momentum_score, 2),
            "trend_score": round(self.trend_score, 2),
            "breadth_score": round(self.breadth_score, 2),
            "volume_score": round(self.volume_score, 2),
            "relative_strength_score": round(
                self.relative_strength_score,
                2,
            ),
            "stock_count": self.stock_count,
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


def _average(values: Iterable[float]) -> float:
    clean_values = [
        float(value)
        for value in values
        if value is not None
    ]

    if not clean_values:
        return 0.0

    return mean(clean_values)


def _score_momentum(
    stock_metrics: list[dict],
) -> float:
    """
    Momentum input expected per stock:

    {
        "change_1d_pct": float,
        "change_5d_pct": float,
        "change_20d_pct": float,
    }
    """

    if not stock_metrics:
        return 0.0

    one_day = _average(
        item.get("change_1d_pct", 0.0)
        for item in stock_metrics
    )

    five_day = _average(
        item.get("change_5d_pct", 0.0)
        for item in stock_metrics
    )

    twenty_day = _average(
        item.get("change_20d_pct", 0.0)
        for item in stock_metrics
    )

    raw_score = (
        50.0
        + one_day * 5.0
        + five_day * 2.0
        + twenty_day * 1.0
    )

    return _clamp(raw_score)


def _score_trend(
    stock_metrics: list[dict],
) -> float:
    """
    Trend strength measures how many stocks are trading
    above important EMAs.
    """

    if not stock_metrics:
        return 0.0

    total = len(stock_metrics)

    above_20 = sum(
        1
        for item in stock_metrics
        if item.get("above_ema20") is True
    )

    above_50 = sum(
        1
        for item in stock_metrics
        if item.get("above_ema50") is True
    )

    above_200 = sum(
        1
        for item in stock_metrics
        if item.get("above_ema200") is True
    )

    ema20_score = (
        above_20 / total
    ) * 100.0

    ema50_score = (
        above_50 / total
    ) * 100.0

    ema200_score = (
        above_200 / total
    ) * 100.0

    return _clamp(
        ema20_score * 0.40
        + ema50_score * 0.35
        + ema200_score * 0.25
    )


def _score_breadth(
    stock_metrics: list[dict],
) -> float:
    """
    Breadth = percentage of stocks showing bullish structure.
    """

    if not stock_metrics:
        return 0.0

    total = len(stock_metrics)

    bullish_count = sum(
        1
        for item in stock_metrics
        if item.get("bullish") is True
    )

    return _clamp(
        (
            bullish_count
            / total
        )
        * 100.0
    )


def _score_volume(
    stock_metrics: list[dict],
) -> float:
    """
    Sector volume strength from average current-volume /
    average-volume ratio.
    """

    if not stock_metrics:
        return 0.0

    volume_ratios = [
        float(
            item.get(
                "volume_ratio",
                0.0,
            )
            or 0.0
        )
        for item in stock_metrics
    ]

    avg_ratio = _average(volume_ratios)

    # 1.0 ratio -> 50 score
    # 1.5 ratio -> 75 score
    # 2.0 ratio -> 100 score

    raw_score = avg_ratio * 50.0

    return _clamp(raw_score)


def _score_relative_strength(
    stock_metrics: list[dict],
) -> float:
    """
    Relative strength compared with benchmark/index.

    Expected input:
        relative_strength_pct

    Positive = outperforming benchmark.
    """

    if not stock_metrics:
        return 0.0

    rs = _average(
        item.get(
            "relative_strength_pct",
            0.0,
        )
        for item in stock_metrics
    )

    raw_score = 50.0 + rs * 5.0

    return _clamp(raw_score)


def calculate_sector_score(
    sector: str,
    stock_metrics: list[dict],
) -> SectorScore:
    """
    Calculate one final technical strength score
    for a sector.
    """

    momentum = _score_momentum(
        stock_metrics
    )

    trend = _score_trend(
        stock_metrics
    )

    breadth = _score_breadth(
        stock_metrics
    )

    volume = _score_volume(
        stock_metrics
    )

    relative_strength = (
        _score_relative_strength(
            stock_metrics
        )
    )

    # Final sector score weights
    final_score = (
        momentum * 0.25
        + trend * 0.25
        + breadth * 0.20
        + volume * 0.15
        + relative_strength * 0.15
    )

    return SectorScore(
        sector=sector,
        score=_clamp(final_score),
        momentum_score=momentum,
        trend_score=trend,
        breadth_score=breadth,
        volume_score=volume,
        relative_strength_score=relative_strength,
        stock_count=len(stock_metrics),
    )


def rank_sectors(
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[str, dict],
) -> list[SectorScore]:
    """
    Group stocks by sector and rank every sector
    using technical metrics.

    metrics_by_symbol example:

    {
        "RELIANCE": {
            "change_1d_pct": 1.2,
            "change_5d_pct": 3.4,
            "change_20d_pct": 8.1,
            "above_ema20": True,
            "above_ema50": True,
            "above_ema200": True,
            "bullish": True,
            "volume_ratio": 1.6,
            "relative_strength_pct": 2.1,
        }
    }
    """

    sector_metrics: dict[
        str,
        list[dict],
    ] = {}

    for stock in stocks:
        metrics = metrics_by_symbol.get(
            stock.symbol
        )

        if not metrics:
            continue

        sector_metrics.setdefault(
            stock.sector,
            [],
        ).append(metrics)

    results: list[SectorScore] = []

    for sector, metrics in sector_metrics.items():
        if not metrics:
            continue

        result = calculate_sector_score(
            sector=sector,
            stock_metrics=metrics,
        )

        results.append(result)

    results.sort(
        key=lambda item: (
            -item.score,
            -item.breadth_score,
            -item.trend_score,
            item.sector,
        )
    )

    return results


def get_top_sectors(
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[str, dict],
    limit: int | None = None,
) -> list[SectorScore]:
    """
    Return only strongest sectors.

    Default:
        Config.TOP_SECTORS_COUNT = 10
    """

    if limit is None:
        limit = Config.TOP_SECTORS_COUNT

    safe_limit = max(
        1,
        int(limit),
    )

    ranked = rank_sectors(
        stocks=stocks,
        metrics_by_symbol=metrics_by_symbol,
    )

    return ranked[:safe_limit]


def get_top_sector_names(
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[str, dict],
    limit: int | None = None,
) -> list[str]:
    top_sectors = get_top_sectors(
        stocks=stocks,
        metrics_by_symbol=metrics_by_symbol,
        limit=limit,
    )

    return [
        item.sector
        for item in top_sectors
    ]
