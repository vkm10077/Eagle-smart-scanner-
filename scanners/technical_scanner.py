from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd

from utils.helpers import (
    clean_text,
    normalize_score,
    normalize_symbol,
    normalize_timeframe,
    safe_float,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_exception,
)


logger = get_logger("scanners.technical_scanner")


class TechnicalScannerError(RuntimeError):
    """Raised when technical analysis cannot be completed."""


@dataclass
class TechnicalFilterResult:
    name: str
    label: str
    passed: bool
    score: float
    weight: float
    value: Any = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "passed": self.passed,
            "score": round(self.score, 2),
            "weight": round(self.weight, 2),
            "value": self.value,
            "reason": self.reason,
        }


@dataclass
class TechnicalScanResult:
    symbol: str
    timeframe: str
    score: float
    passed_count: int
    total_filters: int
    bullish: bool
    current_price: float
    filters: list[TechnicalFilterResult] = field(
        default_factory=list
    )
    indicators: dict[str, Any] = field(
        default_factory=dict
    )
    support: float | None = None
    resistance: float | None = None
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "score": round(self.score, 2),
            "passed_count": self.passed_count,
            "total_filters": self.total_filters,
            "bullish": self.bullish,
            "current_price": round(
                self.current_price,
                2,
            ),
            "filters": [
                item.to_dict()
                for item in self.filters
            ],
            "indicators": self.indicators,
            "support": (
                round(self.support, 2)
                if self.support is not None
                else None
            ),
            "resistance": (
                round(self.resistance, 2)
                if self.resistance is not None
                else None
            ),
            "generated_at": self.generated_at,
        }


class TechnicalScanner:
    """
    Top-10 technical filter scanner.

    Filters:
    1. EMA 20
    2. EMA 50
    3. EMA 200
    4. RSI
    5. MACD
    6. Supertrend
    7. ADX
    8. Volume breakout
    9. Support/resistance breakout
    10. Relative strength versus Nifty
    """

    FILTER_LABELS = {
        "EMA20": "Price Above EMA 20",
        "EMA50": "Price Above EMA 50",
        "EMA200": "Price Above EMA 200",
        "RSI": "RSI Strength",
        "MACD": "MACD Bullish",
        "SUPERTREND": "Supertrend Bullish",
        "ADX": "ADX Trend Strength",
        "VOLUME_BREAKOUT": "Volume Breakout",
        "SUPPORT_RESISTANCE": (
            "Resistance Breakout"
        ),
        "RELATIVE_STRENGTH": (
            "Relative Strength vs Nifty"
        ),
    }

    TIMEFRAME_WEIGHTS = {
        "15_30_days": {
            "EMA20": 14,
            "EMA50": 11,
            "EMA200": 5,
            "RSI": 12,
            "MACD": 12,
            "SUPERTREND": 12,
            "ADX": 8,
            "VOLUME_BREAKOUT": 11,
            "SUPPORT_RESISTANCE": 10,
            "RELATIVE_STRENGTH": 5,
        },
        "3_month": {
            "EMA20": 10,
            "EMA50": 13,
            "EMA200": 8,
            "RSI": 9,
            "MACD": 11,
            "SUPERTREND": 10,
            "ADX": 10,
            "VOLUME_BREAKOUT": 10,
            "SUPPORT_RESISTANCE": 10,
            "RELATIVE_STRENGTH": 9,
        },
        "6_month": {
            "EMA20": 6,
            "EMA50": 14,
            "EMA200": 14,
            "RSI": 8,
            "MACD": 10,
            "SUPERTREND": 9,
            "ADX": 11,
            "VOLUME_BREAKOUT": 7,
            "SUPPORT_RESISTANCE": 9,
            "RELATIVE_STRENGTH": 12,
        },
        "1_year": {
            "EMA20": 4,
            "EMA50": 12,
            "EMA200": 18,
            "RSI": 7,
            "MACD": 9,
            "SUPERTREND": 8,
            "ADX": 11,
            "VOLUME_BREAKOUT": 6,
            "SUPPORT_RESISTANCE": 8,
            "RELATIVE_STRENGTH": 17,
        },
        "3_year": {
            "EMA20": 3,
            "EMA50": 10,
            "EMA200": 20,
            "RSI": 6,
            "MACD": 8,
            "SUPERTREND": 7,
            "ADX": 10,
            "VOLUME_BREAKOUT": 5,
            "SUPPORT_RESISTANCE": 7,
            "RELATIVE_STRENGTH": 24,
        },
    }

    MINIMUM_SCORE = {
        "15_30_days": 72.0,
        "3_month": 72.0,
        "6_month": 70.0,
        "1_year": 68.0,
        "3_year": 65.0,
    }

    MINIMUM_PASSED_FILTERS = {
        "15_30_days": 7,
        "3_month": 7,
        "6_month": 7,
        "1_year": 6,
        "3_year": 6,
    }

    def _build_dataframe(
        self,
        candles: Iterable[dict[str, Any]],
    ) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            row = {
                "timestamp": candle.get(
                    "timestamp"
                )
                or candle.get("date"),
                "open": safe_float(
                    candle.get("open")
                ),
                "high": safe_float(
                    candle.get("high")
                ),
                "low": safe_float(
                    candle.get("low")
                ),
                "close": safe_float(
                    candle.get("close")
                ),
                "volume": safe_float(
                    candle.get("volume"),
                    default=0.0,
                ),
            }

            if any(
                row[field] is None
                for field in (
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                )
            ):
                continue

            rows.append(row)

        if len(rows) < 210:
            raise TechnicalScannerError(
                "At least 210 valid daily candles are required."
            )

        dataframe = pd.DataFrame(rows)

        dataframe = dataframe.drop_duplicates(
            subset=["timestamp"],
            keep="last",
        )

        dataframe = dataframe.sort_values(
            by="timestamp"
        )

        dataframe = dataframe.reset_index(
            drop=True
        )

        numeric_columns = [
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        dataframe[numeric_columns] = (
            dataframe[numeric_columns]
            .apply(
                pd.to_numeric,
                errors="coerce",
            )
        )

        dataframe = dataframe.dropna(
            subset=numeric_columns
        )

        if len(dataframe) < 210:
            raise TechnicalScannerError(
                "Insufficient clean candle history."
            )

        return dataframe

    @staticmethod
    def _ema(
        series: pd.Series,
        period: int,
    ) -> pd.Series:
        return series.ewm(
            span=period,
            adjust=False,
        ).mean()

    @staticmethod
    def _rsi(
        series: pd.Series,
        period: int = 14,
    ) -> pd.Series:
        delta = series.diff()

        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        average_gain = gain.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        average_loss = loss.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        relative_strength = (
            average_gain
            / average_loss.replace(
                0,
                np.nan,
            )
        )

        rsi = 100 - (
            100 / (1 + relative_strength)
        )

        return rsi.fillna(50.0)

    def _macd(
        self,
        series: pd.Series,
    ) -> tuple[
        pd.Series,
        pd.Series,
        pd.Series,
    ]:
        ema_12 = self._ema(series, 12)
        ema_26 = self._ema(series, 26)

        macd_line = ema_12 - ema_26
        signal_line = self._ema(
            macd_line,
            9,
        )
        histogram = (
            macd_line - signal_line
        )

        return (
            macd_line,
            signal_line,
            histogram,
        )

    @staticmethod
    def _true_range(
        dataframe: pd.DataFrame,
    ) -> pd.Series:
        previous_close = (
            dataframe["close"].shift(1)
        )

        ranges = pd.concat(
            [
                dataframe["high"]
                - dataframe["low"],
                (
                    dataframe["high"]
                    - previous_close
                ).abs(),
                (
                    dataframe["low"]
                    - previous_close
                ).abs(),
            ],
            axis=1,
        )

        return ranges.max(axis=1)

    def _atr(
        self,
        dataframe: pd.DataFrame,
        period: int = 14,
    ) -> pd.Series:
        true_range = self._true_range(
            dataframe
        )

        return true_range.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()

    def _adx(
        self,
        dataframe: pd.DataFrame,
        period: int = 14,
    ) -> tuple[
        pd.Series,
        pd.Series,
        pd.Series,
    ]:
        high_difference = (
            dataframe["high"].diff()
        )

        low_difference = (
            -dataframe["low"].diff()
        )

        positive_dm = pd.Series(
            np.where(
                (
                    high_difference
                    > low_difference
                )
                & (
                    high_difference > 0
                ),
                high_difference,
                0.0,
            ),
            index=dataframe.index,
        )

        negative_dm = pd.Series(
            np.where(
                (
                    low_difference
                    > high_difference
                )
                & (
                    low_difference > 0
                ),
                low_difference,
                0.0,
            ),
            index=dataframe.index,
        )

        atr = self._atr(
            dataframe,
            period,
        ).replace(0, np.nan)

        positive_di = (
            100
            * positive_dm.ewm(
                alpha=1 / period,
                adjust=False,
            ).mean()
            / atr
        )

        negative_di = (
            100
            * negative_dm.ewm(
                alpha=1 / period,
                adjust=False,
            ).mean()
            / atr
        )

        denominator = (
            positive_di + negative_di
        ).replace(0, np.nan)

        dx = (
            100
            * (
                positive_di
                - negative_di
            ).abs()
            / denominator
        )

        adx = dx.ewm(
            alpha=1 / period,
            adjust=False,
        ).mean()

        return (
            adx.fillna(0.0),
            positive_di.fillna(0.0),
            negative_di.fillna(0.0),
        )

    def _supertrend(
        self,
        dataframe: pd.DataFrame,
        period: int = 10,
        multiplier: float = 3.0,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        atr = self._atr(
            result,
            period,
        )

        hl2 = (
            result["high"]
            + result["low"]
        ) / 2

        upper_band = (
            hl2 + multiplier * atr
        )

        lower_band = (
            hl2 - multiplier * atr
        )

        final_upper = upper_band.copy()
        final_lower = lower_band.copy()

        supertrend = pd.Series(
            np.nan,
            index=result.index,
        )

        direction = pd.Series(
            1,
            index=result.index,
            dtype=int,
        )

        for index in range(
            1,
            len(result),
        ):
            previous_index = index - 1

            if (
                upper_band.iloc[index]
                < final_upper.iloc[
                    previous_index
                ]
                or result["close"].iloc[
                    previous_index
                ]
                > final_upper.iloc[
                    previous_index
                ]
            ):
                final_upper.iloc[index] = (
                    upper_band.iloc[index]
                )
            else:
                final_upper.iloc[index] = (
                    final_upper.iloc[
                        previous_index
                    ]
                )

            if (
                lower_band.iloc[index]
                > final_lower.iloc[
                    previous_index
                ]
                or result["close"].iloc[
                    previous_index
                ]
                < final_lower.iloc[
                    previous_index
                ]
            ):
                final_lower.iloc[index] = (
                    lower_band.iloc[index]
                )
            else:
                final_lower.iloc[index] = (
                    final_lower.iloc[
                        previous_index
                    ]
                )

            previous_supertrend = (
                supertrend.iloc[
                    previous_index
                ]
            )

            if pd.isna(previous_supertrend):
                previous_supertrend = (
                    final_lower.iloc[
                        previous_index
                    ]
                )

            if (
                previous_supertrend
                == final_upper.iloc[
                    previous_index
                ]
            ):
                if (
                    result["close"].iloc[
                        index
                    ]
                    <= final_upper.iloc[
                        index
                    ]
                ):
                    supertrend.iloc[index] = (
                        final_upper.iloc[
                            index
                        ]
                    )
                    direction.iloc[index] = -1
                else:
                    supertrend.iloc[index] = (
                        final_lower.iloc[
                            index
                        ]
                    )
                    direction.iloc[index] = 1
            else:
                if (
                    result["close"].iloc[
                        index
                    ]
                    >= final_lower.iloc[
                        index
                    ]
                ):
                    supertrend.iloc[index] = (
                        final_lower.iloc[
                            index
                        ]
                    )
                    direction.iloc[index] = 1
                else:
                    supertrend.iloc[index] = (
                        final_upper.iloc[
                            index
                        ]
                    )
                    direction.iloc[index] = -1

        result["supertrend"] = (
            supertrend.bfill()
        )
        result["supertrend_direction"] = (
            direction
        )

        return result

    @staticmethod
    def _support_resistance(
        dataframe: pd.DataFrame,
        lookback: int = 50,
    ) -> tuple[float, float]:
        recent = dataframe.tail(
            max(20, lookback)
        )

        support = float(
            recent["low"]
            .rolling(
                window=min(
                    20,
                    len(recent),
                )
            )
            .min()
            .iloc[-1]
        )

        resistance_series = (
            recent["high"]
            .shift(1)
            .rolling(
                window=min(
                    20,
                    len(recent) - 1,
                )
            )
            .max()
        )

        resistance = safe_float(
            resistance_series.iloc[-1]
        )

        if resistance is None:
            resistance = float(
                recent["high"]
                .iloc[:-1]
                .max()
            )

        return support, resistance

    @staticmethod
    def _relative_strength_score(
        stock_dataframe: pd.DataFrame,
        benchmark_candles: (
            Iterable[dict[str, Any]]
            | None
        ),
    ) -> tuple[
        bool,
        float,
        dict[str, Any],
        str,
    ]:
        if benchmark_candles is None:
            return (
                False,
                0.0,
                {},
                (
                    "Verified Nifty benchmark "
                    "history is unavailable."
                ),
            )

        benchmark_rows: list[
            dict[str, float]
        ] = []

        for candle in benchmark_candles:
            if not isinstance(candle, dict):
                continue

            close = safe_float(
                candle.get("close")
            )

            if close is None or close <= 0:
                continue

            benchmark_rows.append(
                {"close": close}
            )

        benchmark_dataframe = (
            pd.DataFrame(
                benchmark_rows
            )
        )

        if len(benchmark_dataframe) < 60:
            return (
                False,
                0.0,
                {},
                (
                    "Insufficient Nifty "
                    "benchmark history."
                ),
            )

        periods = [
            period
            for period in (
                20,
                60,
                120,
            )
            if (
                len(stock_dataframe)
                > period
                and len(
                    benchmark_dataframe
                )
                > period
            )
        ]

        if not periods:
            return (
                False,
                0.0,
                {},
                "Relative strength unavailable.",
            )

        outperformance_values: list[
            float
        ] = []

        details: dict[str, Any] = {}

        for period in periods:
            stock_return = (
                (
                    stock_dataframe[
                        "close"
                    ].iloc[-1]
                    / stock_dataframe[
                        "close"
                    ].iloc[
                        -period
                    ]
                )
                - 1
            ) * 100

            benchmark_return = (
                (
                    benchmark_dataframe[
                        "close"
                    ].iloc[-1]
                    / benchmark_dataframe[
                        "close"
                    ].iloc[
                        -period
                    ]
                )
                - 1
            ) * 100

            outperformance = (
                stock_return
                - benchmark_return
            )

            outperformance_values.append(
                outperformance
            )

            details[
                f"{period}_day_stock_return"
            ] = round(stock_return, 2)

            details[
                f"{period}_day_nifty_return"
            ] = round(
                benchmark_return,
                2,
            )

            details[
                f"{period}_day_outperformance"
            ] = round(
                outperformance,
                2,
            )

        average_outperformance = float(
            np.mean(
                outperformance_values
            )
        )

        passed = (
            average_outperformance > 0
        )

        score = max(
            0.0,
            min(
                100.0,
                50
                + average_outperformance
                * 5,
            ),
        )

        reason = (
            (
                "Stock is outperforming "
                "Nifty."
            )
            if passed
            else (
                "Stock is not outperforming "
                "Nifty."
            )
        )

        return (
            passed,
            score,
            details,
            reason,
        )

    def _build_filter(
        self,
        *,
        name: str,
        passed: bool,
        score: float,
        weight: float,
        value: Any,
        reason: str,
    ) -> TechnicalFilterResult:
        return TechnicalFilterResult(
            name=name,
            label=self.FILTER_LABELS[
                name
            ],
            passed=passed,
            score=normalize_score(
                score
            ),
            weight=weight,
            value=value,
            reason=reason,
        )

    def scan(
        self,
        symbol: str,
        candles: Iterable[
            dict[str, Any]
        ],
        *,
        timeframe: str = "3_month",
        benchmark_candles: (
            Iterable[dict[str, Any]]
            | None
        ) = None,
    ) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(
            symbol
        )

        normalized_timeframe = (
            normalize_timeframe(
                timeframe
            )
        )

        if not normalized_symbol:
            raise ValueError(
                "A valid stock symbol is required."
            )

        try:
            dataframe = self._build_dataframe(
                candles
            )

            dataframe["ema20"] = self._ema(
                dataframe["close"],
                20,
            )
            dataframe["ema50"] = self._ema(
                dataframe["close"],
                50,
            )
            dataframe["ema200"] = self._ema(
                dataframe["close"],
                200,
            )

            dataframe["rsi"] = self._rsi(
                dataframe["close"]
            )

            (
                dataframe["macd"],
                dataframe[
                    "macd_signal"
                ],
                dataframe[
                    "macd_histogram"
                ],
            ) = self._macd(
                dataframe["close"]
            )

            (
                dataframe["adx"],
                dataframe["plus_di"],
                dataframe["minus_di"],
            ) = self._adx(dataframe)

            dataframe = self._supertrend(
                dataframe
            )

            dataframe[
                "volume_average_20"
            ] = (
                dataframe["volume"]
                .rolling(20)
                .mean()
            )

            latest = dataframe.iloc[-1]
            previous = dataframe.iloc[-2]

            current_price = float(
                latest["close"]
            )

            support, resistance = (
                self._support_resistance(
                    dataframe
                )
            )

            weights = (
                self.TIMEFRAME_WEIGHTS[
                    normalized_timeframe
                ]
            )

            filter_results: list[
                TechnicalFilterResult
            ] = []

            ema20_passed = (
                current_price
                > float(
                    latest["ema20"]
                )
                and latest["ema20"]
                >= previous["ema20"]
            )

            filter_results.append(
                self._build_filter(
                    name="EMA20",
                    passed=ema20_passed,
                    score=(
                        100
                        if ema20_passed
                        else 20
                    ),
                    weight=weights["EMA20"],
                    value=round(
                        float(
                            latest["ema20"]
                        ),
                        2,
                    ),
                    reason=(
                        "Price is above rising EMA 20."
                        if ema20_passed
                        else (
                            "Price is below or EMA 20 "
                            "is not rising."
                        )
                    ),
                )
            )

            ema50_passed = (
                current_price
                > float(
                    latest["ema50"]
                )
                and latest["ema20"]
                > latest["ema50"]
            )

            filter_results.append(
                self._build_filter(
                    name="EMA50",
                    passed=ema50_passed,
                    score=(
                        100
                        if ema50_passed
                        else 20
                    ),
                    weight=weights["EMA50"],
                    value=round(
                        float(
                            latest["ema50"]
                        ),
                        2,
                    ),
                    reason=(
                        (
                            "Price is above EMA 50 "
                            "and EMA 20 is above EMA 50."
                        )
                        if ema50_passed
                        else (
                            "EMA 20/50 bullish "
                            "alignment is absent."
                        )
                    ),
                )
            )

            ema200_passed = (
                current_price
                > float(
                    latest["ema200"]
                )
                and latest["ema50"]
                > latest["ema200"]
            )

            filter_results.append(
                self._build_filter(
                    name="EMA200",
                    passed=ema200_passed,
                    score=(
                        100
                        if ema200_passed
                        else 10
                    ),
                    weight=weights["EMA200"],
                    value=round(
                        float(
                            latest["ema200"]
                        ),
                        2,
                    ),
                    reason=(
                        (
                            "Price and EMA 50 are "
                            "above EMA 200."
                        )
                        if ema200_passed
                        else (
                            "Long-term EMA alignment "
                            "is not bullish."
                        )
                    ),
                )
            )

            rsi_value = float(
                latest["rsi"]
            )

            rsi_passed = (
                52 <= rsi_value <= 72
            )

            if 58 <= rsi_value <= 68:
                rsi_score = 100
            elif rsi_passed:
                rsi_score = 82
            elif 45 <= rsi_value < 52:
                rsi_score = 45
            else:
                rsi_score = 15

            filter_results.append(
                self._build_filter(
                    name="RSI",
                    passed=rsi_passed,
                    score=rsi_score,
                    weight=weights["RSI"],
                    value=round(
                        rsi_value,
                        2,
                    ),
                    reason=(
                        "RSI is in a healthy bullish zone."
                        if rsi_passed
                        else (
                            "RSI is weak or excessively "
                            "overbought."
                        )
                    ),
                )
            )

            macd_value = float(
                latest["macd"]
            )
            macd_signal_value = float(
                latest["macd_signal"]
            )
            macd_histogram = float(
                latest[
                    "macd_histogram"
                ]
            )

            macd_passed = (
                macd_value
                > macd_signal_value
                and macd_histogram > 0
                and macd_histogram
                >= float(
                    previous[
                        "macd_histogram"
                    ]
                )
            )

            filter_results.append(
                self._build_filter(
                    name="MACD",
                    passed=macd_passed,
                    score=(
                        100
                        if macd_passed
                        else 25
                    ),
                    weight=weights["MACD"],
                    value={
                        "macd": round(
                            macd_value,
                            3,
                        ),
                        "signal": round(
                            macd_signal_value,
                            3,
                        ),
                        "histogram": round(
                            macd_histogram,
                            3,
                        ),
                    },
                    reason=(
                        (
                            "MACD is above signal line "
                            "with positive momentum."
                        )
                        if macd_passed
                        else (
                            "MACD bullish confirmation "
                            "is absent."
                        )
                    ),
                )
            )

            supertrend_value = float(
                latest["supertrend"]
            )

            supertrend_passed = (
                int(
                    latest[
                        "supertrend_direction"
                    ]
                )
                == 1
                and current_price
                > supertrend_value
            )

            filter_results.append(
                self._build_filter(
                    name="SUPERTREND",
                    passed=supertrend_passed,
                    score=(
                        100
                        if supertrend_passed
                        else 15
                    ),
                    weight=weights[
                        "SUPERTREND"
                    ],
                    value=round(
                        supertrend_value,
                        2,
                    ),
                    reason=(
                        "Supertrend is bullish."
                        if supertrend_passed
                        else (
                            "Supertrend is not bullish."
                        )
                    ),
                )
            )

            adx_value = float(
                latest["adx"]
            )
            plus_di = float(
                latest["plus_di"]
            )
            minus_di = float(
                latest["minus_di"]
            )

            adx_passed = (
                adx_value >= 20
                and plus_di > minus_di
            )

            adx_score = max(
                0.0,
                min(
                    100.0,
                    (
                        adx_value * 2.5
                        if plus_di > minus_di
                        else adx_value
                    ),
                ),
            )

            filter_results.append(
                self._build_filter(
                    name="ADX",
                    passed=adx_passed,
                    score=adx_score,
                    weight=weights["ADX"],
                    value={
                        "adx": round(
                            adx_value,
                            2,
                        ),
                        "plus_di": round(
                            plus_di,
                            2,
                        ),
                        "minus_di": round(
                            minus_di,
                            2,
                        ),
                    },
                    reason=(
                        (
                            "ADX confirms a strong "
                            "bullish trend."
                        )
                        if adx_passed
                        else (
                            "Trend strength is weak "
                            "or bearish."
                        )
                    ),
                )
            )

            current_volume = float(
                latest["volume"]
            )

            average_volume = safe_float(
                latest[
                    "volume_average_20"
                ],
                default=0.0,
            ) or 0.0

            volume_ratio = (
                current_volume
                / average_volume
                if average_volume > 0
                else 0.0
            )

            volume_passed = (
                volume_ratio >= 1.5
                and current_price
                >= float(
                    previous["close"]
                )
            )

            volume_score = max(
                0.0,
                min(
                    100.0,
                    volume_ratio * 50,
                ),
            )

            filter_results.append(
                self._build_filter(
                    name="VOLUME_BREAKOUT",
                    passed=volume_passed,
                    score=volume_score,
                    weight=weights[
                        "VOLUME_BREAKOUT"
                    ],
                    value={
                        "current_volume": (
                            current_volume
                        ),
                        "average_volume_20": (
                            round(
                                average_volume,
                                2,
                            )
                        ),
                        "volume_ratio": round(
                            volume_ratio,
                            2,
                        ),
                    },
                    reason=(
                        (
                            "Volume is at least 1.5x "
                            "the 20-day average."
                        )
                        if volume_passed
                        else (
                            "Volume breakout is "
                            "not confirmed."
                        )
                    ),
                )
            )

            breakout_margin = (
                (
                    current_price
                    - resistance
                )
                / resistance
                * 100
                if resistance > 0
                else 0.0
            )

            resistance_passed = (
                current_price
                > resistance
                and breakout_margin
                <= 8.0
            )

            breakout_score = max(
                0.0,
                min(
                    100.0,
                    70
                    + breakout_margin
                    * 5,
                ),
            )

            if not resistance_passed:
                breakout_score = 25.0

            filter_results.append(
                self._build_filter(
                    name=(
                        "SUPPORT_RESISTANCE"
                    ),
                    passed=(
                        resistance_passed
                    ),
                    score=breakout_score,
                    weight=weights[
                        "SUPPORT_RESISTANCE"
                    ],
                    value={
                        "support": round(
                            support,
                            2,
                        ),
                        "resistance": round(
                            resistance,
                            2,
                        ),
                        "breakout_percent": (
                            round(
                                breakout_margin,
                                2,
                            )
                        ),
                    },
                    reason=(
                        (
                            "Price has closed above "
                            "recent resistance."
                        )
                        if resistance_passed
                        else (
                            "Resistance breakout "
                            "is not confirmed."
                        )
                    ),
                )
            )

            (
                relative_passed,
                relative_score,
                relative_details,
                relative_reason,
            ) = (
                self._relative_strength_score(
                    dataframe,
                    benchmark_candles,
                )
            )

            filter_results.append(
                self._build_filter(
                    name=(
                        "RELATIVE_STRENGTH"
                    ),
                    passed=relative_passed,
                    score=relative_score,
                    weight=weights[
                        "RELATIVE_STRENGTH"
                    ],
                    value=relative_details,
                    reason=relative_reason,
                )
            )

            total_weight = sum(
                item.weight
                for item in filter_results
            )

            weighted_score = (
                sum(
                    item.score
                    * item.weight
                    for item in filter_results
                )
                / total_weight
                if total_weight > 0
                else 0.0
            )

            passed_count = sum(
                1
                for item in filter_results
                if item.passed
            )

            bullish = (
                weighted_score
                >= self.MINIMUM_SCORE[
                    normalized_timeframe
                ]
                and passed_count
                >= (
                    self.MINIMUM_PASSED_FILTERS[
                        normalized_timeframe
                    ]
                )
                and ema200_passed
                and (
                    macd_passed
                    or supertrend_passed
                )
            )

            scan_result = (
                TechnicalScanResult(
                    symbol=normalized_symbol,
                    timeframe=(
                        normalized_timeframe
                    ),
                    score=normalize_score(
                        weighted_score
                    ),
                    passed_count=(
                        passed_count
                    ),
                    total_filters=len(
                        filter_results
                    ),
                    bullish=bullish,
                    current_price=(
                        current_price
                    ),
                    filters=filter_results,
                    indicators={
                        "ema20": round(
                            float(
                                latest["ema20"]
                            ),
                            2,
                        ),
                        "ema50": round(
                            float(
                                latest["ema50"]
                            ),
                            2,
                        ),
                        "ema200": round(
                            float(
                                latest[
                                    "ema200"
                                ]
                            ),
                            2,
                        ),
                        "rsi": round(
                            rsi_value,
                            2,
                        ),
                        "macd": round(
                            macd_value,
                            3,
                        ),
                        "macd_signal": round(
                            macd_signal_value,
                            3,
                        ),
                        "adx": round(
                            adx_value,
                            2,
                        ),
                        "supertrend": round(
                            supertrend_value,
                            2,
                        ),
                        "volume_ratio": round(
                            volume_ratio,
                            2,
                        ),
                    },
                    support=support,
                    resistance=(
                        resistance
                    ),
                    generated_at=(
                        utc_now().isoformat()
                    ),
                )
            )

            logger.info(
                (
                    "Technical scan completed "
                    "for %s with score %.2f."
                ),
                normalized_symbol,
                weighted_score,
                extra=build_log_extra(
                    component=(
                        "technical_scanner"
                    ),
                    symbol=normalized_symbol,
                    timeframe=(
                        normalized_timeframe
                    ),
                    event=(
                        "technical_scan_completed"
                    ),
                    status=(
                        "success"
                        if bullish
                        else "rejected"
                    ),
                    passed_count=(
                        passed_count
                    ),
                ),
            )

            return scan_result.to_dict()

        except TechnicalScannerError:
            raise

        except Exception as exception:
            log_exception(
                logger,
                "Technical scan failed",
                exception=exception,
                symbol=normalized_symbol,
                timeframe=(
                    normalized_timeframe
                ),
                component=(
                    "technical_scanner"
                ),
                error_code=(
                    "TECHNICAL_SCAN_FAILED"
                ),
            )

            raise TechnicalScannerError(
                (
                    "Technical analysis failed "
                    f"for {normalized_symbol}."
                )
            ) from exception


_global_technical_scanner: (
    TechnicalScanner | None
) = None


def get_technical_scanner(
) -> TechnicalScanner:
    global _global_technical_scanner

    if _global_technical_scanner is None:
        _global_technical_scanner = (
            TechnicalScanner()
        )

    return _global_technical_scanner
