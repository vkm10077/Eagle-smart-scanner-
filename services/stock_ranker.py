from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

from config import Config
from data.nse_universe import NSEStock
from utils.helpers import normalize_symbol


logger = logging.getLogger(
    "services.stock_ranker"
)


# ============================================================
# RESULT MODEL
# ============================================================

@dataclass(frozen=True)
class RankedStock:
    """
    Technical ranking result for one stock
    inside its NSE sector.

    strong_buy:
        True only when the stock is later confirmed
        by the final Eagle technical scanner.

    signal:
        Convenience value for frontend/UI.

        STRONG BUY
            Final technical scanner qualified.

        RANKED
            Stock is only a Top-10 sector candidate.
            It has NOT automatically qualified as STRONG BUY.
    """

    symbol: str
    company_name: str
    sector: str

    score: float

    momentum_score: float
    trend_score: float
    volume_score: float
    rsi_score: float
    relative_strength_score: float

    strong_buy: bool = False

    # --------------------------------------------------------
    # DICTIONARY
    # --------------------------------------------------------

    def to_dict(
        self,
    ) -> dict[str, Any]:

        is_strong_buy = bool(
            self.strong_buy
        )

        return {
            "symbol": str(
                self.symbol
            ),

            "company_name": str(
                self.company_name
            ),

            "sector": str(
                self.sector
            ),

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

            # Final scanner status
            "strong_buy": (
                is_strong_buy
            ),

            # Frontend-friendly field
            "signal": (
                "STRONG BUY"
                if is_strong_buy
                else "RANKED"
            ),
        }


# ============================================================
# SAFE NUMBER
# ============================================================

def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    """
    Convert values safely into normal Python floats.

    This protects ranking from:
    - None
    - strings
    - numpy numeric types
    - malformed values
    """

    try:

        number = float(
            value
        )

        return number

    except (
        TypeError,
        ValueError,
    ):

        return float(
            default
        )


# ============================================================
# CLAMP SCORE
# ============================================================

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


# ============================================================
# MOMENTUM SCORE
# ============================================================

def _momentum_score(
    metrics: dict[str, Any],
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

    score = (
        50.0
        + (
            change_1d
            * 5.0
        )
        + (
            change_5d
            * 2.0
        )
        + change_20d
    )

    return _clamp(
        score
    )


# ============================================================
# TREND SCORE
# ============================================================

def _trend_score(
    metrics: dict[str, Any],
) -> float:

    score = 0.0

    if bool(
        metrics.get(
            "above_ema20",
            False,
        )
    ):
        score += 30.0

    if bool(
        metrics.get(
            "above_ema50",
            False,
        )
    ):
        score += 30.0

    if bool(
        metrics.get(
            "above_ema200",
            False,
        )
    ):
        score += 25.0

    if bool(
        metrics.get(
            "bullish",
            False,
        )
    ):
        score += 15.0

    return _clamp(
        score
    )


# ============================================================
# VOLUME SCORE
# ============================================================

def _volume_score(
    metrics: dict[str, Any],
) -> float:

    ratio = _safe_float(
        metrics.get(
            "volume_ratio"
        )
    )

    # 1x volume  = 50
    # 1.5x       = 75
    # 2x+        = 100
    return _clamp(
        ratio
        * 50.0
    )


# ============================================================
# RSI SCORE
# ============================================================

def _rsi_score(
    metrics: dict[str, Any],
) -> float:

    rsi = _safe_float(
        metrics.get(
            "rsi"
        )
    )

    if rsi <= 0:
        return 0.0

    # Best bullish momentum area.
    if (
        55.0
        <= rsi
        <= 70.0
    ):
        return 100.0

    if (
        50.0
        <= rsi
        < 55.0
    ):
        return 75.0

    if (
        70.0
        < rsi
        <= 75.0
    ):
        return 70.0

    if (
        45.0
        <= rsi
        < 50.0
    ):
        return 50.0

    if (
        75.0
        < rsi
        <= 80.0
    ):
        return 40.0

    return 20.0


# ============================================================
# RELATIVE STRENGTH SCORE
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

    score = (
        50.0
        + (
            relative_strength
            * 5.0
        )
    )

    return _clamp(
        score
    )


# ============================================================
# NORMALIZE STRONG-BUY SYMBOLS
# ============================================================

def _normalize_strong_buy_symbols(
    symbols: (
        Iterable[str]
        | None
    ),
) -> set[str]:
    """
    Convert any incoming STRONG BUY symbol collection
    into a safe normalized Python set.

    Examples:

        HDFCBANK
        NSE:HDFCBANK-EQ

    normalize_symbol() handles the common format.
    """

    if symbols is None:
        return set()

    output: set[str] = set()

    for symbol in symbols:

        normalized = normalize_symbol(
            symbol
        )

        if normalized:

            output.add(
                normalized
            )

    return output


# ============================================================
# CALCULATE ONE STOCK SCORE
# ============================================================

def calculate_stock_score(
    stock: NSEStock,
    metrics: dict[str, Any],
    strong_buy_symbols: (
        set[str]
        | None
    ) = None,
) -> RankedStock:
    """
    Calculate technical ranking score for one stock.

    IMPORTANT:

    This ranking score DOES NOT itself produce
    the final STRONG BUY signal.

    STRONG BUY comes from:
        scanners/technical_scanner.py

    strong_buy_symbols is therefore optional and is
    supplied later after final technical confirmation.
    """

    if not isinstance(
        metrics,
        dict,
    ):

        metrics = {}

    normalized_symbol = (
        normalize_symbol(
            stock.symbol
        )
    )

    normalized_strong_buy_symbols = (
        _normalize_strong_buy_symbols(
            strong_buy_symbols
        )
    )

    momentum = (
        _momentum_score(
            metrics
        )
    )

    trend = (
        _trend_score(
            metrics
        )
    )

    volume = (
        _volume_score(
            metrics
        )
    )

    rsi = (
        _rsi_score(
            metrics
        )
    )

    relative_strength = (
        _relative_strength_score(
            metrics
        )
    )

    # --------------------------------------------------------
    # FINAL STOCK-RANKING SCORE
    #
    # Total weight = 100%
    #
    # Momentum          25%
    # Trend             30%
    # Volume            15%
    # RSI               15%
    # Relative Strength 15%
    # --------------------------------------------------------

    final_score = (
        (
            momentum
            * 0.25
        )
        + (
            trend
            * 0.30
        )
        + (
            volume
            * 0.15
        )
        + (
            rsi
            * 0.15
        )
        + (
            relative_strength
            * 0.15
        )
    )

    is_strong_buy = bool(
        normalized_symbol
        and normalized_symbol
        in normalized_strong_buy_symbols
    )

    return RankedStock(
        symbol=(
            normalized_symbol
            or str(
                stock.symbol
            ).strip().upper()
        ),

        company_name=(
            str(
                stock.company_name
                or normalized_symbol
                or stock.symbol
            )
            .strip()
        ),

        sector=(
            str(
                stock.sector
                or ""
            )
            .strip()
        ),

        score=(
            _clamp(
                final_score
            )
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

        strong_buy=(
            is_strong_buy
        ),
    )


# ============================================================
# RANK STOCKS INSIDE ONE SECTOR
# ============================================================

def rank_sector_stocks(
    sector: str,
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[
        str,
        dict[str, Any],
    ],
    strong_buy_symbols: (
        set[str]
        | None
    ) = None,
) -> list[RankedStock]:
    """
    Rank all technically available stocks
    belonging to one selected NSE sector.

    This produces the list from which
    Top 10 stocks are selected.
    """

    target_sector = (
        str(
            sector
            or ""
        )
        .strip()
    )

    if not target_sector:
        return []

    normalized_strong_buy_symbols = (
        _normalize_strong_buy_symbols(
            strong_buy_symbols
        )
    )

    ranked: list[
        RankedStock
    ] = []

    for stock in stocks:

        stock_sector = (
            str(
                stock.sector
                or ""
            )
            .strip()
        )

        if (
            stock_sector.casefold()
            != target_sector.casefold()
        ):
            continue

        symbol = (
            normalize_symbol(
                stock.symbol
            )
        )

        if not symbol:
            continue

        metrics = (
            metrics_by_symbol.get(
                symbol
            )
        )

        # Extra compatibility:
        # In case caller stored raw stock.symbol
        # instead of normalized symbol.
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

                metrics=(
                    metrics
                ),

                strong_buy_symbols=(
                    normalized_strong_buy_symbols
                ),
            )
        )

        ranked.append(
            ranked_stock
        )

    # --------------------------------------------------------
    # Strong ranking order
    #
    # 1. Overall score
    # 2. Trend
    # 3. Momentum
    # 4. Volume
    # 5. RSI
    # 6. Relative strength
    # --------------------------------------------------------

    ranked.sort(
        key=lambda item: (
            -float(
                item.score
            ),

            -float(
                item.trend_score
            ),

            -float(
                item.momentum_score
            ),

            -float(
                item.volume_score
            ),

            -float(
                item.rsi_score
            ),

            -float(
                item.relative_strength_score
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
    strong_buy_symbols: (
        set[str]
        | None
    ) = None,
) -> list[RankedStock]:
    """
    Return Top N technically ranked stocks
    from one selected sector.

    Default:
        Config.TOP_STOCKS_PER_SECTOR = 10

    IMPORTANT:
        These Top 10 stocks are ranking candidates.

        They do NOT need to pass STRONG BUY rules
        just to appear in the sector Top-10 list.

        If a candidate later passes final technical
        scanner rules, strong_buy=True will identify it.
    """

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

    ranked = (
        rank_sector_stocks(
            sector=(
                sector
            ),

            stocks=(
                stocks
            ),

            metrics_by_symbol=(
                metrics_by_symbol
            ),

            strong_buy_symbols=(
                strong_buy_symbols
            ),
        )
    )

    return ranked[
        :safe_limit
    ]


# ============================================================
# TOP STOCKS AS DICTIONARIES
# ============================================================

def get_top_stocks_for_sector_as_dicts(
    sector: str,
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[
        str,
        dict[str, Any],
    ],
    limit: int | None = None,
    strong_buy_symbols: (
        set[str]
        | None
    ) = None,
) -> list[dict[str, Any]]:
    """
    Frontend/API-ready version of sector Top-10 stocks.
    """

    ranked = (
        get_top_stocks_for_sector(
            sector=(
                sector
            ),

            stocks=(
                stocks
            ),

            metrics_by_symbol=(
                metrics_by_symbol
            ),

            limit=(
                limit
            ),

            strong_buy_symbols=(
                strong_buy_symbols
            ),
        )
    )

    return [
        item.to_dict()
        for item
        in ranked
    ]


# ============================================================
# BUILD ALL TOP-SECTOR STOCKS
# ============================================================

def build_top_sector_stock_universe(
    top_sectors: Iterable[str],
    stocks: Iterable[NSEStock],
    metrics_by_symbol: dict[
        str,
        dict[str, Any],
    ],
    strong_buy_symbols: (
        set[str]
        | None
    ) = None,
) -> list[RankedStock]:
    """
    Build candidate universe:

        Top 10 Sectors
              ×
        Top 10 Stocks Per Sector

    Maximum:
        100 stocks

    Each sector still has its own Top-10 ranking.

    If the same stock appears in more than one
    related sector index, it is included only once
    in the final candidate universe.
    """

    stock_list = list(
        stocks
    )

    normalized_strong_buy_symbols = (
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

    sector_count = 0

    for sector in top_sectors:

        clean_sector = (
            str(
                sector
                or ""
            )
            .strip()
        )

        if not clean_sector:
            continue

        # Do not accept more sectors than
        # Config.TOP_SECTORS_COUNT.
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
                    normalized_strong_buy_symbols
                ),
            )
        )

        sector_count += 1

        for stock in top_stocks:

            symbol = (
                normalize_symbol(
                    stock.symbol
                )
            )

            if not symbol:
                continue

            if symbol in (
                seen_symbols
            ):
                continue

            seen_symbols.add(
                symbol
            )

            output.append(
                stock
            )

            # Hard safety:
            # candidate universe never exceeds
            # Config.MAX_SCANNER_UNIVERSE.
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
    strong_buy_symbols: (
        set[str]
        | None
    ) = None,
) -> dict[
    str,
    list[
        dict[str, Any]
    ],
]:
    """
    FRONTEND FEATURE.

    Builds:

        {
            "Information Technology": [
                {...},
                {...}
            ],

            "Metals & Mining": [
                {...}
            ]
        }

    This is the structure required when the user taps
    a Top-10 sector card on the dashboard.

    The sector card can then immediately display that
    sector's Top 10 stocks.

    IMPORTANT:
    All Top-10 ranked stocks are returned.

    STRONG BUY stocks are separately marked with:
        strong_buy = True
        signal = "STRONG BUY"
    """

    stock_list = list(
        stocks
    )

    normalized_strong_buy_symbols = (
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

    sector_count = 0

    for sector in top_sectors:

        clean_sector = (
            str(
                sector
                or ""
            )
            .strip()
        )

        if not clean_sector:
            continue

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
                    normalized_strong_buy_symbols
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
