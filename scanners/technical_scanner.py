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

    confirmation_timeframe_bullish: bool
    higher_timeframe_bullish: bool
    multi_timeframe_confirmed: bool

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
            "symbol": self.symbol,
            "sector": self.sector,
            "mode": self.mode,

            "current_price": round(
                self.current_price,
                2,
            ),

            "entry_price": round(
                self.entry_price,
                2,
            ),

            "stop_loss": round(
                self.stop_loss,
                2,
            ),

            "target_price": round(
                self.target_price,
                2,
            ),

            "risk_reward": round(
                self.risk_reward,
                2,
            ),

            "technical_score": round(
                self.technical_score,
                2,
            ),

            "confirmations": (
                self.confirmations
            ),

            "ema_bullish": (
                self.ema_bullish
            ),

            "rsi": round(
                self.rsi,
                2,
            ),

            "macd_bullish": (
                self.macd_bullish
            ),

            "supertrend_bullish": (
                self.supertrend_bullish
            ),

            "above_vwap": (
                self.above_vwap
            ),

            "volume_ratio": round(
                self.volume_ratio,
                2,
            ),

            "volume_confirmed": (
                self.volume_confirmed
            ),

            "breakout": (
                self.breakout
            ),

            "breakout_price": (
                round(
                    self.breakout_price,
                    2,
                )
                if self.breakout_price
                is not None
                else None
            ),

            "price_action_bullish": (
                self.price_action_bullish
            ),

            "relative_strength_pct": round(
                self.relative_strength_pct,
                2,
            ),

            "relative_strength_bullish": (
                self.relative_strength_bullish
            ),

            "chart_pattern": (
                self.chart_pattern
            ),

            "chart_pattern_score": round(
                self.chart_pattern_score,
                2,
            ),

            "chart_pattern_confirmed": (
                self.chart_pattern_confirmed
            ),

            "candlestick_pattern": (
                self.candlestick_pattern
            ),

            "candlestick_confirmed": (
                self.candlestick_confirmed
            ),

            "confirmation_timeframe_bullish": (
                self.confirmation_timeframe_bullish
            ),

            "higher_timeframe_bullish": (
                self.higher_timeframe_bullish
            ),

            "multi_timeframe_confirmed": (
                self.multi_timeframe_confirmed
            ),

            "signal": (
                self.signal
            ),

            "reasons": (
                self.reasons
            ),

            "rejected_reasons": (
                self.rejected_reasons
            ),
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
            return default

        return result

    except (
        TypeError,
        ValueError,
    ):

        return default


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
        ] = (
            pd.to_numeric(
                dataframe[
                    column
                ],
                errors="coerce",
            )
        )


    dataframe = (
        dataframe
        .dropna(
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


    dataframe[
        "timestamp"
    ] = (
        pd.to_numeric(
            dataframe[
                "timestamp"
            ],
            errors="coerce",
        )
    )


    dataframe = (
        dataframe
        .dropna(
            subset=[
                "timestamp"
            ]
        )
    )


    dataframe[
        "timestamp"
    ] = (
        dataframe[
            "timestamp"
        ]
        .astype(
            "int64"
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


    if dataframe.empty:

        raise ValueError(
            (
                "Valid historical candles "
                "are unavailable."
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

    return (
        series
        .ewm(
            span=period,
            adjust=False,
        )
        .mean()
    )


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
        gain
        .ewm(
            alpha=(
                1 / period
            ),
            adjust=False,
        )
        .mean()
    )


    average_loss = (
        loss
        .ewm(
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
                1 + rs
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
        true_range
        .ewm(
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

def _session_vwap(
    dataframe: pd.DataFrame,
    mode: str,
) -> pd.Series:
    """
    Intraday:
        VWAP resets on every IST trading date.

    Swing:
        Standard cumulative VWAP is used only
        as a supporting metric.
    """

    typical_price = (
        (
            dataframe[
                "high"
            ]
            + dataframe[
                "low"
            ]
            + dataframe[
                "close"
            ]
        )
        / 3.0
    )


    volume = (
        dataframe[
            "volume"
        ]
        .replace(
            0,
            np.nan,
        )
    )


    if (
        mode
        == Config.MODE_INTRADAY
    ):

        timestamps = (
            pd.to_datetime(
                dataframe[
                    "timestamp"
                ],
                unit="s",
                utc=True,
            )
            .dt
            .tz_convert(
                "Asia/Kolkata"
            )
        )


        session_date = (
            timestamps.dt.date
        )


        price_volume = (
            typical_price
            * volume
        )


        cumulative_pv = (
            price_volume
            .groupby(
                session_date
            )
            .cumsum()
        )


        cumulative_volume = (
            volume
            .groupby(
                session_date
            )
            .cumsum()
        )


        return (
            cumulative_pv
            / cumulative_volume
        ).ffill()


    cumulative_price_volume = (
        typical_price
        * volume
    ).cumsum()


    cumulative_volume = (
        volume.cumsum()
    )


    return (
        cumulative_price_volume
        / cumulative_volume
    ).ffill()


# ============================================================
# SUPERTREND
# ============================================================

def _supertrend(
    dataframe: pd.DataFrame,
) -> tuple[
    pd.Series,
    pd.Series,
]:

    atr_series = (
        _atr(
            dataframe,
            Config.SUPERTREND_PERIOD,
        )
    )


    hl2 = (
        dataframe[
            "high"
        ]
        + dataframe[
            "low"
        ]
    ) / 2.0


    upper = (
        hl2
        + (
            Config.SUPERTREND_MULTIPLIER
            * atr_series
        )
    )


    lower = (
        hl2
        - (
            Config.SUPERTREND_MULTIPLIER
            * atr_series
        )
    )


    final_upper = (
        upper.copy()
    )

    final_lower = (
        lower.copy()
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
            upper.iloc[
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
            ] = (
                upper.iloc[
                    index
                ]
            )

        else:

            final_upper.iloc[
                index
            ] = (
                final_upper.iloc[
                    index - 1
                ]
            )


        if (
            lower.iloc[
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
            ] = (
                lower.iloc[
                    index
                ]
            )

        else:

            final_lower.iloc[
                index
            ] = (
                final_lower.iloc[
                    index - 1
                ]
            )


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


        if np.isclose(
            previous_supertrend,
            previous_upper,
            equal_nan=False,
        ):

            if (
                close.iloc[
                    index
                ]
                <= final_upper.iloc[
                    index
                ]
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
                close.iloc[
                    index
                ]
                >= final_lower.iloc[
                    index
                ]
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
# INDICATOR FRAME
# ============================================================

def _add_indicators(
    dataframe: pd.DataFrame,
    *,
    mode: str,
) -> pd.DataFrame:

    output = (
        dataframe.copy()
    )

    close = (
        output[
            "close"
        ]
    )


    output[
        "ema20"
    ] = _ema(
        close,
        Config.EMA_FAST,
    )


    output[
        "ema50"
    ] = _ema(
        close,
        Config.EMA_MEDIUM,
    )


    output[
        "ema200"
    ] = _ema(
        close,
        Config.EMA_LONG,
    )


    output[
        "rsi"
    ] = _rsi(
        close,
        Config.RSI_PERIOD,
    )


    (
        output[
            "macd"
        ],
        output[
            "macd_signal"
        ],
        output[
            "macd_histogram"
        ],
    ) = _macd(
        close
    )


    output[
        "atr"
    ] = _atr(
        output,
        Config.ATR_PERIOD,
    )


    (
        output[
            "supertrend"
        ],
        output[
            "supertrend_direction"
        ],
    ) = _supertrend(
        output
    )


    output[
        "vwap"
    ] = (
        _session_vwap(
            output,
            mode,
        )
    )


    output[
        "volume_average_20"
    ] = (
        output[
            "volume"
        ]
        .rolling(
            Config.VOLUME_AVG_PERIOD
        )
        .mean()
    )


    return output


# ============================================================
# TIMEFRAME TREND
# ============================================================

def _timeframe_confirmation(
    candles: (
        pd.DataFrame
        | Iterable[
            dict[str, Any]
        ]
        | None
    ),
    *,
    mode: str,
    require_long_ema: bool = False,
) -> dict[str, Any]:

    if candles is None:

        return {
            "available": False,
            "bullish": False,
            "score": 0.0,
        }


    try:

        dataframe = (
            _prepare_dataframe(
                candles
            )
        )


        if len(
            dataframe
        ) < 50:

            return {
                "available": False,
                "bullish": False,
                "score": 0.0,
            }


        dataframe = (
            _add_indicators(
                dataframe,
                mode=mode,
            )
        )


        latest = (
            dataframe.iloc[
                -1
            ]
        )


        price = _safe_float(
            latest[
                "close"
            ]
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

        macd = _safe_float(
            latest[
                "macd"
            ]
        )

        macd_signal = _safe_float(
            latest[
                "macd_signal"
            ]
        )

        histogram = _safe_float(
            latest[
                "macd_histogram"
            ]
        )

        supertrend_direction = int(
            _safe_float(
                latest[
                    "supertrend_direction"
                ]
            )
        )


        price_above_ema20 = (
            price > ema20
        )

        ema_structure = (
            ema20 > ema50
        )


        long_trend = True

        if (
            require_long_ema
            and len(
                dataframe
            ) >= Config.EMA_LONG
        ):

            long_trend = (
                ema50 > ema200
                and price > ema200
            )


        rsi_bullish = (
            50.0
            <= rsi_value
            <= 75.0
        )


        macd_bullish = (
            macd
            > macd_signal
            and histogram > 0
        )


        supertrend_bullish = (
            supertrend_direction
            == 1
        )


        checks = [
            price_above_ema20,
            ema_structure,
            long_trend,
            rsi_bullish,
            macd_bullish,
            supertrend_bullish,
        ]


        passed = sum(
            1
            for item
            in checks
            if item
        )


        score = (
            passed
            / len(
                checks
            )
            * 100.0
        )


        bullish = (
            price_above_ema20
            and ema_structure
            and long_trend
            and supertrend_bullish
            and passed >= 5
        )


        return {
            "available": True,

            "bullish": (
                bullish
            ),

            "score": round(
                score,
                2,
            ),

            "price_above_ema20": (
                price_above_ema20
            ),

            "ema_structure": (
                ema_structure
            ),

            "long_trend": (
                long_trend
            ),

            "rsi": (
                rsi_value
            ),

            "rsi_bullish": (
                rsi_bullish
            ),

            "macd_bullish": (
                macd_bullish
            ),

            "supertrend_bullish": (
                supertrend_bullish
            ),
        }


    except Exception:

        return {
            "available": False,
            "bullish": False,
            "score": 0.0,
        }


# ============================================================
# CURRENT TRADING-DAY RETURN
# ============================================================

def _current_period_return(
    dataframe: pd.DataFrame,
    *,
    mode: str,
) -> float:

    if len(
        dataframe
    ) < 2:

        return 0.0


    if (
        mode
        == Config.MODE_INTRADAY
    ):

        datetimes = (
            pd.to_datetime(
                dataframe[
                    "timestamp"
                ],
                unit="s",
                utc=True,
            )
            .dt
            .tz_convert(
                "Asia/Kolkata"
            )
        )


        latest_date = (
            datetimes.iloc[
                -1
            ].date()
        )


        mask = (
            datetimes.dt.date
            == latest_date
        )


        session = (
            dataframe.loc[
                mask
            ]
        )


        if session.empty:

            return 0.0


        start_price = (
            _safe_float(
                session[
                    "open"
                ].iloc[
                    0
                ]
            )
        )


        end_price = (
            _safe_float(
                session[
                    "close"
                ].iloc[
                    -1
                ]
            )
        )


    else:

        start_price = (
            _safe_float(
                dataframe[
                    "close"
                ].iloc[
                    -2
                ]
            )
        )


        end_price = (
            _safe_float(
                dataframe[
                    "close"
                ].iloc[
                    -1
                ]
            )
        )


    if (
        start_price <= 0
        or end_price <= 0
    ):

        return 0.0


    return (
        (
            end_price
            / start_price
        )
        - 1
    ) * 100.0


# ============================================================
# CANDLESTICK PATTERN
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


    o = _safe_float(
        current[
            "open"
        ]
    )

    h = _safe_float(
        current[
            "high"
        ]
    )

    l = _safe_float(
        current[
            "low"
        ]
    )

    c = _safe_float(
        current[
            "close"
        ]
    )


    previous_o = _safe_float(
        previous[
            "open"
        ]
    )

    previous_c = _safe_float(
        previous[
            "close"
        ]
    )

    previous_l = _safe_float(
        previous[
            "low"
        ]
    )


    first_o = _safe_float(
        first[
            "open"
        ]
    )

    first_c = _safe_float(
        first[
            "close"
        ]
    )


    body = abs(
        c - o
    )


    candle_range = max(
        h - l,
        0.0001,
    )


    upper_wick = (
        h
        - max(
            o,
            c,
        )
    )


    lower_wick = (
        min(
            o,
            c,
        )
        - l
    )


    bullish = (
        c > o
    )


    previous_bearish = (
        previous_c
        < previous_o
    )


    # 1 Bullish Engulfing
    if (
        bullish
        and previous_bearish
        and o <= previous_c
        and c >= previous_o
    ):

        return (
            "Bullish Engulfing",
            True,
        )


    # 2 Hammer
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


    # 3 Morning Star
    if (
        first_c < first_o
        and abs(
            previous_c
            - previous_o
        )
        < abs(
            first_c
            - first_o
        ) * 0.6
        and bullish
        and c
        > (
            first_o
            + first_c
        ) / 2
    ):

        return (
            "Morning Star",
            True,
        )


    # 4 Piercing Pattern
    if (
        previous_bearish
        and bullish
        and o <= previous_c
        and c
        > (
            previous_o
            + previous_c
        ) / 2
        and c < previous_o
    ):

        return (
            "Piercing Pattern",
            True,
        )


    # 5 Bullish Harami
    if (
        previous_bearish
        and bullish
        and o > previous_c
        and c < previous_o
    ):

        return (
            "Bullish Harami",
            True,
        )


    # 6 Bullish Marubozu
    if (
        bullish
        and (
            body
            / candle_range
        ) >= 0.80
    ):

        return (
            "Bullish Marubozu",
            True,
        )


    # 7 Inverted Hammer
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


    # 8 Three White Soldiers
    if (
        first_c > first_o
        and previous_c > previous_o
        and c > o
        and previous_c > first_c
        and c > previous_c
    ):

        return (
            "Three White Soldiers",
            True,
        )


    # 9 Tweezer Bottom
    if (
        previous_bearish
        and bullish
        and abs(
            l
            - previous_l
        )
        / max(
            l,
            0.0001,
        )
        <= 0.003
    ):

        return (
            "Tweezer Bottom",
            True,
        )


    # 10 Bullish Doji
    if (
        body
        / candle_range
        <= 0.10
        and c
        >= (
            h + l
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


    try:

        return (
            scanner.scan(
                symbol=(
                    symbol
                ),
                candles=(
                    candle_records
                ),
                timeframe=(
                    "15_30_days"
                ),
            )
        )


    except PatternScannerError:

        return {
            "symbol": (
                symbol
            ),

            "score": 0.0,

            "bullish_pattern": (
                False
            ),

            "strongest_pattern": (
                None
            ),

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
        | None
    ) = None,
    mode: str = "swing",
    benchmark_change_pct: float = 0.0,
    *,
    primary_candles: (
        pd.DataFrame
        | Iterable[
            dict[str, Any]
        ]
        | None
    ) = None,
    confirmation_candles: (
        pd.DataFrame
        | Iterable[
            dict[str, Any]
        ]
        | None
    ) = None,
    higher_timeframe_candles: (
        pd.DataFrame
        | Iterable[
            dict[str, Any]
        ]
        | None
    ) = None,
) -> TechnicalResult:
    """
    Full multi-timeframe technical analysis.

    Compatibility:
        Existing callers using candles= continue to work.

    Preferred call:
        primary_candles=
        confirmation_candles=
        higher_timeframe_candles=
    """

    normalized_mode = (
        Config.normalize_trading_mode(
            mode
        )
    )


    primary_source = (
        primary_candles
        if primary_candles
        is not None
        else candles
    )


    if primary_source is None:

        raise ValueError(
            (
                f"{symbol}: primary candle "
                "data is required."
            )
        )


    dataframe = (
        _prepare_dataframe(
            primary_source
        )
    )


    minimum_candles = (
        Config.MIN_REQUIRED_CANDLES_INTRADAY
        if normalized_mode
        == Config.MODE_INTRADAY
        else Config.MIN_REQUIRED_CANDLES_SWING
    )


    if (
        len(
            dataframe
        )
        < minimum_candles
    ):

        raise ValueError(
            (
                f"{symbol}: only "
                f"{len(dataframe)} "
                "primary candles available; "
                f"{minimum_candles} required."
            )
        )


    dataframe = (
        _add_indicators(
            dataframe,
            mode=(
                normalized_mode
            ),
        )
    )


    latest = (
        dataframe.iloc[
            -1
        ]
    )


    # ========================================================
    # PRIMARY VALUES
    # ========================================================

    current_price = (
        _safe_float(
            latest[
                "close"
            ]
        )
    )


    if (
        current_price <= 0
        and not Config.ALLOW_ZERO_PRICE
    ):

        raise ValueError(
            (
                f"{symbol}: invalid "
                "current price."
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

    atr_value = (
        _safe_float(
            latest[
                "atr"
            ]
        )
    )

    vwap_value = (
        _safe_float(
            latest[
                "vwap"
            ]
        )
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
    # EMA
    # ========================================================

    ema_bullish = (
        current_price > ema20
        and ema20 > ema50
        and ema50 > ema200
    )


    # ========================================================
    # RSI + BREAKOUT SETTINGS
    # ========================================================

    if (
        normalized_mode
        == Config.MODE_INTRADAY
    ):

        rsi_valid = (
            Config.INTRADAY_RSI_MIN
            <= rsi_value
            <= Config.INTRADAY_RSI_MAX
        )

        breakout_lookback = (
            Config.INTRADAY_BREAKOUT_LOOKBACK
        )

    else:

        rsi_valid = (
            Config.SWING_RSI_MIN
            <= rsi_value
            <= Config.SWING_RSI_MAX
        )

        breakout_lookback = (
            Config.SWING_BREAKOUT_LOOKBACK
        )


    # ========================================================
    # MACD
    # ========================================================

    macd_bullish = (
        macd_value
        > macd_signal_value
        and macd_histogram > 0
    )


    # ========================================================
    # SUPERTREND
    # ========================================================

    supertrend_bullish = (
        supertrend_direction
        == 1
    )


    # ========================================================
    # VWAP
    # ========================================================

    above_vwap = (
        current_price > vwap_value
        if vwap_value > 0
        else False
    )


    # ========================================================
    # VOLUME
    # ========================================================

    volume_ratio = (
        current_volume
        / average_volume
        if average_volume > 0
        else 0.0
    )


    minimum_volume_ratio = (
        Config.get_min_volume_ratio(
            normalized_mode
        )
    )


    volume_confirmed = (
        volume_ratio
        >= minimum_volume_ratio
    )


    # ========================================================
    # BREAKOUT
    # ========================================================

    historical_slice = (
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


    resistance = (
        _safe_float(
            historical_slice.max()
        )
        if not historical_slice.empty
        else 0.0
    )


    support_slice = (
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


    support = (
        _safe_float(
            support_slice.min()
        )
        if not support_slice.empty
        else 0.0
    )


    breakout_level = (
        resistance
        * (
            1
            + (
                Config.BREAKOUT_BUFFER_PERCENT
                / 100.0
            )
        )
    )


    breakout = (
        resistance > 0
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


    higher_high = (
        len(
            recent_high
        ) >= 3
        and recent_high.iloc[
            -1
        ]
        > recent_high.iloc[
            -3
        ]
    )


    higher_low = (
        len(
            recent_low
        ) >= 3
        and recent_low.iloc[
            -1
        ]
        > recent_low.iloc[
            -3
        ]
    )


    price_action_bullish = (
        higher_high
        and higher_low
    )


    # ========================================================
    # SAME-DAY RELATIVE STRENGTH
    # ========================================================

    stock_period_change = (
        _current_period_return(
            dataframe,
            mode=(
                normalized_mode
            ),
        )
    )


    relative_strength_pct = (
        stock_period_change
        - float(
            benchmark_change_pct
            or 0.0
        )
    )


    relative_strength_bullish = (
        relative_strength_pct
        >= Config.MIN_RELATIVE_STRENGTH_PCT
    )


    # ========================================================
    # CHART PATTERN
    # ========================================================

    pattern_result = (
        _run_chart_pattern_scanner(
            symbol=(
                symbol
            ),
            dataframe=(
                dataframe
            ),
        )
    )


    chart_pattern = (
        pattern_result.get(
            "strongest_pattern"
        )
    )


    chart_pattern_score = (
        _safe_float(
            pattern_result.get(
                "score"
            )
        )
    )


    chart_pattern_confirmed = (
        bool(
            pattern_result.get(
                "bullish_pattern",
                False,
            )
        )
    )


    # ========================================================
    # CANDLESTICK
    # ========================================================

    (
        candlestick_pattern,
        candlestick_confirmed,
    ) = (
        _detect_candlestick_pattern(
            dataframe
        )
    )


    # ========================================================
    # MULTI-TIMEFRAME CONFIRMATION
    # ========================================================

    confirmation_snapshot = (
        _timeframe_confirmation(
            confirmation_candles,
            mode=(
                normalized_mode
            ),
            require_long_ema=False,
        )
    )


    higher_snapshot = (
        _timeframe_confirmation(
            higher_timeframe_candles,
            mode=(
                normalized_mode
            ),
            require_long_ema=(
                normalized_mode
                == Config.MODE_INTRADAY
            ),
        )
    )


    confirmation_timeframe_bullish = (
        bool(
            confirmation_snapshot.get(
                "bullish",
                False,
            )
        )
    )


    higher_timeframe_bullish = (
        bool(
            higher_snapshot.get(
                "bullish",
                False,
            )
        )
    )


    # Swing weekly confirmation is generally
    # supplied as both confirmation and higher timeframe.
    if (
        normalized_mode
        == Config.MODE_SWING
        and confirmation_timeframe_bullish
        and higher_timeframe_candles
        is None
    ):

        higher_timeframe_bullish = (
            confirmation_timeframe_bullish
        )


    multi_timeframe_confirmed = (
        confirmation_timeframe_bullish
        and higher_timeframe_bullish
    )


    # ========================================================
    # CONFIRMATIONS
    # ========================================================

    confirmations = 0

    reasons: list[
        str
    ] = []

    rejected_reasons: list[
        str
    ] = []


    if ema_bullish:

        confirmations += 1

        reasons.append(
            (
                "Primary EMA 20 > "
                "EMA 50 > EMA 200"
            )
        )

    else:

        rejected_reasons.append(
            (
                "Primary bullish EMA "
                "structure missing"
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
                "RSI outside ideal range: "
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
            "MACD confirmation missing"
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
            "Price below intraday VWAP"
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
                f"Volume weak "
                f"{volume_ratio:.2f}x"
            )
        )


    if breakout:

        confirmations += 1

        reasons.append(
            "Resistance breakout"
        )


    if price_action_bullish:

        confirmations += 1

        reasons.append(
            "Higher High + Higher Low"
        )


    if relative_strength_bullish:

        confirmations += 1

        reasons.append(
            (
                "Stock outperforming "
                "Nifty by "
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


    if confirmation_timeframe_bullish:

        confirmations += 1

        reasons.append(
            (
                "Confirmation timeframe "
                "trend bullish"
            )
        )

    else:

        rejected_reasons.append(
            (
                "Confirmation timeframe "
                "is not bullish"
            )
        )


    if higher_timeframe_bullish:

        confirmations += 1

        reasons.append(
            (
                "Higher timeframe "
                "trend bullish"
            )
        )

    else:

        rejected_reasons.append(
            (
                "Higher timeframe "
                "confirmation missing"
            )
        )


    # ========================================================
    # PRIMARY TECHNICAL SCORE
    # ========================================================

    score = 0.0


    if (
        normalized_mode
        == Config.MODE_INTRADAY
    ):

        if ema_bullish:
            score += (
                Config.INTRADAY_WEIGHT_TREND
            )

        if rsi_valid:
            score += (
                Config.INTRADAY_WEIGHT_RSI
            )

        if macd_bullish:
            score += (
                Config.INTRADAY_WEIGHT_MACD
            )

        if supertrend_bullish:
            score += (
                Config.INTRADAY_WEIGHT_SUPERTREND
            )

        if above_vwap:
            score += (
                Config.INTRADAY_WEIGHT_VWAP
            )

        if volume_confirmed:
            score += (
                Config.INTRADAY_WEIGHT_VOLUME
            )

        if breakout:
            score += (
                Config.INTRADAY_WEIGHT_BREAKOUT
            )

        if price_action_bullish:
            score += (
                Config.INTRADAY_WEIGHT_PRICE_ACTION
            )

        if relative_strength_bullish:
            score += (
                Config.INTRADAY_WEIGHT_RELATIVE_STRENGTH
            )

        if (
            chart_pattern_confirmed
            or candlestick_confirmed
        ):

            score += (
                Config.INTRADAY_WEIGHT_PATTERNS
            )


    else:

        if ema_bullish:
            score += (
                Config.SWING_WEIGHT_TREND
            )

        if rsi_valid:
            score += (
                Config.SWING_WEIGHT_RSI
            )

        if macd_bullish:
            score += (
                Config.SWING_WEIGHT_MACD
            )

        if supertrend_bullish:
            score += (
                Config.SWING_WEIGHT_SUPERTREND
            )

        if volume_confirmed:
            score += (
                Config.SWING_WEIGHT_VOLUME
            )

        if breakout:
            score += (
                Config.SWING_WEIGHT_BREAKOUT
            )

        if price_action_bullish:
            score += (
                Config.SWING_WEIGHT_PRICE_ACTION
            )

        if relative_strength_bullish:
            score += (
                Config.SWING_WEIGHT_RELATIVE_STRENGTH
            )

        if chart_pattern_confirmed:
            score += (
                Config.SWING_WEIGHT_CHART_PATTERN
            )

        if candlestick_confirmed:
            score += (
                Config.SWING_WEIGHT_CANDLE_PATTERN
            )


    # Multi-timeframe confirmation is used
    # as a quality adjustment without requiring
    # additional Config variables.

    if multi_timeframe_confirmed:

        score = min(
            100.0,
            score + 5.0,
        )

    elif (
        confirmation_timeframe_bullish
        or higher_timeframe_bullish
    ):

        score = max(
            0.0,
            score - 5.0,
        )

    else:

        score = max(
            0.0,
            score - 10.0,
        )


    score = min(
        100.0,
        max(
            0.0,
            score,
        ),
    )


    # ========================================================
    # ENTRY
    # ========================================================

    if (
        normalized_mode
        == Config.MODE_INTRADAY
    ):

        entry_buffer_percent = (
            Config.ENTRY_BUFFER_PERCENT_INTRADAY
        )

    else:

        entry_buffer_percent = (
            Config.ENTRY_BUFFER_PERCENT_SWING
        )


    breakout_entry = (
        resistance
        * (
            1
            + (
                entry_buffer_percent
                / 100.0
            )
        )
    )


    entry_price = (
        max(
            current_price,
            breakout_entry,
        )
        if resistance > 0
        else current_price
    )


    # ========================================================
    # STOP LOSS
    # ========================================================

    stop_multiplier = (
        Config.get_stop_loss_atr_multiplier(
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
        value

        for value
        in (
            atr_stop,
            recent_swing_low,
            support,
        )

        if (
            value > 0
            and value < entry_price
        )
    ]


    if valid_stops:

        stop_loss = (
            max(
                valid_stops
            )
        )

    else:

        stop_loss = (
            entry_price
            - (
                atr_value
                * stop_multiplier
            )
        )


    # ========================================================
    # RISK
    # ========================================================

    risk = (
        entry_price
        - stop_loss
    )


    if risk <= 0:

        risk = (
            atr_value
            * stop_multiplier
        )


        if risk <= 0:

            risk = (
                entry_price
                * 0.01
            )


        stop_loss = (
            entry_price
            - risk
        )


    # ========================================================
    # TARGET
    # ========================================================

    target_multiplier = (
        Config.get_target_atr_multiplier(
            normalized_mode
        )
    )


    atr_target = (
        entry_price
        + (
            atr_value
            * target_multiplier
        )
    )


    rr_target = (
        entry_price
        + (
            risk
            * Config.MIN_RISK_REWARD
        )
    )


    target_price = (
        max(
            atr_target,
            rr_target,
        )
    )


    reward = (
        target_price
        - entry_price
    )


    risk_reward = (
        reward
        / risk
        if risk > 0
        else 0.0
    )


    risk_reward_valid = (
        risk_reward
        >= Config.MIN_RISK_REWARD
    )


    # ========================================================
    # STOP LOSS WIDTH
    # ========================================================

    stop_loss_percent = (
        (
            entry_price
            - stop_loss
        )
        / entry_price
        * 100.0
        if entry_price > 0
        else 100.0
    )


    if (
        normalized_mode
        == Config.MODE_INTRADAY
    ):

        maximum_stop_percent = (
            Config.MAX_STOP_LOSS_PERCENT_INTRADAY
        )

    else:

        maximum_stop_percent = (
            Config.MAX_STOP_LOSS_PERCENT_SWING
        )


    stop_loss_valid = (
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
        Config.REQUIRE_BULLISH_EMA_STRUCTURE
    ):

        mandatory_rules.append(
            ema_bullish
        )


    if (
        Config.REQUIRE_SUPERTREND_BUY
    ):

        mandatory_rules.append(
            supertrend_bullish
        )


    if (
        Config.REQUIRE_VALID_RSI
    ):

        mandatory_rules.append(
            rsi_valid
        )


    if (
        Config.REQUIRE_POSITIVE_RISK_REWARD
    ):

        mandatory_rules.append(
            risk_reward_valid
        )


    mandatory_rules.append(
        stop_loss_valid
    )


    # Multi-timeframe confirmation is mandatory.
    mandatory_rules.append(
        multi_timeframe_confirmed
    )


    if (
        normalized_mode
        == Config.MODE_INTRADAY
    ):

        if (
            Config.INTRADAY_REQUIRE_MACD_BULLISH
        ):

            mandatory_rules.append(
                macd_bullish
            )


        if (
            Config.INTRADAY_REQUIRE_VOLUME_CONFIRMATION
        ):

            mandatory_rules.append(
                volume_confirmed
            )


        if (
            Config.INTRADAY_REQUIRE_ABOVE_VWAP
        ):

            mandatory_rules.append(
                above_vwap
            )


    else:

        if (
            Config.SWING_REQUIRE_PRICE_ABOVE_EMA20
        ):

            mandatory_rules.append(
                current_price
                > ema20
            )


        if (
            Config.SWING_REQUIRE_PRICE_ABOVE_EMA50
        ):

            mandatory_rules.append(
                current_price
                > ema50
            )


    mandatory_pass = (
        all(
            mandatory_rules
        )
    )


    # ========================================================
    # FINAL SIGNAL
    # ========================================================

    minimum_confirmations = (
        Config.get_min_confirmations(
            normalized_mode
        )
    )


    strong_buy = (
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


    return TechnicalResult(
        symbol=(
            symbol
        ),

        sector=(
            sector
        ),

        mode=(
            normalized_mode
        ),

        current_price=(
            current_price
        ),

        entry_price=(
            entry_price
        ),

        stop_loss=(
            stop_loss
        ),

        target_price=(
            target_price
        ),

        risk_reward=(
            risk_reward
        ),

        technical_score=(
            score
        ),

        confirmations=(
            confirmations
        ),

        ema_bullish=(
            ema_bullish
        ),

        rsi=(
            rsi_value
        ),

        macd_bullish=(
            macd_bullish
        ),

        supertrend_bullish=(
            supertrend_bullish
        ),

        above_vwap=(
            above_vwap
        ),

        volume_ratio=(
            volume_ratio
        ),

        volume_confirmed=(
            volume_confirmed
        ),

        breakout=(
            breakout
        ),

        breakout_price=(
            resistance
            if resistance > 0
            else None
        ),

        price_action_bullish=(
            price_action_bullish
        ),

        relative_strength_pct=(
            relative_strength_pct
        ),

        relative_strength_bullish=(
            relative_strength_bullish
        ),

        chart_pattern=(
            chart_pattern
        ),

        chart_pattern_score=(
            chart_pattern_score
        ),

        chart_pattern_confirmed=(
            chart_pattern_confirmed
        ),

        candlestick_pattern=(
            candlestick_pattern
        ),

        candlestick_confirmed=(
            candlestick_confirmed
        ),

        confirmation_timeframe_bullish=(
            confirmation_timeframe_bullish
        ),

        higher_timeframe_bullish=(
            higher_timeframe_bullish
        ),

        multi_timeframe_confirmed=(
            multi_timeframe_confirmed
        ),

        signal=(
            signal
        ),

        reasons=(
            reasons
        ),

        rejected_reasons=(
            rejected_reasons
        ),
    )


# ============================================================
# STRONG BUY HELPER
# ============================================================

def analyze_for_strong_buy(
    symbol: str,
    sector: str,
    candles: (
        pd.DataFrame
        | Iterable[
            dict[str, Any]
        ]
        | None
    ) = None,
    mode: str = "swing",
    benchmark_change_pct: float = 0.0,
    *,
    primary_candles: (
        pd.DataFrame
        | Iterable[
            dict[str, Any]
        ]
        | None
    ) = None,
    confirmation_candles: (
        pd.DataFrame
        | Iterable[
            dict[str, Any]
        ]
        | None
    ) = None,
    higher_timeframe_candles: (
        pd.DataFrame
        | Iterable[
            dict[str, Any]
        ]
        | None
    ) = None,
) -> dict[str, Any] | None:

    result = (
        analyze_stock(
            symbol=(
                symbol
            ),

            sector=(
                sector
            ),

            candles=(
                candles
            ),

            mode=(
                mode
            ),

            benchmark_change_pct=(
                benchmark_change_pct
            ),

            primary_candles=(
                primary_candles
            ),

            confirmation_candles=(
                confirmation_candles
            ),

            higher_timeframe_candles=(
                higher_timeframe_candles
            ),
        )
    )


    if (
        result.signal
        != "STRONG BUY"
    ):

        return None


    return (
        result.to_dict()
    )
