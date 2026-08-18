from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from config import Config
from data.nse_universe import NSEStock
from utils.helpers import (
    normalize_symbol,
    safe_float,
)


# ============================================================
# CONSTANTS
# ============================================================


BTST_MODE = getattr(
    Config,
    "MODE_BTST",
    "btst",
)


# ============================================================
# RESULT MODEL
# ============================================================


@dataclass(frozen=True)
class RankedStock:
    """
    Technical ranking result for one stock
    inside a selected NSE sector.

    IMPORTANT:

    Ranking != STRONG BUY

    RANKED:
        Stock is a Top-N technical candidate.

    STRONG BUY:
        Stock has separately passed the final
        Eagle technical scanner.
    """

    symbol: str
    company_name: str
    sector: str
    mode: str

    score: float

    momentum_score: float
    trend_score: float
    volume_score: float
    rsi_score: float
    relative_strength_score: float

    macd_score: float
    supertrend_score: float
    vwap_score: float
    breakout_score: float
    multi_timeframe_score: float

    strong_buy: bool = False

    def to_dict(
        self,
    ) -> dict[str, Any]:

        is_strong_buy = bool(
            self.strong_buy
        )

        return {
            "symbol": self.symbol,

            "company_name": (
                self.company_name
            ),

            "sector": self.sector,

            "mode": self.mode,

            "score": round(
                float(
                    self.score
                ),
                2,
            ),

            "momentum_score": round(
                float(
                    self.momentum_score
                ),
                2,
            ),

            "trend_score": round(
                float(
                    self.trend_score
                ),
                2,
            ),

            "volume_score": round(
                float(
                    self.volume_score
                ),
                2,
            ),

            "rsi_score": round(
                float(
                    self.rsi_score
                ),
                2,
            ),

            "relative_strength_score": round(
                float(
                    self.relative_strength_score
                ),
                2,
            ),

            "macd_score": round(
                float(
                    self.macd_score
                ),
                2,
            ),

            "supertrend_score": round(
                float(
                    self.supertrend_score
                ),
                2,
            ),

            "vwap_score": round(
                float(
                    self.vwap_score
                ),
                2,
            ),

            "breakout_score": round(
                float(
                    self.breakout_score
                ),
                2,
            ),

            "multi_timeframe_score": round(
                float(
                    self.multi_timeframe_score
                ),
                2,
            ),

            "strong_buy": (
                is_strong_buy
            ),

            "signal": (
                "STRONG BUY"
                if is_strong_buy
                else "RANKED"
            ),
        }


# ============================================================
# HELPERS
# ============================================================


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:

    number = safe_float(
        value
    )

    if number is None:
        return float(
            default
        )

    return float(
        number
    )


def _clamp(
    value: float,
    minimum: float = 0.0,
    maximum: float = 100.0,
) -> float:

    number = _safe_float(
        value
    )

    return max(
        float(
            minimum
        ),
        min(
            number,
            float(
                maximum
            ),
        ),
    )


def _normalize_mode(
    mode: str | None,
) -> str:
    """
    Normalize Intraday / BTST / Swing.

    Config.normalize_trading_mode currently
    knows Intraday and Swing.

    BTST is handled independently so this
    file remains compatible until Config
    formally adds MODE_BTST.
    """

    value = str(
        mode
        or Config.DEFAULT_TRADING_MODE
    ).strip().lower()

    if value == BTST_MODE:
        return BTST_MODE

    return (
        Config
        .normalize_trading_mode(
            value
        )
    )


def _metric_bool(
    metrics: dict[str, Any],
    *names: str,
) -> bool:
    """
    Return True if any compatible metric name
    explicitly evaluates to True.

    This supports old and new metric schemas.
    """

    for name in names:

        if (
            name in metrics
            and metrics.get(
                name
            ) is True
        ):
            return True

    return False


# ============================================================
# STRONG BUY SYMBOL NORMALIZATION
# ============================================================


def _normalize_strong_buy_symbols(
    symbols: Iterable[str] | None,
) -> set[str]:

    if symbols is None:
        return set()

    output: set[str] = set()

    for symbol in symbols:

        normalized = (
            normalize_symbol(
                symbol
            )
        )

        if normalized:
            output.add(
                normalized
            )

    return output


# ============================================================
# MOMENTUM
# ============================================================


def _momentum_score(
    metrics: dict[str, Any],
    *,
    mode: str,
) -> float:

    change_1d = _safe_float(
        metrics.get(
            "change_1d_pct"
        )
    )

    change_5d = _safe_float(
        metrics.get(
            "change_5d_pct"
        )
    )

    change_20d = _safe_float(
        metrics.get(
            "change_20d_pct"
        )
    )

    if (
        mode
        == Config.MODE_INTRADAY
    ):

        score = (
            50.0
            + change_1d * 10.0
            + change_5d * 3.0
            + change_20d
        )

    elif mode == BTST_MODE:

        score = (
            50.0
            + change_1d * 8.0
            + change_5d * 3.0
            + change_20d * 1.5
        )

    else:

        score = (
            50.0
            + change_1d * 3.0
            + change_5d * 2.5
            + change_20d * 2.0
        )

    return _clamp(
        score
    )


# ============================================================
# TREND
# ============================================================


def _trend_score(
    metrics: dict[str, Any],
    *,
    mode: str,
) -> float:

    score = 0.0

    above_ema20 = _metric_bool(
        metrics,
        "above_ema20",
    )

    above_ema50 = _metric_bool(
        metrics,
        "above_ema50",
    )

    above_ema200 = _metric_bool(
        metrics,
        "above_ema200",
    )

    bullish = _metric_bool(
        metrics,
        "bullish",
    )

    if (
        mode
        == Config.MODE_INTRADAY
    ):

        if above_ema20:
            score += 30.0

        if above_ema50:
            score += 25.0

        if above_ema200:
            score += 15.0

        if bullish:
            score += 30.0

    elif mode == BTST_MODE:

        if above_ema20:
            score += 30.0

        if above_ema50:
            score += 30.0

        if above_ema200:
            score += 20.0

        if bullish:
            score += 20.0

    else:

        if above_ema20:
            score += 25.0

        if above_ema50:
            score += 30.0

        if above_ema200:
            score += 30.0

        if bullish:
            score += 15.0

    return _clamp(
        score
    )


# ============================================================
# VOLUME
# ============================================================


def _volume_score(
    metrics: dict[str, Any],
) -> float:

    ratio = _safe_float(
        metrics.get(
            "volume_ratio"
        )
    )

    ratio_score = _clamp(
        ratio
        * 50.0
    )

    confirmed = _metric_bool(
        metrics,
        "volume_confirmed",
        "volume_confirmation",
    )

    if confirmed:

        return _clamp(
            ratio_score
            * 0.70
            + 30.0
        )

    return _clamp(
        ratio_score
        * 0.70
    )


# ============================================================
# RSI
# ============================================================


def _rsi_score(
    metrics: dict[str, Any],
    *,
    mode: str,
) -> float:

    rsi = _safe_float(
        metrics.get(
            "rsi"
        )
    )

    if rsi <= 0:
        return 0.0

    # --------------------------------------------------------
    # INTRADAY
    # --------------------------------------------------------

    if (
        mode
        == Config.MODE_INTRADAY
    ):

        if 58.0 <= rsi <= 70.0:
            return 100.0

        if 55.0 <= rsi < 58.0:
            return 85.0

        if 70.0 < rsi <= 75.0:
            return 75.0

        if 50.0 <= rsi < 55.0:
            return 60.0

        if 75.0 < rsi <= 80.0:
            return 40.0

        return 20.0

    # --------------------------------------------------------
    # BTST
    # --------------------------------------------------------

    if mode == BTST_MODE:

        if 58.0 <= rsi <= 68.0:
            return 100.0

        if 55.0 <= rsi < 58.0:
            return 85.0

        if 68.0 < rsi <= 72.0:
            return 80.0

        if 50.0 <= rsi < 55.0:
            return 60.0

        if 72.0 < rsi <= 76.0:
            return 45.0

        return 20.0

    # --------------------------------------------------------
    # SWING
    # --------------------------------------------------------

    if 55.0 <= rsi <= 65.0:
        return 100.0

    if 50.0 <= rsi < 55.0:
        return 80.0

    if 65.0 < rsi <= 72.0:
        return 80.0

    if 45.0 <= rsi < 50.0:
        return 55.0

    if 72.0 < rsi <= 76.0:
        return 45.0

    return 20.0


# ============================================================
# RELATIVE STRENGTH
# ============================================================


def _relative_strength_score(
    metrics: dict[str, Any],
) -> float:

    relative_strength = (
        _safe_float(
            metrics.get(
                "relative_strength_pct"
            )
        )
    )

    return _clamp(
        50.0
        + relative_strength
        * 5.0
    )


# ============================================================
# MACD
# ============================================================


def _macd_score(
    metrics: dict[str, Any],
) -> float:

    if _metric_bool(
        metrics,
        "macd_bullish",
        "macd_buy",
    ):
        return 100.0

    macd = safe_float(
        metrics.get(
            "macd"
        )
    )

    signal = safe_float(
        metrics.get(
            "macd_signal"
        )
    )

    histogram = safe_float(
        metrics.get(
            "macd_histogram"
        )
    )

    if (
        macd is not None
        and signal is not None
        and macd > signal
    ):

        if (
            histogram is not None
            and histogram > 0
        ):
            return 100.0

        return 80.0

    if (
        histogram is not None
        and histogram > 0
    ):
        return 70.0

    return 0.0


# ============================================================
# SUPERTREND
# ============================================================


def _supertrend_score(
    metrics: dict[str, Any],
) -> float:

    if _metric_bool(
        metrics,
        "supertrend_buy",
        "supertrend_bullish",
    ):
        return 100.0

    direction = str(
        metrics.get(
            "supertrend"
        )
        or metrics.get(
            "supertrend_signal"
        )
        or ""
    ).strip().upper()

    if direction in {
        "BUY",
        "BULLISH",
        "UP",
        "1",
    }:
        return 100.0

    return 0.0


# ============================================================
# VWAP
# ============================================================


def _vwap_score(
    metrics: dict[str, Any],
    *,
    mode: str,
) -> float:

    above_vwap = _metric_bool(
        metrics,
        "above_vwap",
        "price_above_vwap",
    )

    if above_vwap:
        return 100.0

    current_price = safe_float(
        metrics.get(
            "current_price"
        )
    )

    vwap = safe_float(
        metrics.get(
            "vwap"
        )
    )

    if (
        current_price is not None
        and vwap is not None
        and current_price > 0
        and vwap > 0
    ):

        if current_price > vwap:
            return 100.0

        distance = (
            (
                current_price
                / vwap
            )
            - 1.0
        ) * 100.0

        if distance >= -0.25:
            return 60.0

    # VWAP has lower importance for swing.
    if mode == Config.MODE_SWING:
        return 50.0

    return 0.0


# ============================================================
# BREAKOUT
# ============================================================


def _breakout_score(
    metrics: dict[str, Any],
) -> float:

    if _metric_bool(
        metrics,
        "breakout",
        "breakout_confirmed",
        "bullish_breakout",
    ):
        return 100.0

    breakout_score = safe_float(
        metrics.get(
            "breakout_score"
        )
    )

    if breakout_score is not None:

        return _clamp(
            breakout_score
        )

    resistance = safe_float(
        metrics.get(
            "resistance"
        )
    )

    current_price = safe_float(
        metrics.get(
            "current_price"
        )
    )

    if (
        resistance is not None
        and current_price is not None
        and resistance > 0
        and current_price > resistance
    ):
        return 100.0

    return 0.0


# ============================================================
# MULTI TIMEFRAME
# ============================================================


def _multi_timeframe_score(
    metrics: dict[str, Any],
) -> float:

    confirmation = _metric_bool(
        metrics,
        "confirmation_bullish",
        "confirmation_confirmed",
    )

    higher = _metric_bool(
        metrics,
        "higher_timeframe_bullish",
        "higher_timeframe_confirmed",
    )

    final_confirmation = _metric_bool(
        metrics,
        "multi_timeframe_confirmed",
    )

    score = 0.0

    if confirmation:
        score += 30.0

    if higher:
        score += 30.0

    if final_confirmation:
        score += 40.0

    return _clamp(
        score
    )


# ============================================================
# MODE WEIGHTS
# ============================================================


def _get_weights(
    mode: str,
) -> dict[str, float]:
    """
    All weights total 1.00.
    """

    # --------------------------------------------------------
    # INTRADAY
    # Momentum / VWAP / volume / MACD get priority.
    # --------------------------------------------------------

    if (
        mode
        == Config.MODE_INTRADAY
    ):

        return {
            "momentum": 0.16,
            "trend": 0.14,
            "volume": 0.12,
            "rsi": 0.08,
            "relative_strength": 0.07,
            "macd": 0.10,
            "supertrend": 0.09,
            "vwap": 0.10,
            "breakout": 0.08,
            "multi_timeframe": 0.06,
        }

    # --------------------------------------------------------
    # BTST
    # Closing momentum + trend + breakout +
    # multi-timeframe confirmation.
    # --------------------------------------------------------

    if mode == BTST_MODE:

        return {
            "momentum": 0.16,
            "trend": 0.16,
            "volume": 0.11,
            "rsi": 0.08,
            "relative_strength": 0.09,
            "macd": 0.09,
            "supertrend": 0.09,
            "vwap": 0.05,
            "breakout": 0.09,
            "multi_timeframe": 0.08,
        }

    # --------------------------------------------------------
    # SWING
    # Trend + relative strength +
    # breakout + higher timeframe.
    # --------------------------------------------------------

    return {
        "momentum": 0.11,
        "trend": 0.19,
        "volume": 0.09,
        "rsi": 0.08,
        "relative_strength": 0.12,
        "macd": 0.09,
        "supertrend": 0.10,
        "vwap": 0.03,
        "breakout": 0.09,
        "multi_timeframe": 0.10,
    }


# ============================================================
# ONE STOCK SCORE
# ============================================================


def calculate_stock_score(
    stock: NSEStock,
    metrics: dict[str, Any],
    strong_buy_symbols: set[str] | None = None,
    mode: str | None = None,
) -> RankedStock:
    """
    Calculate ranking score.

    This function NEVER creates a STRONG BUY
    simply because score is high.

    STRONG BUY must come from the final
    technical scanner.
    """

    if not isinstance(
        metrics,
        dict,
    ):
        metrics = {}

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    normalized_symbol = (
        normalize_symbol(
            stock.symbol
        )
    )

    strong_buy_set = (
        _normalize_strong_buy_symbols(
            strong_buy_symbols
        )
    )

    momentum = _momentum_score(
        metrics,
        mode=normalized_mode,
    )

    trend = _trend_score(
        metrics,
        mode=normalized_mode,
    )

    volume = _volume_score(
        metrics
    )

    rsi = _rsi_score(
        metrics,
        mode=normalized_mode,
    )

    relative_strength = (
        _relative_strength_score(
            metrics
        )
    )

    macd = _macd_score(
        metrics
    )

    supertrend = (
        _supertrend_score(
            metrics
        )
    )

    vwap = _vwap_score(
        metrics,
        mode=normalized_mode,
    )

    breakout = _breakout_score(
        metrics
    )

    multi_timeframe = (
        _multi_timeframe_score(
            metrics
        )
    )

    weights = _get_weights(
        normalized_mode
    )

    final_score = (
        momentum
        * weights["momentum"]

        + trend
        * weights["trend"]

        + volume
        * weights["volume"]

        + rsi
        * weights["rsi"]

        + relative_strength
        * weights[
            "relative_strength"
        ]

        + macd
        * weights["macd"]

        + supertrend
        * weights["supertrend"]

        + vwap
        * weights["vwap"]

        + breakout
        * weights["breakout"]

        + multi_timeframe
        * weights[
            "multi_timeframe"
        ]
    )

    is_strong_buy = bool(
        normalized_symbol
        and normalized_symbol
        in strong_buy_set
    )

    company_name = str(
        stock.company_name
        or normalized_symbol
        or stock.symbol
    ).strip()

    sector = str(
        stock.sector
        or ""
    ).strip()

    return RankedStock(
        symbol=(
            normalized_symbol
            or str(
                stock.symbol
            ).strip().upper()
        ),

        company_name=(
            company_name
        ),

        sector=(
            sector
        ),

        mode=(
            normalized_mode
        ),

        score=_clamp(
            final_score
        ),

        momentum_score=(
            momentum
        ),

        trend_score=(
            trend
        ),

        volume_score=(
            volume
        ),

        rsi_score=(
            rsi
        ),

        relative_strength_score=(
            relative_strength
        ),

        macd_score=(
            macd
        ),

        supertrend_score=(
            supertrend
        ),

        vwap_score=(
            vwap
        ),

        breakout_score=(
            breakout
        ),

        multi_timeframe_score=(
            multi_timeframe
        ),

        strong_buy=(
            is_strong_buy
        ),
    )


# ============================================================
# RANK ONE SECTOR
# ============================================================


def rank_sector_stocks(
    sector: str,
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[
        str,
        dict[str, Any],
    ],
    strong_buy_symbols: set[str] | None = None,
    mode: str | None = None,
) -> list[RankedStock]:

    target_sector = str(
        sector
        or ""
    ).strip()

    if not target_sector:
        return []

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    strong_buy_set = (
        _normalize_strong_buy_symbols(
            strong_buy_symbols
        )
    )

    ranked: list[
        RankedStock
    ] = []

    for stock in stocks:

        stock_sector = str(
            stock.sector
            or ""
        ).strip()

        if (
            stock_sector.casefold()
            != target_sector.casefold()
        ):
            continue

        symbol = normalize_symbol(
            stock.symbol
        )

        if not symbol:
            continue

        metrics = (
            metrics_by_symbol.get(
                symbol
            )
        )

        # Backward compatibility:
        # raw symbol may have been used as key.
        if not isinstance(
            metrics,
            dict,
        ):

            metrics = (
                metrics_by_symbol.get(
                    stock.symbol
                )
            )

        if not isinstance(
            metrics,
            dict,
        ):
            continue

        ranked_stock = (
            calculate_stock_score(
                stock=stock,
                metrics=metrics,
                strong_buy_symbols=(
                    strong_buy_set
                ),
                mode=(
                    normalized_mode
                ),
            )
        )

        ranked.append(
            ranked_stock
        )

    # ========================================================
    # SORTING
    #
    # 1. Overall ranking
    # 2. Multi timeframe
    # 3. Trend
    # 4. Momentum
    # 5. Relative strength
    # 6. Volume
    # 7. Breakout
    # ========================================================

    ranked.sort(
        key=lambda item: (
            -float(
                item.score
            ),

            -float(
                item.multi_timeframe_score
            ),

            -float(
                item.trend_score
            ),

            -float(
                item.momentum_score
            ),

            -float(
                item.relative_strength_score
            ),

            -float(
                item.volume_score
            ),

            -float(
                item.breakout_score
            ),

            item.symbol,
        )
    )

    return ranked


# ============================================================
# TOP STOCKS FOR ONE SECTOR
# ============================================================


def get_top_stocks_for_sector(
    sector: str,
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[
        str,
        dict[str, Any],
    ],
    limit: int | None = None,
    strong_buy_symbols: set[str] | None = None,
    mode: str | None = None,
) -> list[RankedStock]:

    if limit is None:

        limit = (
            Config
            .TOP_STOCKS_PER_SECTOR
        )

    try:

        safe_limit = int(
            limit
        )

    except (
        TypeError,
        ValueError,
    ):

        safe_limit = (
            Config
            .TOP_STOCKS_PER_SECTOR
        )

    safe_limit = max(
        1,
        min(
            safe_limit,
            Config
            .TOP_STOCKS_PER_SECTOR,
        ),
    )

    ranked = rank_sector_stocks(
        sector=sector,
        stocks=stocks,
        metrics_by_symbol=(
            metrics_by_symbol
        ),
        strong_buy_symbols=(
            strong_buy_symbols
        ),
        mode=mode,
    )

    return ranked[
        :safe_limit
    ]


# ============================================================
# DICTIONARY VERSION
# ============================================================


def get_top_stocks_for_sector_as_dicts(
    sector: str,
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[
        str,
        dict[str, Any],
    ],
    limit: int | None = None,
    strong_buy_symbols: set[str] | None = None,
    mode: str | None = None,
) -> list[dict[str, Any]]:

    ranked = (
        get_top_stocks_for_sector(
            sector=sector,
            stocks=stocks,
            metrics_by_symbol=(
                metrics_by_symbol
            ),
            limit=limit,
            strong_buy_symbols=(
                strong_buy_symbols
            ),
            mode=mode,
        )
    )

    return [
        item.to_dict()
        for item
        in ranked
    ]


# ============================================================
# BUILD TOP-SECTOR UNIVERSE
# ============================================================


def build_top_sector_stock_universe(
    top_sectors: Iterable[str],
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[
        str,
        dict[str, Any],
    ],
    strong_buy_symbols: set[str] | None = None,
    mode: str | None = None,
) -> list[RankedStock]:
    """
    Build:

        Top 10 sectors
             ×
        Top 10 stocks

    Maximum candidate universe = 100.

    Duplicate symbols are removed.

    IMPORTANT:

    Candidate universe contains RANKED stocks.

    Final STRONG BUY status remains independent.
    """

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    stock_list = list(
        stocks
    )

    strong_buy_set = (
        _normalize_strong_buy_symbols(
            strong_buy_symbols
        )
    )

    output: list[
        RankedStock
    ] = []

    seen_symbols: set[
        str
    ] = set()

    seen_sectors: set[
        str
    ] = set()

    sector_count = 0

    for sector in top_sectors:

        clean_sector = str(
            sector
            or ""
        ).strip()

        if not clean_sector:
            continue

        sector_key = (
            clean_sector.casefold()
        )

        if sector_key in seen_sectors:
            continue

        seen_sectors.add(
            sector_key
        )

        if (
            sector_count
            >= Config.TOP_SECTORS_COUNT
        ):
            break

        top_stocks = (
            get_top_stocks_for_sector(
                sector=(
                    clean_sector
                ),
                stocks=(
                    stock_list
                ),
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
                limit=(
                    Config
                    .TOP_STOCKS_PER_SECTOR
                ),
                strong_buy_symbols=(
                    strong_buy_set
                ),
                mode=(
                    normalized_mode
                ),
            )
        )

        sector_count += 1

        for stock in top_stocks:

            symbol = normalize_symbol(
                stock.symbol
            )

            if not symbol:
                continue

            if symbol in seen_symbols:
                continue

            seen_symbols.add(
                symbol
            )

            output.append(
                stock
            )

            if (
                len(
                    output
                )
                >= Config
                .MAX_SCANNER_UNIVERSE
            ):

                return output

    return output


# ============================================================
# GROUP TOP STOCKS BY SECTOR
# ============================================================


def build_top_stocks_by_sector(
    top_sectors: Iterable[str],
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[
        str,
        dict[str, Any],
    ],
    strong_buy_symbols: set[str] | None = None,
    mode: str | None = None,
) -> dict[
    str,
    list[
        dict[str, Any]
    ],
]:
    """
    Frontend structure:

    {
        "Information Technology": [
            {...},
            {...}
        ],

        "Banking": [
            {...},
            {...}
        ]
    }

    Every sector receives its own Top-10 stocks.
    """

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    stock_list = list(
        stocks
    )

    strong_buy_set = (
        _normalize_strong_buy_symbols(
            strong_buy_symbols
        )
    )

    result: dict[
        str,
        list[
            dict[str, Any]
        ],
    ] = {}

    seen_sectors: set[
        str
    ] = set()

    sector_count = 0

    for sector in top_sectors:

        clean_sector = str(
            sector
            or ""
        ).strip()

        if not clean_sector:
            continue

        sector_key = (
            clean_sector.casefold()
        )

        if sector_key in seen_sectors:
            continue

        seen_sectors.add(
            sector_key
        )

        if (
            sector_count
            >= Config.TOP_SECTORS_COUNT
        ):
            break

        ranked_stocks = (
            get_top_stocks_for_sector(
                sector=(
                    clean_sector
                ),
                stocks=(
                    stock_list
                ),
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
                limit=(
                    Config
                    .TOP_STOCKS_PER_SECTOR
                ),
                strong_buy_symbols=(
                    strong_buy_set
                ),
                mode=(
                    normalized_mode
                ),
            )
        )

        result[
            clean_sector
        ] = [
            item.to_dict()
            for item
            in ranked_stocks
        ]

        sector_count += 1

    return result


# ============================================================
# STRONG BUY CANDIDATES
# ============================================================


def get_strong_buy_ranked_stocks(
    ranked_stocks: Iterable[
        RankedStock
    ],
) -> list[RankedStock]:
    """
    Return only stocks that have already
    been confirmed as STRONG BUY by the
    final technical scanner.

    This function does NOT generate signals.
    """

    output = [
        stock
        for stock
        in ranked_stocks
        if stock.strong_buy
    ]

    output.sort(
        key=lambda item: (
            -float(
                item.score
            ),
            -float(
                item.multi_timeframe_score
            ),
            -float(
                item.trend_score
            ),
            item.symbol,
        )
    )

    return output
