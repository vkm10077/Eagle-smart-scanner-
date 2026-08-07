from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd

from config import Config
from scanners.pattern_scanner import (
    PatternScannerError,
    get_pattern_scanner,
)


# ============================================================
# RESULT MODEL
# ============================================================

@dataclass
class TechnicalResult:
    symbol: str
    sector: str
    mode: str

    current_price: float
    entry_price: float
    stop_loss: float
    target_price: float

    risk_reward: float

    technical_score: float
    confirmations: int

    ema_bullish: bool
    rsi: float

    macd_bullish: bool
    supertrend_bullish: bool

    above_vwap: bool

    volume_ratio: float
    volume_confirmed: bool

    breakout: bool
    breakout_price: float | None

    price_action_bullish: bool

    relative_strength_pct: float
    relative_strength_bullish: bool

    chart_pattern: str | None
    chart_pattern_score: float
    chart_pattern_confirmed: bool

    candlestick_pattern: str | None
    candlestick_confirmed: bool

    signal: str

    reasons: list[str] = field(
        default_factory=list
    )

    rejected_reasons: list[str] = field(
        default_factory=list
    )

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "symbol": str(
                self.symbol
            ),

            "sector": str(
                self.sector
            ),

            "mode": str(
                self.mode
            ),

            "current_price": round(
                float(
                    self.current_price
                ),
                2,
            ),

            "entry_price": round(
                float(
                    self.entry_price
                ),
                2,
            ),

            "stop_loss": round(
                float(
                    self.stop_loss
                ),
                2,
            ),

            "target_price": round(
                float(
                    self.target_price
                ),
                2,
            ),

            "risk_reward": round(
                float(
                    self.risk_reward
                ),
                2,
            ),

            "technical_score": round(
                float(
                    self.technical_score
                ),
                2,
            ),

            "confirmations": int(
                self.confirmations
            ),

            "ema_bullish": bool(
                self.ema_bullish
            ),

            "rsi": round(
                float(
                    self.rsi
                ),
                2,
            ),

            "macd_bullish": bool(
                self.macd_bullish
            ),

            "supertrend_bullish": bool(
                self.supertrend_bullish
            ),

            "above_vwap": bool(
                self.above_vwap
            ),

            "volume_ratio": round(
                float(
                    self.volume_ratio
                ),
                2,
            ),

            "volume_confirmed": bool(
                self.volume_confirmed
            ),

            "breakout": bool(
                self.breakout
            ),

            "breakout_price": (
                round(
                    float(
                        self.breakout_price
                    ),
                    2,
                )
                if self.breakout_price
                is not None
                else None
            ),

            "price_action_bullish": bool(
                self.price_action_bullish
            ),

            "relative_strength_pct": round(
                float(
                    self.relative_strength_pct
                ),
                2,
            ),

            "relative_strength_bullish": bool(
                self.relative_strength_bullish
            ),

            "chart_pattern": (
                str(
                    self.chart_pattern
                )
                if self.chart_pattern
                is not None
                else None
            ),

            "chart_pattern_score": round(
                float(
                    self.chart_pattern_score
                ),
                2,
            ),

            "chart_pattern_confirmed": bool(
                self.chart_pattern_confirmed
            ),

            "candlestick_pattern": (
                str(
                    self.candlestick_pattern
                )
                if self.candlestick_pattern
                is not None
                else None
            ),

            "candlestick_confirmed": bool(
                self.candlestick_confirmed
            ),

            "signal": str(
                self.signal
            ),

            "reasons": [
                str(
                    reason
                )
                for reason
                in self.reasons
            ],

            "rejected_reasons": [
                str(
                    reason
                )
                for reason
                in self.rejected_reasons
            ],
        }


# ============================================================
# BASIC HELPERS
# ============================================================

def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:

    try:

        result = float(
            value
        )

        if (
            math.isnan(
                result
            )
            or math.isinf(
                result
            )
        ):
            return float(
                default
            )

        return result

    except (
        TypeError,
        ValueError,
    ):

        return float(
            default
        )


def _safe_bool(
    value: Any,
) -> bool:
    """
    Converts Python bool, numpy.bool_,
    pandas boolean and numeric comparisons
    into a normal JSON-safe Python bool.
    """

    try:
        return bool(
            value
        )

    except Exception:
        return False


def _prepare_dataframe(
    candles: (
        pd.DataFrame
        | Iterable[
            dict[str, Any]
        ]
    ),
) -> pd.DataFrame:

    if isinstance(
        candles,
        pd.DataFrame,
    ):

        dataframe = (
            candles.copy()
        )

    else:

        dataframe = (
            pd.DataFrame(
                list(
                    candles
                )
            )
        )

    required_columns = {
        "open",
        "high",
        "low",
        "close",
        "volume",
    }

    missing_columns = (
        required_columns
        - set(
            dataframe.columns
        )
    )

    if missing_columns:

        raise ValueError(
            (
                "Missing candle columns: "
                + ", ".join(
                    sorted(
                        missing_columns
                    )
                )
            )
        )

    for column in (
        required_columns
    ):

        dataframe[
            column
        ] = pd.to_numeric(
            dataframe[
                column
            ],
            errors="coerce",
        )

    dataframe = (
        dataframe.dropna(
            subset=[
                "open",
                "high",
                "low",
                "close",
            ]
        )
    )

    dataframe[
        "volume"
    ] = (
        dataframe[
            "volume"
        ]
        .fillna(
            0.0
        )
    )

    if (
        "timestamp"
        not in dataframe.columns
    ):

        dataframe[
            "timestamp"
        ] = np.arange(
            len(
                dataframe
            )
        )

    dataframe = (
        dataframe
        .drop_duplicates(
            subset=[
                "timestamp"
            ],
            keep="last",
        )
        .sort_values(
            "timestamp"
        )
        .reset_index(
            drop=True
        )
    )

    return dataframe


# ============================================================
# EMA
# ============================================================

def _ema(
    series: pd.Series,
    period: int,
) -> pd.Series:

    return series.ewm(
        span=period,
        adjust=False,
    ).mean()


# ============================================================
# RSI
# ============================================================

def _rsi(
    series: pd.Series,
    period: int,
) -> pd.Series:

    delta = (
        series.diff()
    )

    gain = (
        delta.clip(
            lower=0
        )
    )

    loss = (
        -delta.clip(
            upper=0
        )
    )

    average_gain = (
        gain.ewm(
            alpha=(
                1 / period
            ),
            adjust=False,
        )
        .mean()
    )

    average_loss = (
        loss.ewm(
            alpha=(
                1 / period
            ),
            adjust=False,
        )
        .mean()
    )

    rs = (
        average_gain
        / average_loss.replace(
            0,
            np.nan,
        )
    )

    result = (
        100
        - (
            100
            / (
                1
                + rs
            )
        )
    )

    return (
        result.fillna(
            50.0
        )
    )


# ============================================================
# MACD
# ============================================================

def _macd(
    series: pd.Series,
) -> tuple[
    pd.Series,
    pd.Series,
    pd.Series,
]:

    fast = _ema(
        series,
        Config.MACD_FAST,
    )

    slow = _ema(
        series,
        Config.MACD_SLOW,
    )

    macd_line = (
        fast
        - slow
    )

    signal_line = (
        _ema(
            macd_line,
            Config.MACD_SIGNAL,
        )
    )

    histogram = (
        macd_line
        - signal_line
    )

    return (
        macd_line,
        signal_line,
        histogram,
    )


# ============================================================
# ATR
# ============================================================

def _atr(
    dataframe: pd.DataFrame,
    period: int,
) -> pd.Series:

    previous_close = (
        dataframe[
            "close"
        ]
        .shift(
            1
        )
    )

    true_range = (
        pd.concat(
            [
                (
                    dataframe[
                        "high"
                    ]
                    - dataframe[
                        "low"
                    ]
                ),

                (
                    dataframe[
                        "high"
                    ]
                    - previous_close
                ).abs(),

                (
                    dataframe[
                        "low"
                    ]
                    - previous_close
                ).abs(),
            ],
            axis=1,
        )
        .max(
            axis=1
        )
    )

    return (
        true_range.ewm(
            alpha=(
                1 / period
            ),
            adjust=False,
        )
        .mean()
    )


# ============================================================
# VWAP
# ============================================================

def _vwap(
    dataframe: pd.DataFrame,
) -> pd.Series:

    typical_price = (
        dataframe[
            "high"
        ]
        + dataframe[
            "low"
        ]
        + dataframe[
            "close"
        ]
    ) / 3.0

    volume = (
        dataframe[
            "volume"
        ]
        .replace(
            0,
            np.nan,
        )
    )

    cumulative_volume = (
        volume.cumsum()
    )

    cumulative_price_volume = (
        (
            typical_price
            * volume
        )
        .cumsum()
    )

    result = (
        cumulative_price_volume
        / cumulative_volume
    )

    return (
        result.ffill()
    )


# ============================================================
# SUPERTREND
# ============================================================

def _supertrend(
    dataframe: pd.DataFrame,
) -> tuple[
    pd.Series,
    pd.Series,
]:

    atr_series = _atr(
        dataframe,
        Config.SUPERTREND_PERIOD,
    )

    hl2 = (
        dataframe[
            "high"
        ]
        + dataframe[
            "low"
        ]
    ) / 2.0

    upper_band = (
        hl2
        + (
            Config.SUPERTREND_MULTIPLIER
            * atr_series
        )
    )

    lower_band = (
        hl2
        - (
            Config.SUPERTREND_MULTIPLIER
            * atr_series
        )
    )

    final_upper = (
        upper_band.copy()
    )

    final_lower = (
        lower_band.copy()
    )

    close = (
        dataframe[
            "close"
        ]
    )

    for index in range(
        1,
        len(
            dataframe
        ),
    ):

        if (
            upper_band.iloc[
                index
            ]
            < final_upper.iloc[
                index - 1
            ]
            or close.iloc[
                index - 1
            ]
            > final_upper.iloc[
                index - 1
            ]
        ):

            final_upper.iloc[
                index
            ] = upper_band.iloc[
                index
            ]

        else:

            final_upper.iloc[
                index
            ] = final_upper.iloc[
                index - 1
            ]

        if (
            lower_band.iloc[
                index
            ]
            > final_lower.iloc[
                index - 1
            ]
            or close.iloc[
                index - 1
            ]
            < final_lower.iloc[
                index - 1
            ]
        ):

            final_lower.iloc[
                index
            ] = lower_band.iloc[
                index
            ]

        else:

            final_lower.iloc[
                index
            ] = final_lower.iloc[
                index - 1
            ]

    supertrend = (
        pd.Series(
            index=(
                dataframe.index
            ),
            dtype=float,
        )
    )

    direction = (
        pd.Series(
            index=(
                dataframe.index
            ),
            dtype=int,
        )
    )

    supertrend.iloc[
        0
    ] = (
        final_lower.iloc[
            0
        ]
    )

    direction.iloc[
        0
    ] = 1

    for index in range(
        1,
        len(
            dataframe
        ),
    ):

        previous_supertrend = (
            supertrend.iloc[
                index - 1
            ]
        )

        previous_upper = (
            final_upper.iloc[
                index - 1
            ]
        )

        previous_was_upper = (
            np.isclose(
                previous_supertrend,
                previous_upper,
                equal_nan=False,
            )
        )

        if (
            _safe_bool(
                previous_was_upper
            )
        ):

            if (
                float(
                    close.iloc[
                        index
                    ]
                )
                <= float(
                    final_upper.iloc[
                        index
                    ]
                )
            ):

                supertrend.iloc[
                    index
                ] = (
                    final_upper.iloc[
                        index
                    ]
                )

                direction.iloc[
                    index
                ] = -1

            else:

                supertrend.iloc[
                    index
                ] = (
                    final_lower.iloc[
                        index
                    ]
                )

                direction.iloc[
                    index
                ] = 1

        else:

            if (
                float(
                    close.iloc[
                        index
                    ]
                )
                >= float(
                    final_lower.iloc[
                        index
                    ]
                )
            ):

                supertrend.iloc[
                    index
                ] = (
                    final_lower.iloc[
                        index
                    ]
                )

                direction.iloc[
                    index
                ] = 1

            else:

                supertrend.iloc[
                    index
                ] = (
                    final_upper.iloc[
                        index
                    ]
                )

                direction.iloc[
                    index
                ] = -1

    return (
        supertrend,
        direction,
    )


# ============================================================
# CANDLESTICK PATTERNS
# ============================================================

def _detect_candlestick_pattern(
    dataframe: pd.DataFrame,
) -> tuple[
    str | None,
    bool,
]:

    if len(
        dataframe
    ) < 3:

        return (
            None,
            False,
        )

    first = (
        dataframe.iloc[
            -3
        ]
    )

    previous = (
        dataframe.iloc[
            -2
        ]
    )

    current = (
        dataframe.iloc[
            -1
        ]
    )

    open_price = _safe_float(
        current[
            "open"
        ]
    )

    high_price = _safe_float(
        current[
            "high"
        ]
    )

    low_price = _safe_float(
        current[
            "low"
        ]
    )

    close_price = _safe_float(
        current[
            "close"
        ]
    )

    previous_open = _safe_float(
        previous[
            "open"
        ]
    )

    previous_close = _safe_float(
        previous[
            "close"
        ]
    )

    previous_low = _safe_float(
        previous[
            "low"
        ]
    )

    first_open = _safe_float(
        first[
            "open"
        ]
    )

    first_close = _safe_float(
        first[
            "close"
        ]
    )

    body = abs(
        close_price
        - open_price
    )

    candle_range = max(
        high_price
        - low_price,
        0.0001,
    )

    upper_wick = (
        high_price
        - max(
            open_price,
            close_price,
        )
    )

    lower_wick = (
        min(
            open_price,
            close_price,
        )
        - low_price
    )

    bullish = (
        close_price
        > open_price
    )

    previous_bearish = (
        previous_close
        < previous_open
    )

    # --------------------------------------------------------
    # 1. Bullish Engulfing
    # --------------------------------------------------------

    if (
        bullish
        and previous_bearish
        and open_price
        <= previous_close
        and close_price
        >= previous_open
    ):

        return (
            "Bullish Engulfing",
            True,
        )

    # --------------------------------------------------------
    # 2. Hammer
    # --------------------------------------------------------

    if (
        bullish
        and lower_wick
        >= body * 2
        and upper_wick
        <= max(
            body,
            0.0001,
        )
    ):

        return (
            "Hammer",
            True,
        )

    # --------------------------------------------------------
    # 3. Morning Star
    # --------------------------------------------------------

    if (
        first_close
        < first_open
        and abs(
            previous_close
            - previous_open
        )
        < (
            abs(
                first_close
                - first_open
            )
            * 0.6
        )
        and bullish
        and close_price
        > (
            first_open
            + first_close
        ) / 2
    ):

        return (
            "Morning Star",
            True,
        )

    # --------------------------------------------------------
    # 4. Piercing Pattern
    # --------------------------------------------------------

    if (
        previous_bearish
        and bullish
        and open_price
        <= previous_close
        and close_price
        > (
            previous_open
            + previous_close
        ) / 2
        and close_price
        < previous_open
    ):

        return (
            "Piercing Pattern",
            True,
        )

    # --------------------------------------------------------
    # 5. Bullish Harami
    # --------------------------------------------------------

    if (
        previous_bearish
        and bullish
        and open_price
        > previous_close
        and close_price
        < previous_open
    ):

        return (
            "Bullish Harami",
            True,
        )

    # --------------------------------------------------------
    # 6. Bullish Marubozu
    # --------------------------------------------------------

    if (
        bullish
        and (
            body
            / candle_range
        )
        >= 0.80
    ):

        return (
            "Bullish Marubozu",
            True,
        )

    # --------------------------------------------------------
    # 7. Inverted Hammer
    # --------------------------------------------------------

    if (
        bullish
        and upper_wick
        >= body * 2
        and lower_wick
        <= max(
            body,
            0.0001,
        )
    ):

        return (
            "Inverted Hammer",
            True,
        )

    # --------------------------------------------------------
    # 8. Three White Soldiers
    # --------------------------------------------------------

    if (
        first_close
        > first_open
        and previous_close
        > previous_open
        and close_price
        > open_price
        and previous_close
        > first_close
        and close_price
        > previous_close
    ):

        return (
            "Three White Soldiers",
            True,
        )

    # --------------------------------------------------------
    # 9. Tweezer Bottom
    # --------------------------------------------------------

    if (
        previous_bearish
        and bullish
        and (
            abs(
                low_price
                - previous_low
            )
            / max(
                low_price,
                0.0001,
            )
        )
        <= 0.003
    ):

        return (
            "Tweezer Bottom",
            True,
        )

    # --------------------------------------------------------
    # 10. Doji Bullish Confirmation
    # --------------------------------------------------------

    if (
        (
            body
            / candle_range
        )
        <= 0.10
        and close_price
        >= (
            high_price
            + low_price
        ) / 2
    ):

        return (
            "Doji Bullish Confirmation",
            True,
        )

    return (
        None,
        False,
    )


# ============================================================
# CHART PATTERN SCANNER
# ============================================================

def _run_chart_pattern_scanner(
    symbol: str,
    dataframe: pd.DataFrame,
    mode: str,
) -> dict[str, Any]:

    scanner = (
        get_pattern_scanner()
    )

    candle_records = (
        dataframe[
            [
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        ]
        .to_dict(
            orient="records"
        )
    )

    # Existing pattern scanner currently uses
    # 15_30_days profile.
    pattern_timeframe = (
        "15_30_days"
    )

    try:

        result = scanner.scan(
            symbol=symbol,
            candles=(
                candle_records
            ),
            timeframe=(
                pattern_timeframe
            ),
        )

        if not isinstance(
            result,
            dict,
        ):

            return {
                "symbol": (
                    symbol
                ),
                "score": 0.0,
                "bullish_pattern": False,
                "strongest_pattern": None,
                "detected_count": 0,
                "confirmed_count": 0,
                "patterns": [],
            }

        return result

    except (
        PatternScannerError,
        Exception,
    ):

        return {
            "symbol": (
                symbol
            ),
            "score": 0.0,
            "bullish_pattern": False,
            "strongest_pattern": None,
            "detected_count": 0,
            "confirmed_count": 0,
            "patterns": [],
        }


# ============================================================
# MAIN ANALYSIS
# ============================================================

def analyze_stock(
    symbol: str,
    sector: str,
    candles: (
        pd.DataFrame
        | Iterable[
            dict[str, Any]
        ]
    ),
    mode: str,
    benchmark_change_pct: float = 0.0,
) -> TechnicalResult:

    normalized_symbol = str(
        symbol or ""
    ).strip().upper()

    normalized_sector = str(
        sector or ""
    ).strip()

    normalized_mode = (
        Config.normalize_trading_mode(
            mode
        )
    )

    if not normalized_symbol:

        raise ValueError(
            "Stock symbol is required."
        )

    if not normalized_sector:

        raise ValueError(
            (
                f"{normalized_symbol}: "
                "sector is required."
            )
        )

    dataframe = (
        _prepare_dataframe(
            candles
        )
    )

    minimum_candles = (
        Config.MIN_REQUIRED_CANDLES_INTRADAY
        if normalized_mode
        == Config.MODE_INTRADAY
        else (
            Config
            .MIN_REQUIRED_CANDLES_SWING
        )
    )

    if (
        len(
            dataframe
        )
        < minimum_candles
    ):

        raise ValueError(
            (
                f"{normalized_symbol}: "
                f"only {len(dataframe)} "
                "candles available; "
                f"{minimum_candles} "
                "required."
            )
        )

    # ========================================================
    # INDICATORS
    # ========================================================

    close = (
        dataframe[
            "close"
        ]
    )

    dataframe[
        "ema20"
    ] = _ema(
        close,
        Config.EMA_FAST,
    )

    dataframe[
        "ema50"
    ] = _ema(
        close,
        Config.EMA_MEDIUM,
    )

    dataframe[
        "ema200"
    ] = _ema(
        close,
        Config.EMA_LONG,
    )

    dataframe[
        "rsi"
    ] = _rsi(
        close,
        Config.RSI_PERIOD,
    )

    (
        dataframe[
            "macd"
        ],
        dataframe[
            "macd_signal"
        ],
        dataframe[
            "macd_histogram"
        ],
    ) = _macd(
        close
    )

    dataframe[
        "atr"
    ] = _atr(
        dataframe,
        Config.ATR_PERIOD,
    )

    (
        dataframe[
            "supertrend"
        ],
        dataframe[
            "supertrend_direction"
        ],
    ) = _supertrend(
        dataframe
    )

    dataframe[
        "vwap"
    ] = _vwap(
        dataframe
    )

    dataframe[
        "volume_average_20"
    ] = (
        dataframe[
            "volume"
        ]
        .rolling(
            Config.VOLUME_AVG_PERIOD
        )
        .mean()
    )

    latest = (
        dataframe.iloc[
            -1
        ]
    )

    # ========================================================
    # CURRENT VALUES
    # ========================================================

    current_price = _safe_float(
        latest[
            "close"
        ]
    )

    if (
        current_price <= 0
        and not Config.ALLOW_ZERO_PRICE
    ):

        raise ValueError(
            (
                f"{normalized_symbol}: "
                "invalid current price."
            )
        )

    ema20 = _safe_float(
        latest[
            "ema20"
        ]
    )

    ema50 = _safe_float(
        latest[
            "ema50"
        ]
    )

    ema200 = _safe_float(
        latest[
            "ema200"
        ]
    )

    rsi_value = _safe_float(
        latest[
            "rsi"
        ]
    )

    macd_value = _safe_float(
        latest[
            "macd"
        ]
    )

    macd_signal_value = (
        _safe_float(
            latest[
                "macd_signal"
            ]
        )
    )

    macd_histogram = (
        _safe_float(
            latest[
                "macd_histogram"
            ]
        )
    )

    atr_value = _safe_float(
        latest[
            "atr"
        ]
    )

    vwap_value = _safe_float(
        latest[
            "vwap"
        ]
    )

    supertrend_direction = int(
        _safe_float(
            latest[
                "supertrend_direction"
            ]
        )
    )

    current_volume = (
        _safe_float(
            latest[
                "volume"
            ]
        )
    )

    average_volume = (
        _safe_float(
            latest[
                "volume_average_20"
            ]
        )
    )

    # ========================================================
    # EMA TREND
    # ========================================================

    ema_bullish = bool(
        current_price
        > ema20
        and ema20
        > ema50
        and ema50
        > ema200
    )

    # ========================================================
    # RSI
    # ========================================================

    if (
        normalized_mode
        == Config.MODE_INTRADAY
    ):

        rsi_valid = bool(
            Config.INTRADAY_RSI_MIN
            <= rsi_value
            <= Config.INTRADAY_RSI_MAX
        )

        breakout_lookback = (
            Config
            .INTRADAY_BREAKOUT_LOOKBACK
        )

    else:

        rsi_valid = bool(
            Config.SWING_RSI_MIN
            <= rsi_value
            <= Config.SWING_RSI_MAX
        )

        breakout_lookback = (
            Config
            .SWING_BREAKOUT_LOOKBACK
        )

    # ========================================================
    # MACD
    # ========================================================

    macd_bullish = bool(
        macd_value
        > macd_signal_value
        and macd_histogram
        > 0
    )

    # ========================================================
    # SUPERTREND
    # ========================================================

    supertrend_bullish = bool(
        supertrend_direction
        == 1
    )

    # ========================================================
    # VWAP
    # ========================================================

    above_vwap = bool(
        current_price
        > vwap_value
        if vwap_value
        > 0
        else False
    )

    # ========================================================
    # VOLUME
    # ========================================================

    volume_ratio = (
        current_volume
        / average_volume
        if average_volume
        > 0
        else 0.0
    )

    minimum_volume_ratio = (
        Config.get_min_volume_ratio(
            normalized_mode
        )
    )

    volume_confirmed = bool(
        volume_ratio
        >= minimum_volume_ratio
    )

    # ========================================================
    # BREAKOUT
    # ========================================================

    resistance_series = (
        dataframe[
            "high"
        ]
        .iloc[
            :-1
        ]
        .tail(
            breakout_lookback
        )
    )

    support_series = (
        dataframe[
            "low"
        ]
        .iloc[
            :-1
        ]
        .tail(
            breakout_lookback
        )
    )

    resistance = (
        _safe_float(
            resistance_series.max()
        )
        if not resistance_series.empty
        else 0.0
    )

    support = (
        _safe_float(
            support_series.min()
        )
        if not support_series.empty
        else 0.0
    )

    breakout_level = (
        resistance
        * (
            1
            + (
                Config
                .BREAKOUT_BUFFER_PERCENT
                / 100
            )
        )
    )

    breakout = bool(
        resistance
        > 0
        and current_price
        >= breakout_level
    )

    # ========================================================
    # PRICE ACTION
    # ========================================================

    recent_high = (
        dataframe[
            "high"
        ]
        .tail(
            5
        )
    )

    recent_low = (
        dataframe[
            "low"
        ]
        .tail(
            5
        )
    )

    higher_high = bool(
        len(
            recent_high
        )
        >= 3
        and float(
            recent_high.iloc[
                -1
            ]
        )
        > float(
            recent_high.iloc[
                -3
            ]
        )
    )

    higher_low = bool(
        len(
            recent_low
        )
        >= 3
        and float(
            recent_low.iloc[
                -1
            ]
        )
        > float(
            recent_low.iloc[
                -3
            ]
        )
    )

    price_action_bullish = bool(
        higher_high
        and higher_low
    )

    # ========================================================
    # RELATIVE STRENGTH
    # ========================================================

    lookback = max(
        2,
        int(
            Config
            .RELATIVE_STRENGTH_LOOKBACK
        )
        + 1,
    )

    if len(
        close
    ) >= lookback:

        past_price = (
            _safe_float(
                close.iloc[
                    -lookback
                ],
                current_price,
            )
        )

    else:

        past_price = (
            current_price
        )

    if (
        past_price
        > 0
    ):

        stock_change_pct = (
            (
                current_price
                / past_price
            )
            - 1
        ) * 100

    else:

        stock_change_pct = (
            0.0
        )

    relative_strength_pct = (
        float(
            stock_change_pct
        )
        - float(
            benchmark_change_pct
            or 0.0
        )
    )

    relative_strength_bullish = bool(
        relative_strength_pct
        >= Config
        .MIN_RELATIVE_STRENGTH_PCT
    )

    # ========================================================
    # CHART PATTERN
    # ========================================================

    pattern_result = (
        _run_chart_pattern_scanner(
            symbol=(
                normalized_symbol
            ),
            dataframe=(
                dataframe
            ),
            mode=(
                normalized_mode
            ),
        )
    )

    chart_pattern_value = (
        pattern_result.get(
            "strongest_pattern"
        )
    )

    chart_pattern = (
        str(
            chart_pattern_value
        )
        if chart_pattern_value
        not in {
            None,
            "",
        }
        else None
    )

    chart_pattern_score = (
        _safe_float(
            pattern_result.get(
                "score"
            )
        )
    )

    chart_pattern_confirmed = bool(
        pattern_result.get(
            "bullish_pattern",
            False,
        )
    )

    # ========================================================
    # CANDLESTICK PATTERN
    # ========================================================

    (
        candlestick_pattern,
        candlestick_confirmed,
    ) = (
        _detect_candlestick_pattern(
            dataframe
        )
    )

    candlestick_confirmed = bool(
        candlestick_confirmed
    )

    # ========================================================
    # CONFIRMATIONS
    # ========================================================

    confirmations = 0

    reasons: list[str] = []

    rejected_reasons: list[
        str
    ] = []

    if ema_bullish:

        confirmations += 1

        reasons.append(
            (
                "EMA 20 > EMA 50 "
                "> EMA 200"
            )
        )

    else:

        rejected_reasons.append(
            (
                "Bullish EMA structure "
                "missing"
            )
        )

    if rsi_valid:

        confirmations += 1

        reasons.append(
            (
                f"RSI bullish "
                f"{rsi_value:.1f}"
            )
        )

    else:

        rejected_reasons.append(
            (
                "RSI not in ideal range: "
                f"{rsi_value:.1f}"
            )
        )

    if macd_bullish:

        confirmations += 1

        reasons.append(
            "MACD bullish"
        )

    else:

        rejected_reasons.append(
            (
                "MACD confirmation "
                "missing"
            )
        )

    if supertrend_bullish:

        confirmations += 1

        reasons.append(
            "Supertrend BUY"
        )

    else:

        rejected_reasons.append(
            "Supertrend bearish"
        )

    if above_vwap:

        confirmations += 1

        reasons.append(
            "Price above VWAP"
        )

    elif (
        normalized_mode
        == Config.MODE_INTRADAY
    ):

        rejected_reasons.append(
            "Price below VWAP"
        )

    if volume_confirmed:

        confirmations += 1

        reasons.append(
            (
                f"Volume "
                f"{volume_ratio:.2f}x"
            )
        )

    else:

        rejected_reasons.append(
            (
                "Volume weak "
                f"{volume_ratio:.2f}x"
            )
        )

    if breakout:

        confirmations += 1

        reasons.append(
            "Resistance breakout"
        )

    else:

        rejected_reasons.append(
            (
                "Resistance breakout "
                "not confirmed"
            )
        )

    if price_action_bullish:

        confirmations += 1

        reasons.append(
            (
                "Higher High + "
                "Higher Low"
            )
        )

    if relative_strength_bullish:

        confirmations += 1

        reasons.append(
            (
                "Positive Relative Strength "
                f"{relative_strength_pct:.2f}%"
            )
        )

    if chart_pattern_confirmed:

        confirmations += 1

        reasons.append(
            (
                "Confirmed chart pattern: "
                f"{chart_pattern}"
            )
        )

    if candlestick_confirmed:

        confirmations += 1

        reasons.append(
            (
                "Bullish candlestick: "
                f"{candlestick_pattern}"
            )
        )

    # ========================================================
    # TECHNICAL SCORE
    # ========================================================

    score = 0.0

    if (
        normalized_mode
        == Config.MODE_INTRADAY
    ):

        if ema_bullish:
            score += (
                Config
                .INTRADAY_WEIGHT_TREND
            )

        if rsi_valid:
            score += (
                Config
                .INTRADAY_WEIGHT_RSI
            )

        if macd_bullish:
            score += (
                Config
                .INTRADAY_WEIGHT_MACD
            )

        if supertrend_bullish:
            score += (
                Config
                .INTRADAY_WEIGHT_SUPERTREND
            )

        if above_vwap:
            score += (
                Config
                .INTRADAY_WEIGHT_VWAP
            )

        if volume_confirmed:
            score += (
                Config
                .INTRADAY_WEIGHT_VOLUME
            )

        if breakout:
            score += (
                Config
                .INTRADAY_WEIGHT_BREAKOUT
            )

        if price_action_bullish:
            score += (
                Config
                .INTRADAY_WEIGHT_PRICE_ACTION
            )

        if relative_strength_bullish:
            score += (
                Config
                .INTRADAY_WEIGHT_RELATIVE_STRENGTH
            )

        if (
            chart_pattern_confirmed
            or candlestick_confirmed
        ):
            score += (
                Config
                .INTRADAY_WEIGHT_PATTERNS
            )

    else:

        if ema_bullish:
            score += (
                Config
                .SWING_WEIGHT_TREND
            )

        if rsi_valid:
            score += (
                Config
                .SWING_WEIGHT_RSI
            )

        if macd_bullish:
            score += (
                Config
                .SWING_WEIGHT_MACD
            )

        if supertrend_bullish:
            score += (
                Config
                .SWING_WEIGHT_SUPERTREND
            )

        if volume_confirmed:
            score += (
                Config
                .SWING_WEIGHT_VOLUME
            )

        if breakout:
            score += (
                Config
                .SWING_WEIGHT_BREAKOUT
            )

        if price_action_bullish:
            score += (
                Config
                .SWING_WEIGHT_PRICE_ACTION
            )

        if relative_strength_bullish:
            score += (
                Config
                .SWING_WEIGHT_RELATIVE_STRENGTH
            )

        if chart_pattern_confirmed:
            score += (
                Config
                .SWING_WEIGHT_CHART_PATTERN
            )

        if candlestick_confirmed:
            score += (
                Config
                .SWING_WEIGHT_CANDLE_PATTERN
            )

    score = float(
        min(
            100.0,
            max(
                0.0,
                score,
            ),
        )
    )

    # ========================================================
    # ENTRY PRICE
    # ========================================================

    if (
        normalized_mode
        == Config.MODE_INTRADAY
    ):

        entry_buffer_percent = (
            Config
            .ENTRY_BUFFER_PERCENT_INTRADAY
        )

    else:

        entry_buffer_percent = (
            Config
            .ENTRY_BUFFER_PERCENT_SWING
        )

    breakout_entry = (
        resistance
        * (
            1
            + (
                entry_buffer_percent
                / 100
            )
        )
    )

    entry_price = float(
        max(
            current_price,
            breakout_entry,
        )
    )

    # ========================================================
    # STOP LOSS
    # ========================================================

    stop_multiplier = (
        Config
        .get_stop_loss_atr_multiplier(
            normalized_mode
        )
    )

    atr_stop = (
        entry_price
        - (
            atr_value
            * stop_multiplier
        )
    )

    recent_swing_low = (
        _safe_float(
            dataframe[
                "low"
            ]
            .tail(
                10
            )
            .min()
        )
    )

    valid_stops = [
        float(
            value
        )
        for value
        in (
            atr_stop,
            recent_swing_low,
            support,
        )
        if (
            value
            > 0
            and value
            < entry_price
        )
    ]

    if valid_stops:

        stop_loss = float(
            max(
                valid_stops
            )
        )

    else:

        stop_loss = float(
            entry_price
            - (
                atr_value
                * stop_multiplier
            )
        )

    # ========================================================
    # RISK
    # ========================================================

    risk = float(
        entry_price
        - stop_loss
    )

    if risk <= 0:

        risk = float(
            atr_value
            * stop_multiplier
        )

        if risk <= 0:

            risk = float(
                entry_price
                * 0.01
            )

        stop_loss = float(
            entry_price
            - risk
        )

    # ========================================================
    # TARGET
    # ========================================================

    target_multiplier = (
        Config
        .get_target_atr_multiplier(
            normalized_mode
        )
    )

    atr_target = float(
        entry_price
        + (
            atr_value
            * target_multiplier
        )
    )

    rr_target = float(
        entry_price
        + (
            risk
            * Config.MIN_RISK_REWARD
        )
    )

    target_price = float(
        max(
            atr_target,
            rr_target,
        )
    )

    reward = float(
        target_price
        - entry_price
    )

    risk_reward = float(
        (
            reward
            / risk
        )
        if risk
        > 0
        else 0.0
    )

    risk_reward_valid = bool(
        risk_reward
        >= Config.MIN_RISK_REWARD
    )

    # ========================================================
    # STOP LOSS %
    # ========================================================

    stop_loss_percent = float(
        (
            (
                entry_price
                - stop_loss
            )
            / entry_price
            * 100
        )
        if entry_price
        > 0
        else 100.0
    )

    if (
        normalized_mode
        == Config.MODE_INTRADAY
    ):

        maximum_stop_percent = (
            Config
            .MAX_STOP_LOSS_PERCENT_INTRADAY
        )

    else:

        maximum_stop_percent = (
            Config
            .MAX_STOP_LOSS_PERCENT_SWING
        )

    stop_loss_valid = bool(
        0
        < stop_loss_percent
        <= maximum_stop_percent
    )

    if not stop_loss_valid:

        rejected_reasons.append(
            (
                "Stop loss too wide: "
                f"{stop_loss_percent:.2f}%"
            )
        )

    # ========================================================
    # MANDATORY RULES
    # ========================================================

    mandatory_rules: list[
        bool
    ] = []

    if (
        Config
        .REQUIRE_BULLISH_EMA_STRUCTURE
    ):

        mandatory_rules.append(
            bool(
                ema_bullish
            )
        )

    if (
        Config
        .REQUIRE_SUPERTREND_BUY
    ):

        mandatory_rules.append(
            bool(
                supertrend_bullish
            )
        )

    if (
        Config
        .REQUIRE_VALID_RSI
    ):

        mandatory_rules.append(
            bool(
                rsi_valid
            )
        )

    if (
        Config
        .REQUIRE_POSITIVE_RISK_REWARD
    ):

        mandatory_rules.append(
            bool(
                risk_reward_valid
            )
        )

    mandatory_rules.append(
        bool(
            stop_loss_valid
        )
    )

    if (
        normalized_mode
        == Config.MODE_INTRADAY
    ):

        if (
            Config
            .INTRADAY_REQUIRE_MACD_BULLISH
        ):

            mandatory_rules.append(
                bool(
                    macd_bullish
                )
            )

        if (
            Config
            .INTRADAY_REQUIRE_VOLUME_CONFIRMATION
        ):

            mandatory_rules.append(
                bool(
                    volume_confirmed
                )
            )

        if (
            Config
            .INTRADAY_REQUIRE_ABOVE_VWAP
        ):

            mandatory_rules.append(
                bool(
                    above_vwap
                )
            )

    else:

        if (
            Config
            .SWING_REQUIRE_PRICE_ABOVE_EMA20
        ):

            mandatory_rules.append(
                bool(
                    current_price
                    > ema20
                )
            )

        if (
            Config
            .SWING_REQUIRE_PRICE_ABOVE_EMA50
        ):

            mandatory_rules.append(
                bool(
                    current_price
                    > ema50
                )
            )

    mandatory_pass = bool(
        all(
            mandatory_rules
        )
    )

    # ========================================================
    # FINAL SIGNAL
    # ========================================================

    minimum_confirmations = (
        Config
        .get_min_confirmations(
            normalized_mode
        )
    )

    strong_buy = bool(
        mandatory_pass
        and score
        >= Config.STRONG_BUY_MIN_SCORE
        and confirmations
        >= minimum_confirmations
    )

    signal = (
        "STRONG BUY"
        if strong_buy
        else "NO SIGNAL"
    )

    # ========================================================
    # RESULT
    # ========================================================

    return TechnicalResult(
        symbol=(
            normalized_symbol
        ),

        sector=(
            normalized_sector
        ),

        mode=(
            normalized_mode
        ),

        current_price=float(
            current_price
        ),

        entry_price=float(
            entry_price
        ),

        stop_loss=float(
            stop_loss
        ),

        target_price=float(
            target_price
        ),

        risk_reward=float(
            risk_reward
        ),

        technical_score=float(
            score
        ),

        confirmations=int(
            confirmations
        ),

        ema_bullish=bool(
            ema_bullish
        ),

        rsi=float(
            rsi_value
        ),

        macd_bullish=bool(
            macd_bullish
        ),

        supertrend_bullish=bool(
            supertrend_bullish
        ),

        above_vwap=bool(
            above_vwap
        ),

        volume_ratio=float(
            volume_ratio
        ),

        volume_confirmed=bool(
            volume_confirmed
        ),

        breakout=bool(
            breakout
        ),

        breakout_price=(
            float(
                resistance
            )
            if resistance
            > 0
            else None
        ),

        price_action_bullish=bool(
            price_action_bullish
        ),

        relative_strength_pct=float(
            relative_strength_pct
        ),

        relative_strength_bullish=bool(
            relative_strength_bullish
        ),

        chart_pattern=(
            chart_pattern
        ),

        chart_pattern_score=float(
            chart_pattern_score
        ),

        chart_pattern_confirmed=bool(
            chart_pattern_confirmed
        ),

        candlestick_pattern=(
            candlestick_pattern
        ),

        candlestick_confirmed=bool(
            candlestick_confirmed
        ),

        signal=str(
            signal
        ),

        reasons=[
            str(
                reason
            )
            for reason
            in reasons
        ],

        rejected_reasons=[
            str(
                reason
            )
            for reason
            in rejected_reasons
        ],
    )


# ============================================================
# ONLY STRONG BUY HELPER
# ============================================================

def analyze_for_strong_buy(
    symbol: str,
    sector: str,
    candles: (
        pd.DataFrame
        | Iterable[
            dict[str, Any]
        ]
    ),
    mode: str,
    benchmark_change_pct: float = 0.0,
) -> dict[str, Any] | None:

    result = analyze_stock(
        symbol=symbol,
        sector=sector,
        candles=candles,
        mode=mode,
        benchmark_change_pct=(
            benchmark_change_pct
        ),
    )

    if (
        result.signal
        != "STRONG BUY"
    ):
        return None

    return result.to_dict()
