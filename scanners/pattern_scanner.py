from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd

from utils.helpers import (
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


logger = get_logger("scanners.pattern_scanner")


class PatternScannerError(RuntimeError):
    """Raised when chart-pattern analysis cannot be completed."""


@dataclass
class PatternResult:
    name: str
    label: str
    detected: bool
    confirmed: bool
    score: float
    confidence: float
    breakout_price: float | None = None
    support: float | None = None
    resistance: float | None = None
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "detected": self.detected,
            "confirmed": self.confirmed,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 2),
            "breakout_price": (
                round(self.breakout_price, 2)
                if self.breakout_price is not None
                else None
            ),
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
            "reason": self.reason,
            "details": self.details,
        }


@dataclass
class PatternScanResult:
    symbol: str
    timeframe: str
    score: float
    detected_count: int
    confirmed_count: int
    bullish_pattern: bool
    strongest_pattern: str | None
    patterns: list[PatternResult] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "score": round(self.score, 2),
            "detected_count": self.detected_count,
            "confirmed_count": self.confirmed_count,
            "bullish_pattern": self.bullish_pattern,
            "strongest_pattern": self.strongest_pattern,
            "patterns": [
                pattern.to_dict()
                for pattern in self.patterns
            ],
            "generated_at": self.generated_at,
        }


class PatternScanner:
    """
    Detects only the selected top-10 commonly used bullish chart patterns.

    Patterns:
    1. Cup and Handle
    2. Ascending Triangle
    3. Symmetrical Triangle Breakout
    4. Flag and Pole
    5. Double Bottom
    6. Inverse Head and Shoulders
    7. Falling Wedge Breakout
    8. Rectangle Breakout
    9. Rounded Bottom
    10. Consolidation Breakout

    A pattern is considered confirmed only when price, close and
    volume conditions support the breakout.
    """

    PATTERN_LABELS = {
        "CUP_HANDLE": "Cup and Handle",
        "ASCENDING_TRIANGLE": "Ascending Triangle",
        "SYMMETRICAL_TRIANGLE": "Symmetrical Triangle",
        "FLAG": "Flag and Pole",
        "DOUBLE_BOTTOM": "Double Bottom",
        "INVERSE_HEAD_SHOULDER": "Inverse Head and Shoulders",
        "FALLING_WEDGE": "Falling Wedge",
        "RECTANGLE_BREAKOUT": "Rectangle Breakout",
        "ROUNDED_BOTTOM": "Rounded Bottom",
        "CONSOLIDATION_BREAKOUT": "Consolidation Breakout",
    }

    TIMEFRAME_LOOKBACK = {
        "15_30_days": 90,
        "3_month": 140,
        "6_month": 220,
        "1_year": 320,
        "3_year": 500,
    }

    MINIMUM_PATTERN_SCORE = {
        "15_30_days": 70.0,
        "3_month": 70.0,
        "6_month": 68.0,
        "1_year": 65.0,
        "3_year": 62.0,
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
                "timestamp": (
                    candle.get("timestamp")
                    or candle.get("date")
                ),
                "open": safe_float(candle.get("open")),
                "high": safe_float(candle.get("high")),
                "low": safe_float(candle.get("low")),
                "close": safe_float(candle.get("close")),
                "volume": safe_float(
                    candle.get("volume"),
                    default=0.0,
                ),
            }

            if any(
                row[key] is None
                for key in (
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                )
            ):
                continue

            rows.append(row)

        dataframe = pd.DataFrame(rows)

        if dataframe.empty:
            raise PatternScannerError(
                "Historical candle data is unavailable."
            )

        dataframe = dataframe.drop_duplicates(
            subset=["timestamp"],
            keep="last",
        )

        dataframe = dataframe.sort_values(
            "timestamp"
        ).reset_index(drop=True)

        if len(dataframe) < 80:
            raise PatternScannerError(
                "At least 80 valid candles are required."
            )

        dataframe["volume_average_20"] = (
            dataframe["volume"]
            .rolling(20)
            .mean()
        )

        return dataframe

    @staticmethod
    def _percentage_difference(
        first: float,
        second: float,
    ) -> float:
        average_value = (
            abs(first) + abs(second)
        ) / 2

        if average_value <= 0:
            return 0.0

        return (
            abs(first - second)
            / average_value
            * 100
        )

    @staticmethod
    def _linear_slope(
        values: pd.Series,
    ) -> float:
        clean_values = values.dropna()

        if len(clean_values) < 3:
            return 0.0

        x_values = np.arange(
            len(clean_values)
        )

        slope, _ = np.polyfit(
            x_values,
            clean_values.to_numpy(),
            1,
        )

        return float(slope)

    @staticmethod
    def _volume_confirmation(
        dataframe: pd.DataFrame,
        multiplier: float = 1.3,
    ) -> tuple[bool, float]:
        latest_volume = safe_float(
            dataframe["volume"].iloc[-1],
            default=0.0,
        ) or 0.0

        average_volume = safe_float(
            dataframe["volume_average_20"].iloc[-1],
            default=0.0,
        ) or 0.0

        ratio = (
            latest_volume / average_volume
            if average_volume > 0
            else 0.0
        )

        return ratio >= multiplier, ratio

    def _create_result(
        self,
        *,
        name: str,
        detected: bool,
        confirmed: bool,
        score: float,
        confidence: float,
        breakout_price: float | None = None,
        support: float | None = None,
        resistance: float | None = None,
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> PatternResult:
        return PatternResult(
            name=name,
            label=self.PATTERN_LABELS[name],
            detected=detected,
            confirmed=confirmed,
            score=normalize_score(score),
            confidence=normalize_score(confidence),
            breakout_price=breakout_price,
            support=support,
            resistance=resistance,
            reason=reason,
            details=details or {},
        )

    def _detect_double_bottom(
        self,
        dataframe: pd.DataFrame,
    ) -> PatternResult:
        recent = dataframe.tail(100).copy()

        rolling_low = (
            recent["low"]
            .rolling(5, center=True)
            .min()
        )

        bottom_points = recent[
            recent["low"] == rolling_low
        ]

        if len(bottom_points) < 2:
            return self._create_result(
                name="DOUBLE_BOTTOM",
                detected=False,
                confirmed=False,
                score=0,
                confidence=0,
                reason="Two valid bottoms were not found.",
            )

        first_bottom = bottom_points.iloc[-2]
        second_bottom = bottom_points.iloc[-1]

        first_index = bottom_points.index[-2]
        second_index = bottom_points.index[-1]

        distance = second_index - first_index

        similarity = self._percentage_difference(
            float(first_bottom["low"]),
            float(second_bottom["low"]),
        )

        if distance < 10 or similarity > 5:
            return self._create_result(
                name="DOUBLE_BOTTOM",
                detected=False,
                confirmed=False,
                score=20,
                confidence=20,
                reason="Bottom spacing or price similarity is weak.",
            )

        middle_slice = recent.loc[
            first_index:second_index
        ]

        neckline = float(
            middle_slice["high"].max()
        )

        current_price = float(
            recent["close"].iloc[-1]
        )

        volume_confirmed, volume_ratio = (
            self._volume_confirmation(recent)
        )

        detected = similarity <= 5
        confirmed = (
            detected
            and current_price > neckline
            and volume_confirmed
        )

        score = (
            90
            if confirmed
            else 65
            if detected
            else 20
        )

        return self._create_result(
            name="DOUBLE_BOTTOM",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=neckline,
            support=min(
                float(first_bottom["low"]),
                float(second_bottom["low"]),
            ),
            resistance=neckline,
            reason=(
                "Double bottom breakout confirmed."
                if confirmed
                else (
                    "Double bottom detected but breakout "
                    "or volume confirmation is pending."
                )
            ),
            details={
                "bottom_similarity_percent": round(
                    similarity,
                    2,
                ),
                "bottom_distance_candles": int(
                    distance
                ),
                "volume_ratio": round(
                    volume_ratio,
                    2,
                ),
            },
        )

    def _detect_ascending_triangle(
        self,
        dataframe: pd.DataFrame,
    ) -> PatternResult:
        recent = dataframe.tail(70).copy()

        first_half = recent.iloc[
            : len(recent) // 2
        ]
        second_half = recent.iloc[
            len(recent) // 2 :
        ]

        resistance_one = float(
            first_half["high"].quantile(0.9)
        )

        resistance_two = float(
            second_half["high"].quantile(0.9)
        )

        resistance_difference = (
            self._percentage_difference(
                resistance_one,
                resistance_two,
            )
        )

        low_slope = self._linear_slope(
            recent["low"]
        )

        resistance = (
            resistance_one
            + resistance_two
        ) / 2

        current_price = float(
            recent["close"].iloc[-1]
        )

        volume_confirmed, volume_ratio = (
            self._volume_confirmation(recent)
        )

        detected = (
            resistance_difference <= 3
            and low_slope > 0
        )

        confirmed = (
            detected
            and current_price > resistance
            and volume_confirmed
        )

        score = (
            92
            if confirmed
            else 68
            if detected
            else 15
        )

        return self._create_result(
            name="ASCENDING_TRIANGLE",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=float(
                recent["low"].tail(20).min()
            ),
            resistance=resistance,
            reason=(
                "Ascending triangle breakout confirmed."
                if confirmed
                else (
                    "Ascending triangle is forming but "
                    "breakout confirmation is pending."
                    if detected
                    else "Ascending triangle was not detected."
                )
            ),
            details={
                "resistance_difference_percent": round(
                    resistance_difference,
                    2,
                ),
                "low_slope": round(
                    low_slope,
                    4,
                ),
                "volume_ratio": round(
                    volume_ratio,
                    2,
                ),
            },
        )

    def _detect_symmetrical_triangle(
        self,
        dataframe: pd.DataFrame,
    ) -> PatternResult:
        recent = dataframe.tail(60).copy()

        high_slope = self._linear_slope(
            recent["high"]
        )

        low_slope = self._linear_slope(
            recent["low"]
        )

        current_price = float(
            recent["close"].iloc[-1]
        )

        recent_resistance = float(
            recent["high"]
            .iloc[:-1]
            .tail(15)
            .max()
        )

        volume_confirmed, volume_ratio = (
            self._volume_confirmation(recent)
        )

        detected = (
            high_slope < 0
            and low_slope > 0
        )

        confirmed = (
            detected
            and current_price > recent_resistance
            and volume_confirmed
        )

        score = (
            88
            if confirmed
            else 63
            if detected
            else 10
        )

        return self._create_result(
            name="SYMMETRICAL_TRIANGLE",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=recent_resistance,
            support=float(
                recent["low"].tail(15).min()
            ),
            resistance=recent_resistance,
            reason=(
                "Symmetrical triangle breakout confirmed."
                if confirmed
                else (
                    "Triangle contraction detected but "
                    "breakout is pending."
                    if detected
                    else "Symmetrical triangle was not detected."
                )
            ),
            details={
                "high_slope": round(
                    high_slope,
                    4,
                ),
                "low_slope": round(
                    low_slope,
                    4,
                ),
                "volume_ratio": round(
                    volume_ratio,
                    2,
                ),
            },
        )

    def _detect_flag(
        self,
        dataframe: pd.DataFrame,
    ) -> PatternResult:
        recent = dataframe.tail(50).copy()

        pole = recent.iloc[:20]
        flag = recent.iloc[20:]

        pole_start = float(
            pole["close"].iloc[0]
        )

        pole_end = float(
            pole["close"].iloc[-1]
        )

        pole_gain = (
            (pole_end - pole_start)
            / pole_start
            * 100
        )

        flag_high_slope = self._linear_slope(
            flag["high"]
        )

        flag_low_slope = self._linear_slope(
            flag["low"]
        )

        flag_resistance = float(
            flag["high"]
            .iloc[:-1]
            .max()
        )

        current_price = float(
            flag["close"].iloc[-1]
        )

        volume_confirmed, volume_ratio = (
            self._volume_confirmation(recent)
        )

        detected = (
            pole_gain >= 10
            and flag_high_slope <= 0
            and flag_low_slope <= 0
        )

        confirmed = (
            detected
            and current_price > flag_resistance
            and volume_confirmed
        )

        score = (
            90
            if confirmed
            else 66
            if detected
            else 10
        )

        return self._create_result(
            name="FLAG",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=flag_resistance,
            support=float(
                flag["low"].min()
            ),
            resistance=flag_resistance,
            reason=(
                "Flag and pole breakout confirmed."
                if confirmed
                else (
                    "Bullish flag detected but breakout "
                    "confirmation is pending."
                    if detected
                    else "Flag and pole was not detected."
                )
            ),
            details={
                "pole_gain_percent": round(
                    pole_gain,
                    2,
                ),
                "flag_high_slope": round(
                    flag_high_slope,
                    4,
                ),
                "flag_low_slope": round(
                    flag_low_slope,
                    4,
                ),
                "volume_ratio": round(
                    volume_ratio,
                    2,
                ),
            },
        )

    def _detect_falling_wedge(
        self,
        dataframe: pd.DataFrame,
    ) -> PatternResult:
        recent = dataframe.tail(70).copy()

        high_slope = self._linear_slope(
            recent["high"]
        )

        low_slope = self._linear_slope(
            recent["low"]
        )

        current_price = float(
            recent["close"].iloc[-1]
        )

        resistance = float(
            recent["high"]
            .iloc[:-1]
            .tail(15)
            .max()
        )

        volume_confirmed, volume_ratio = (
            self._volume_confirmation(recent)
        )

        detected = (
            high_slope < 0
            and low_slope < 0
            and high_slope < low_slope
        )

        confirmed = (
            detected
            and current_price > resistance
            and volume_confirmed
        )

        score = (
            88
            if confirmed
            else 62
            if detected
            else 10
        )

        return self._create_result(
            name="FALLING_WEDGE",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=float(
                recent["low"].tail(20).min()
            ),
            resistance=resistance,
            reason=(
                "Falling wedge breakout confirmed."
                if confirmed
                else (
                    "Falling wedge detected but breakout "
                    "confirmation is pending."
                    if detected
                    else "Falling wedge was not detected."
                )
            ),
            details={
                "high_slope": round(
                    high_slope,
                    4,
                ),
                "low_slope": round(
                    low_slope,
                    4,
                ),
                "volume_ratio": round(
                    volume_ratio,
                    2,
                ),
            },
        )

    def _detect_rectangle(
        self,
        dataframe: pd.DataFrame,
    ) -> PatternResult:
        recent = dataframe.tail(50).copy()

        resistance = float(
            recent["high"]
            .iloc[:-1]
            .quantile(0.9)
        )

        support = float(
            recent["low"]
            .iloc[:-1]
            .quantile(0.1)
        )

        range_percent = (
            (resistance - support)
            / support
            * 100
            if support > 0
            else 100
        )

        high_slope = abs(
            self._linear_slope(
                recent["high"].iloc[:-1]
            )
        )

        low_slope = abs(
            self._linear_slope(
                recent["low"].iloc[:-1]
            )
        )

        current_price = float(
            recent["close"].iloc[-1]
        )

        volume_confirmed, volume_ratio = (
            self._volume_confirmation(recent)
        )

        detected = (
            range_percent <= 15
            and high_slope
            <= resistance * 0.002
            and low_slope
            <= support * 0.002
        )

        confirmed = (
            detected
            and current_price > resistance
            and volume_confirmed
        )

        score = (
            90
            if confirmed
            else 65
            if detected
            else 12
        )

        return self._create_result(
            name="RECTANGLE_BREAKOUT",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=support,
            resistance=resistance,
            reason=(
                "Rectangle breakout confirmed."
                if confirmed
                else (
                    "Rectangle consolidation detected "
                    "but breakout is pending."
                    if detected
                    else "Rectangle pattern was not detected."
                )
            ),
            details={
                "range_percent": round(
                    range_percent,
                    2,
                ),
                "volume_ratio": round(
                    volume_ratio,
                    2,
                ),
            },
        )

    def _detect_consolidation(
        self,
        dataframe: pd.DataFrame,
    ) -> PatternResult:
        recent = dataframe.tail(30).copy()

        resistance = float(
            recent["high"]
            .iloc[:-1]
            .max()
        )

        support = float(
            recent["low"]
            .iloc[:-1]
            .min()
        )

        range_percent = (
            (resistance - support)
            / support
            * 100
            if support > 0
            else 100
        )

        current_price = float(
            recent["close"].iloc[-1]
        )

        volume_confirmed, volume_ratio = (
            self._volume_confirmation(recent)
        )

        detected = range_percent <= 10

        confirmed = (
            detected
            and current_price > resistance
            and volume_confirmed
        )

        score = (
            88
            if confirmed
            else 60
            if detected
            else 10
        )

        return self._create_result(
            name="CONSOLIDATION_BREAKOUT",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=support,
            resistance=resistance,
            reason=(
                "Consolidation breakout confirmed."
                if confirmed
                else (
                    "Tight consolidation detected but "
                    "breakout is pending."
                    if detected
                    else "Tight consolidation was not detected."
                )
            ),
            details={
                "range_percent": round(
                    range_percent,
                    2,
                ),
                "volume_ratio": round(
                    volume_ratio,
                    2,
                ),
            },
        )

    def _detect_rounded_bottom(
        self,
        dataframe: pd.DataFrame,
    ) -> PatternResult:
        recent = dataframe.tail(120).copy()

        thirds = np.array_split(
            recent["close"].to_numpy(),
            3,
        )

        first_average = float(
            np.mean(thirds[0])
        )
        middle_average = float(
            np.mean(thirds[1])
        )
        last_average = float(
            np.mean(thirds[2])
        )

        resistance = float(
            recent["high"]
            .iloc[:-1]
            .tail(30)
            .max()
        )

        current_price = float(
            recent["close"].iloc[-1]
        )

        volume_confirmed, volume_ratio = (
            self._volume_confirmation(recent)
        )

        detected = (
            middle_average < first_average
            and middle_average < last_average
            and last_average >= first_average * 0.95
        )

        confirmed = (
            detected
            and current_price > resistance
            and volume_confirmed
        )

        score = (
            85
            if confirmed
            else 60
            if detected
            else 10
        )

        return self._create_result(
            name="ROUNDED_BOTTOM",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=float(
                recent["low"].min()
            ),
            resistance=resistance,
            reason=(
                "Rounded bottom breakout confirmed."
                if confirmed
                else (
                    "Rounded bottom structure detected "
                    "but breakout is pending."
                    if detected
                    else "Rounded bottom was not detected."
                )
            ),
            details={
                "first_average": round(
                    first_average,
                    2,
                ),
                "middle_average": round(
                    middle_average,
                    2,
                ),
                "last_average": round(
                    last_average,
                    2,
                ),
                "volume_ratio": round(
                    volume_ratio,
                    2,
                ),
            },
        )

    def _detect_cup_handle(
        self,
        dataframe: pd.DataFrame,
    ) -> PatternResult:
        recent = dataframe.tail(140).copy()

        cup = recent.iloc[:-25]
        handle = recent.iloc[-25:]

        if len(cup) < 60:
            return self._create_result(
                name="CUP_HANDLE",
                detected=False,
                confirmed=False,
                score=0,
                confidence=0,
                reason="Insufficient history for cup and handle.",
            )

        left_rim = float(
            cup["high"].iloc[:20].max()
        )

        right_rim = float(
            cup["high"].iloc[-20:].max()
        )

        cup_bottom = float(
            cup["low"].min()
        )

        rim_similarity = (
            self._percentage_difference(
                left_rim,
                right_rim,
            )
        )

        cup_depth = (
            (min(left_rim, right_rim) - cup_bottom)
            / min(left_rim, right_rim)
            * 100
        )

        handle_depth = (
            (right_rim - float(handle["low"].min()))
            / right_rim
            * 100
        )

        resistance = max(
            left_rim,
            right_rim,
        )

        current_price = float(
            handle["close"].iloc[-1]
        )

        volume_confirmed, volume_ratio = (
            self._volume_confirmation(recent)
        )

        detected = (
            rim_similarity <= 8
            and 10 <= cup_depth <= 40
            and handle_depth <= 15
        )

        confirmed = (
            detected
            and current_price > resistance
            and volume_confirmed
        )

        score = (
            94
            if confirmed
            else 70
            if detected
            else 15
        )

        return self._create_result(
            name="CUP_HANDLE",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=float(
                handle["low"].min()
            ),
            resistance=resistance,
            reason=(
                "Cup and handle breakout confirmed."
                if confirmed
                else (
                    "Cup and handle detected but breakout "
                    "confirmation is pending."
                    if detected
                    else "Cup and handle was not detected."
                )
            ),
            details={
                "rim_similarity_percent": round(
                    rim_similarity,
                    2,
                ),
                "cup_depth_percent": round(
                    cup_depth,
                    2,
                ),
                "handle_depth_percent": round(
                    handle_depth,
                    2,
                ),
                "volume_ratio": round(
                    volume_ratio,
                    2,
                ),
            },
        )

    def _detect_inverse_head_shoulders(
        self,
        dataframe: pd.DataFrame,
    ) -> PatternResult:
        recent = dataframe.tail(120).copy()

        segments = np.array_split(
            recent,
            5,
        )

        if len(segments) < 5:
            return self._create_result(
                name="INVERSE_HEAD_SHOULDER",
                detected=False,
                confirmed=False,
                score=0,
                confidence=0,
                reason="Insufficient history.",
            )

        left_shoulder = float(
            segments[1]["low"].min()
        )

        head = float(
            segments[2]["low"].min()
        )

        right_shoulder = float(
            segments[3]["low"].min()
        )

        shoulder_similarity = (
            self._percentage_difference(
                left_shoulder,
                right_shoulder,
            )
        )

        neckline = max(
            float(segments[1]["high"].max()),
            float(segments[3]["high"].max()),
        )

        current_price = float(
            recent["close"].iloc[-1]
        )

        volume_confirmed, volume_ratio = (
            self._volume_confirmation(recent)
        )

        detected = (
            head < left_shoulder
            and head < right_shoulder
            and shoulder_similarity <= 8
        )

        confirmed = (
            detected
            and current_price > neckline
            and volume_confirmed
        )

        score = (
            92
            if confirmed
            else 68
            if detected
            else 10
        )

        return self._create_result(
            name="INVERSE_HEAD_SHOULDER",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=neckline,
            support=head,
            resistance=neckline,
            reason=(
                "Inverse head and shoulders breakout confirmed."
                if confirmed
                else (
                    "Inverse head and shoulders detected "
                    "but breakout is pending."
                    if detected
                    else (
                        "Inverse head and shoulders "
                        "was not detected."
                    )
                )
            ),
            details={
                "left_shoulder": round(
                    left_shoulder,
                    2,
                ),
                "head": round(
                    head,
                    2,
                ),
                "right_shoulder": round(
                    right_shoulder,
                    2,
                ),
                "shoulder_similarity_percent": round(
                    shoulder_similarity,
                    2,
                ),
                "volume_ratio": round(
                    volume_ratio,
                    2,
                ),
            },
        )

    def scan(
        self,
        symbol: str,
        candles: Iterable[dict[str, Any]],
        *,
        timeframe: str = "3_month",
    ) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(
            symbol
        )

        normalized_timeframe = (
            normalize_timeframe(timeframe)
        )

        if not normalized_symbol:
            raise ValueError(
                "A valid stock symbol is required."
            )

        try:
            dataframe = self._build_dataframe(
                candles
            )

            lookback = self.TIMEFRAME_LOOKBACK[
                normalized_timeframe
            ]

            working_data = dataframe.tail(
                min(
                    lookback,
                    len(dataframe),
                )
            ).copy()

            pattern_results = [
                self._detect_cup_handle(
                    working_data
                ),
                self._detect_ascending_triangle(
                    working_data
                ),
                self._detect_symmetrical_triangle(
                    working_data
                ),
                self._detect_flag(
                    working_data
                ),
                self._detect_double_bottom(
                    working_data
                ),
                self._detect_inverse_head_shoulders(
                    working_data
                ),
                self._detect_falling_wedge(
                    working_data
                ),
                self._detect_rectangle(
                    working_data
                ),
                self._detect_rounded_bottom(
                    working_data
                ),
                self._detect_consolidation(
                    working_data
                ),
            ]

            detected_patterns = [
                pattern
                for pattern in pattern_results
                if pattern.detected
            ]

            confirmed_patterns = [
                pattern
                for pattern in pattern_results
                if pattern.confirmed
            ]

            strongest_pattern: (
                PatternResult | None
            ) = None

            if pattern_results:
                strongest_pattern = max(
                    pattern_results,
                    key=lambda item: (
                        item.confirmed,
                        item.score,
                        item.confidence,
                    ),
                )

            if confirmed_patterns:
                pattern_score = max(
                    item.score
                    for item in confirmed_patterns
                )

                if len(confirmed_patterns) > 1:
                    pattern_score = min(
                        100.0,
                        pattern_score
                        + (
                            len(confirmed_patterns)
                            - 1
                        )
                        * 3,
                    )

            elif detected_patterns:
                pattern_score = max(
                    item.score
                    for item in detected_patterns
                )

            else:
                pattern_score = 0.0

            bullish_pattern = (
                bool(confirmed_patterns)
                and pattern_score
                >= self.MINIMUM_PATTERN_SCORE[
                    normalized_timeframe
                ]
            )

            result = PatternScanResult(
                symbol=normalized_symbol,
                timeframe=normalized_timeframe,
                score=normalize_score(
                    pattern_score
                ),
                detected_count=len(
                    detected_patterns
                ),
                confirmed_count=len(
                    confirmed_patterns
                ),
                bullish_pattern=bullish_pattern,
                strongest_pattern=(
                    strongest_pattern.label
                    if (
                        strongest_pattern
                        and strongest_pattern.detected
                    )
                    else None
                ),
                patterns=pattern_results,
                generated_at=utc_now().isoformat(),
            )

            logger.info(
                (
                    "Pattern scan completed for %s "
                    "with %s confirmed pattern(s)."
                ),
                normalized_symbol,
                len(confirmed_patterns),
                extra=build_log_extra(
                    component="pattern_scanner",
                    symbol=normalized_symbol,
                    timeframe=normalized_timeframe,
                    event="pattern_scan_completed",
                    status=(
                        "success"
                        if bullish_pattern
                        else "rejected"
                    ),
                    detected_count=len(
                        detected_patterns
                    ),
                    confirmed_count=len(
                        confirmed_patterns
                    ),
                ),
            )

            return result.to_dict()

        except PatternScannerError:
            raise

        except Exception as exception:
            log_exception(
                logger,
                "Chart-pattern scan failed",
                exception=exception,
                symbol=normalized_symbol,
                timeframe=normalized_timeframe,
                component="pattern_scanner",
                error_code="PATTERN_SCAN_FAILED",
            )

            raise PatternScannerError(
                (
                    "Chart-pattern analysis failed "
                    f"for {normalized_symbol}."
                )
            ) from exception


_global_pattern_scanner: PatternScanner | None = None


def get_pattern_scanner() -> PatternScanner:
    global _global_pattern_scanner

    if _global_pattern_scanner is None:
        _global_pattern_scanner = PatternScanner()

    return _global_pattern_scanner
