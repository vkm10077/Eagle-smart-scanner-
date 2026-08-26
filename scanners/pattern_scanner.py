from __future__ import annotations

"""
Eagle Smart Scanner - Pattern Scanner

Detects bullish chart patterns + bullish candlestick patterns and returns
a normalized PatternConfirmation object consumed by technical_scanner.py.

Chart patterns:
- Ascending Triangle
- Symmetrical Triangle Breakout
- Falling Wedge Breakout
- Bull Flag
- Cup and Handle
- Double Bottom
- Inverse Head and Shoulders
- Rectangle Breakout
- Channel Breakout
- Rounding Bottom

Candlestick patterns:
- Bullish Engulfing
- Hammer
- Morning Star
- Piercing Pattern
- Bullish Harami
- Bullish Marubozu
- Inverted Hammer
- Three White Soldiers
- Tweezer Bottom
- Doji + Bullish Confirmation

Rules
-----
- Pure technical analysis
- No fundamentals
- No NIFTY500 dependency
- No fake/random pattern generation
- Pattern detection is confirmatory; final BUY/STRONG BUY remains controlled
  by TechnicalScanner mandatory conditions and score thresholds.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from config import Config
from scanners.technical_scanner import PatternConfirmation


class PatternScannerError(RuntimeError):
    """Pattern scanner error."""


@dataclass(frozen=True)
class PatternMatch:
    name: str
    detected: bool
    confirmed: bool
    score: float
    confidence: float
    breakout_price: float
    support: float
    resistance: float
    reason: str
    details: dict[str, Any]


@dataclass(frozen=True)
class PatternScanResult:
    mode: str

    chart_patterns: tuple[PatternMatch, ...]
    candlestick_patterns: tuple[PatternMatch, ...]

    best_chart_pattern: str
    best_chart_score: float
    chart_pattern_bullish: bool

    best_candle_pattern: str
    best_candle_score: float
    candle_pattern_bullish: bool

    total_pattern_score: float

    confirmation: PatternConfirmation


class PatternScanner:
    """
    Bullish chart + candlestick pattern engine.
    """

    # ========================================================
    # MAIN
    # ========================================================

    def scan(
        self,
        df: pd.DataFrame,
        *,
        mode: str | None = None,
    ) -> PatternScanResult:
        mode = Config.normalize_trading_mode(mode)

        data = self._prepare_dataframe(df)

        if len(data) < 80:
            raise PatternScannerError(
                f"At least 80 candles required for pattern scan; got {len(data)}"
            )

        chart_patterns = self._scan_chart_patterns(
            data,
            mode=mode,
        )

        candle_patterns = self._scan_candlestick_patterns(
            data,
            mode=mode,
        )

        confirmed_charts = [
            item
            for item in chart_patterns
            if item.detected and item.confirmed
        ]

        confirmed_candles = [
            item
            for item in candle_patterns
            if item.detected and item.confirmed
        ]

        best_chart = self._best_match(
            confirmed_charts
        )

        best_candle = self._best_match(
            confirmed_candles
        )

        chart_bullish = (
            best_chart is not None
            and best_chart.score >= 60.0
        )

        candle_bullish = (
            best_candle is not None
            and best_candle.score >= 60.0
        )

        chart_name = (
            best_chart.name
            if best_chart
            else ""
        )

        candle_name = (
            best_candle.name
            if best_candle
            else ""
        )

        chart_score = (
            float(best_chart.score)
            if best_chart
            else 0.0
        )

        candle_score = (
            float(best_candle.score)
            if best_candle
            else 0.0
        )

        total_score = round(
            min(
                100.0,
                (
                    chart_score * 0.60
                    + candle_score * 0.40
                ),
            ),
            2,
        )

        confirmation = PatternConfirmation(
            chart_pattern_bullish=chart_bullish,
            chart_pattern_score=chart_score,
            chart_pattern_name=chart_name,
            candle_pattern_bullish=candle_bullish,
            candle_pattern_score=candle_score,
            candle_pattern_name=candle_name,
        )

        return PatternScanResult(
            mode=mode,
            chart_patterns=tuple(chart_patterns),
            candlestick_patterns=tuple(
                candle_patterns
            ),
            best_chart_pattern=chart_name,
            best_chart_score=chart_score,
            chart_pattern_bullish=chart_bullish,
            best_candle_pattern=candle_name,
            best_candle_score=candle_score,
            candle_pattern_bullish=candle_bullish,
            total_pattern_score=total_score,
            confirmation=confirmation,
        )

    # ========================================================
    # CHART PATTERNS
    # ========================================================

    def _scan_chart_patterns(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> list[PatternMatch]:
        detectors = [
            self._ascending_triangle,
            self._symmetrical_triangle,
            self._falling_wedge,
            self._bull_flag,
            self._cup_and_handle,
            self._double_bottom,
            self._inverse_head_shoulders,
            self._rectangle_breakout,
            self._channel_breakout,
            self._rounding_bottom,
        ]

        results: list[PatternMatch] = []

        for detector in detectors:
            try:
                match = detector(
                    df,
                    mode=mode,
                )
            except Exception as exc:
                match = self._empty_match(
                    detector.__name__,
                    reason=f"Pattern calculation error: {exc}",
                )

            results.append(match)

        return results

    # ========================================================
    # CANDLESTICK PATTERNS
    # ========================================================

    def _scan_candlestick_patterns(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> list[PatternMatch]:
        detectors = [
            self._bullish_engulfing,
            self._hammer,
            self._morning_star,
            self._piercing_pattern,
            self._bullish_harami,
            self._bullish_marubozu,
            self._inverted_hammer,
            self._three_white_soldiers,
            self._tweezer_bottom,
            self._doji_bullish_confirmation,
        ]

        results: list[PatternMatch] = []

        for detector in detectors:
            try:
                match = detector(
                    df,
                    mode=mode,
                )
            except Exception as exc:
                match = self._empty_match(
                    detector.__name__,
                    reason=f"Candlestick calculation error: {exc}",
                )

            results.append(match)

        return results

    # ========================================================
    # CHART: ASCENDING TRIANGLE
    # ========================================================

    def _ascending_triangle(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        data = df.tail(
            Config.CHART_PATTERN_LOOKBACK
        )

        high = data["high"].to_numpy()
        low = data["low"].to_numpy()
        close = data["close"].to_numpy()

        resistance = float(
            np.quantile(high, 0.90)
        )

        near_resistance = (
            np.abs(high - resistance)
            / max(resistance, 1e-9)
            <= 0.015
        )

        touch_count = int(
            near_resistance.sum()
        )

        low_slope = self._slope(low)

        current = float(close[-1])

        detected = (
            touch_count >= 2
            and low_slope > 0
        )

        confirmed = (
            detected
            and self._confirmed_breakout(
                data,
                resistance,
            )
        )

        score = self._pattern_score(
            detected=detected,
            confirmed=confirmed,
            structure_strength=min(
                1.0,
                touch_count / 4.0
            ),
            slope_strength=min(
                1.0,
                max(low_slope, 0.0)
                / max(
                    np.mean(low) * 0.002,
                    1e-9,
                ),
            ),
        )

        return PatternMatch(
            name="ascending_triangle",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=float(
                np.quantile(low, 0.25)
            ),
            resistance=resistance,
            reason=(
                "Flat resistance with rising lows"
                if detected
                else "Ascending-triangle structure not confirmed"
            ),
            details={
                "touch_count": touch_count,
                "low_slope": float(low_slope),
                "current_price": current,
            },
        )

    # ========================================================
    # CHART: SYMMETRICAL TRIANGLE
    # ========================================================

    def _symmetrical_triangle(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        data = df.tail(
            Config.CHART_PATTERN_LOOKBACK
        )

        high = data["high"].to_numpy()
        low = data["low"].to_numpy()

        high_slope = self._slope(high)
        low_slope = self._slope(low)

        resistance = float(
            np.quantile(high[-20:], 0.85)
        )

        support = float(
            np.quantile(low[-20:], 0.15)
        )

        detected = (
            high_slope < 0
            and low_slope > 0
        )

        confirmed = (
            detected
            and self._confirmed_breakout(
                data,
                resistance,
            )
        )

        score = self._pattern_score(
            detected=detected,
            confirmed=confirmed,
            structure_strength=0.8,
            slope_strength=0.8,
        )

        return PatternMatch(
            name="symmetrical_triangle",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=support,
            resistance=resistance,
            reason=(
                "Converging highs/lows with bullish breakout"
                if confirmed
                else "Triangle not breakout-confirmed"
            ),
            details={
                "high_slope": float(high_slope),
                "low_slope": float(low_slope),
            },
        )

    # ========================================================
    # CHART: FALLING WEDGE
    # ========================================================

    def _falling_wedge(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        data = df.tail(
            Config.CHART_PATTERN_LOOKBACK
        )

        high = data["high"].to_numpy()
        low = data["low"].to_numpy()

        high_slope = self._slope(high)
        low_slope = self._slope(low)

        # Both trend lines falling, lower line falling less steeply.
        detected = (
            high_slope < 0
            and low_slope < 0
            and high_slope < low_slope
        )

        resistance = float(
            np.max(
                data["high"].tail(12)
            )
        )

        confirmed = (
            detected
            and self._confirmed_breakout(
                data,
                resistance,
            )
        )

        score = self._pattern_score(
            detected=detected,
            confirmed=confirmed,
            structure_strength=0.85,
            slope_strength=0.85,
        )

        return PatternMatch(
            name="falling_wedge",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=float(
                data["low"].tail(12).min()
            ),
            resistance=resistance,
            reason=(
                "Falling wedge bullish breakout"
                if confirmed
                else "Falling-wedge breakout not confirmed"
            ),
            details={
                "high_slope": float(high_slope),
                "low_slope": float(low_slope),
            },
        )

    # ========================================================
    # CHART: BULL FLAG
    # ========================================================

    def _bull_flag(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        data = df.tail(35)

        pole = data.iloc[:12]
        flag = data.iloc[12:]

        pole_return = self._return(
            float(pole["close"].iloc[0]),
            float(pole["close"].iloc[-1]),
        )

        flag_slope = self._slope(
            flag["close"].to_numpy()
        )

        resistance = float(
            flag["high"].max()
        )

        detected = (
            pole_return >= 5.0
            and flag_slope <= 0
            and flag_slope
            > -(
                float(flag["close"].mean())
                * 0.01
            )
        )

        confirmed = (
            detected
            and self._confirmed_breakout(
                data,
                resistance,
            )
        )

        score = self._pattern_score(
            detected=detected,
            confirmed=confirmed,
            structure_strength=min(
                1.0,
                pole_return / 10.0,
            ),
            slope_strength=0.8,
        )

        return PatternMatch(
            name="bull_flag",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=float(
                flag["low"].min()
            ),
            resistance=resistance,
            reason=(
                "Strong pole with controlled consolidation"
                if detected
                else "Bull-flag structure not confirmed"
            ),
            details={
                "pole_return_pct": pole_return,
                "flag_slope": float(flag_slope),
            },
        )

    # ========================================================
    # CHART: CUP AND HANDLE
    # ========================================================

    def _cup_and_handle(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        data = df.tail(80)

        close = data["close"].to_numpy()

        first_third = close[:25]
        middle = close[20:60]
        last = close[-20:]

        left_rim = float(
            np.max(first_third)
        )
        bottom = float(
            np.min(middle)
        )
        right_rim = float(
            np.max(last)
        )

        rim_diff = (
            abs(left_rim - right_rim)
            / max(left_rim, 1e-9)
        )

        depth = (
            (left_rim - bottom)
            / max(left_rim, 1e-9)
        )

        handle = data.tail(12)
        handle_pullback = (
            (
                float(handle["high"].max())
                - float(handle["low"].min())
            )
            / max(
                float(handle["high"].max()),
                1e-9,
            )
        )

        resistance = max(
            left_rim,
            right_rim,
        )

        detected = (
            rim_diff <= 0.05
            and 0.08 <= depth <= 0.35
            and handle_pullback <= 0.12
        )

        confirmed = (
            detected
            and self._confirmed_breakout(
                data,
                resistance,
            )
        )

        score = self._pattern_score(
            detected=detected,
            confirmed=confirmed,
            structure_strength=max(
                0.0,
                1.0 - rim_diff / 0.05,
            ),
            slope_strength=0.9,
        )

        return PatternMatch(
            name="cup_and_handle",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=bottom,
            resistance=resistance,
            reason=(
                "Rounded cup with shallow handle"
                if detected
                else "Cup-and-handle geometry not confirmed"
            ),
            details={
                "left_rim": left_rim,
                "right_rim": right_rim,
                "cup_depth_pct": depth * 100.0,
                "handle_pullback_pct": (
                    handle_pullback * 100.0
                ),
            },
        )

    # ========================================================
    # CHART: DOUBLE BOTTOM
    # ========================================================

    def _double_bottom(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        data = df.tail(70)

        low = data["low"].to_numpy()

        first_half = low[:35]
        second_half = low[35:]

        bottom1 = float(
            np.min(first_half)
        )
        bottom2 = float(
            np.min(second_half)
        )

        bottom_diff = (
            abs(bottom1 - bottom2)
            / max(bottom1, 1e-9)
        )

        neckline = float(
            data["high"].iloc[20:50].max()
        )

        detected = (
            bottom_diff <= 0.04
        )

        confirmed = (
            detected
            and self._confirmed_breakout(
                data,
                neckline,
            )
        )

        score = self._pattern_score(
            detected=detected,
            confirmed=confirmed,
            structure_strength=max(
                0.0,
                1.0 - bottom_diff / 0.04,
            ),
            slope_strength=0.85,
        )

        return PatternMatch(
            name="double_bottom",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=neckline,
            support=min(
                bottom1,
                bottom2,
            ),
            resistance=neckline,
            reason=(
                "Two comparable lows with neckline breakout"
                if confirmed
                else "Double-bottom neckline not confirmed"
            ),
            details={
                "bottom_1": bottom1,
                "bottom_2": bottom2,
                "bottom_difference_pct": (
                    bottom_diff * 100.0
                ),
            },
        )

    # ========================================================
    # CHART: INVERSE HEAD AND SHOULDERS
    # ========================================================

    def _inverse_head_shoulders(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        data = df.tail(90)

        low = data["low"].to_numpy()

        left = float(
            np.min(low[:30])
        )
        head = float(
            np.min(low[30:60])
        )
        right = float(
            np.min(low[60:])
        )

        shoulder_diff = (
            abs(left - right)
            / max(left, 1e-9)
        )

        head_lower = (
            head
            < min(left, right) * 0.97
        )

        neckline = float(
            data["high"].iloc[25:70].max()
        )

        detected = (
            head_lower
            and shoulder_diff <= 0.08
        )

        confirmed = (
            detected
            and self._confirmed_breakout(
                data,
                neckline,
            )
        )

        score = self._pattern_score(
            detected=detected,
            confirmed=confirmed,
            structure_strength=max(
                0.0,
                1.0 - shoulder_diff / 0.08,
            ),
            slope_strength=0.9,
        )

        return PatternMatch(
            name="inverse_head_and_shoulders",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=neckline,
            support=head,
            resistance=neckline,
            reason=(
                "Inverse H&S with neckline breakout"
                if confirmed
                else "Inverse H&S breakout not confirmed"
            ),
            details={
                "left_shoulder": left,
                "head": head,
                "right_shoulder": right,
            },
        )

    # ========================================================
    # CHART: RECTANGLE BREAKOUT
    # ========================================================

    def _rectangle_breakout(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        data = df.tail(40)

        resistance = float(
            data["high"].iloc[:-1].quantile(
                0.90
            )
        )
        support = float(
            data["low"].iloc[:-1].quantile(
                0.10
            )
        )

        width_pct = (
            (
                resistance - support
            )
            / max(
                (resistance + support) / 2.0,
                1e-9,
            )
        )

        detected = (
            0.01 <= width_pct <= 0.12
        )

        confirmed = (
            detected
            and self._confirmed_breakout(
                data,
                resistance,
            )
        )

        score = self._pattern_score(
            detected=detected,
            confirmed=confirmed,
            structure_strength=max(
                0.0,
                1.0 - width_pct / 0.12,
            ),
            slope_strength=0.8,
        )

        return PatternMatch(
            name="rectangle_breakout",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=support,
            resistance=resistance,
            reason=(
                "Range consolidation breakout"
                if confirmed
                else "Rectangle breakout not confirmed"
            ),
            details={
                "range_width_pct": (
                    width_pct * 100.0
                ),
            },
        )

    # ========================================================
    # CHART: CHANNEL BREAKOUT
    # ========================================================

    def _channel_breakout(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        data = df.tail(50)

        highs = data["high"].to_numpy()
        lows = data["low"].to_numpy()

        high_slope = self._slope(highs[:-1])
        low_slope = self._slope(lows[:-1])

        parallel = (
            abs(
                high_slope - low_slope
            )
            <= max(
                abs(high_slope),
                abs(low_slope),
                1e-9,
            ) * 0.35
        )

        resistance = float(
            data["high"].iloc[:-1].max()
        )

        detected = parallel

        confirmed = (
            detected
            and self._confirmed_breakout(
                data,
                resistance,
            )
        )

        score = self._pattern_score(
            detected=detected,
            confirmed=confirmed,
            structure_strength=0.75,
            slope_strength=0.75,
        )

        return PatternMatch(
            name="channel_breakout",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=float(
                data["low"].iloc[:-1].min()
            ),
            resistance=resistance,
            reason=(
                "Parallel price channel breakout"
                if confirmed
                else "Channel breakout not confirmed"
            ),
            details={
                "high_slope": float(high_slope),
                "low_slope": float(low_slope),
            },
        )

    # ========================================================
    # CHART: ROUNDING BOTTOM
    # ========================================================

    def _rounding_bottom(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        data = df.tail(80)

        close = data["close"].to_numpy()

        x = np.arange(
            len(close),
            dtype=float,
        )

        coeff = np.polyfit(
            x,
            close,
            2,
        )

        curvature = float(
            coeff[0]
        )

        resistance = float(
            np.quantile(
                data["high"].tail(20),
                0.90,
            )
        )

        detected = (
            curvature > 0
            and close[-1] > close[len(close) // 2]
        )

        confirmed = (
            detected
            and self._confirmed_breakout(
                data,
                resistance,
            )
        )

        score = self._pattern_score(
            detected=detected,
            confirmed=confirmed,
            structure_strength=0.8,
            slope_strength=0.8,
        )

        return PatternMatch(
            name="rounding_bottom",
            detected=detected,
            confirmed=confirmed,
            score=score,
            confidence=score,
            breakout_price=resistance,
            support=float(
                data["low"].min()
            ),
            resistance=resistance,
            reason=(
                "Positive curvature rounding bottom"
                if detected
                else "Rounding-bottom curvature not confirmed"
            ),
            details={
                "quadratic_curvature": curvature,
            },
        )

    # ========================================================
    # CANDLE: BULLISH ENGULFING
    # ========================================================

    def _bullish_engulfing(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        prev = df.iloc[-2]
        curr = df.iloc[-1]

        detected = (
            prev["close"] < prev["open"]
            and curr["close"] > curr["open"]
            and curr["open"] <= prev["close"]
            and curr["close"] >= prev["open"]
        )

        return self._candle_match(
            "bullish_engulfing",
            detected,
            df,
            88.0,
            "Bullish candle fully engulfs previous bearish body",
        )

    # ========================================================
    # CANDLE: HAMMER
    # ========================================================

    def _hammer(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        row = df.iloc[-1]

        body, upper, lower, rng = (
            self._candle_geometry(row)
        )

        detected = (
            rng > 0
            and lower >= body * 2.0
            and upper <= max(
                body,
                rng * 0.20,
            )
            and row["close"] >= row["open"]
        )

        return self._candle_match(
            "hammer",
            detected,
            df,
            78.0,
            "Long lower wick with bullish close",
        )

    # ========================================================
    # CANDLE: MORNING STAR
    # ========================================================

    def _morning_star(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        a = df.iloc[-3]
        b = df.iloc[-2]
        c = df.iloc[-1]

        a_body = abs(
            a["close"] - a["open"]
        )
        b_body = abs(
            b["close"] - b["open"]
        )

        midpoint_a = (
            a["open"]
            + a["close"]
        ) / 2.0

        detected = (
            a["close"] < a["open"]
            and b_body <= a_body * 0.5
            and c["close"] > c["open"]
            and c["close"] > midpoint_a
        )

        return self._candle_match(
            "morning_star",
            detected,
            df,
            92.0,
            "Three-candle bullish reversal sequence",
        )

    # ========================================================
    # CANDLE: PIERCING
    # ========================================================

    def _piercing_pattern(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        prev = df.iloc[-2]
        curr = df.iloc[-1]

        midpoint = (
            prev["open"]
            + prev["close"]
        ) / 2.0

        detected = (
            prev["close"] < prev["open"]
            and curr["close"] > curr["open"]
            and curr["open"] <= prev["close"]
            and curr["close"] > midpoint
            and curr["close"] < prev["open"]
        )

        return self._candle_match(
            "piercing_pattern",
            detected,
            df,
            80.0,
            "Bullish close penetrates previous bearish body",
        )

    # ========================================================
    # CANDLE: BULLISH HARAMI
    # ========================================================

    def _bullish_harami(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        prev = df.iloc[-2]
        curr = df.iloc[-1]

        detected = (
            prev["close"] < prev["open"]
            and curr["close"] > curr["open"]
            and curr["open"] > prev["close"]
            and curr["close"] < prev["open"]
        )

        return self._candle_match(
            "bullish_harami",
            detected,
            df,
            72.0,
            "Small bullish body contained inside previous bearish body",
        )

    # ========================================================
    # CANDLE: BULLISH MARUBOZU
    # ========================================================

    def _bullish_marubozu(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        row = df.iloc[-1]

        body, upper, lower, rng = (
            self._candle_geometry(row)
        )

        detected = (
            row["close"] > row["open"]
            and rng > 0
            and body / rng >= 0.80
            and upper / rng <= 0.10
            and lower / rng <= 0.10
        )

        return self._candle_match(
            "bullish_marubozu",
            detected,
            df,
            90.0,
            "Large bullish body with minimal wicks",
        )

    # ========================================================
    # CANDLE: INVERTED HAMMER
    # ========================================================

    def _inverted_hammer(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        row = df.iloc[-1]

        body, upper, lower, rng = (
            self._candle_geometry(row)
        )

        detected = (
            rng > 0
            and upper >= body * 2.0
            and lower <= max(
                body,
                rng * 0.20,
            )
            and row["close"] >= row["open"]
        )

        return self._candle_match(
            "inverted_hammer",
            detected,
            df,
            70.0,
            "Long upper wick with bullish body",
        )

    # ========================================================
    # CANDLE: THREE WHITE SOLDIERS
    # ========================================================

    def _three_white_soldiers(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        rows = df.iloc[-3:]

        bullish = all(
            row["close"] > row["open"]
            for _, row in rows.iterrows()
        )

        rising_closes = (
            rows["close"].iloc[0]
            < rows["close"].iloc[1]
            < rows["close"].iloc[2]
        )

        detected = (
            bullish
            and rising_closes
        )

        return self._candle_match(
            "three_white_soldiers",
            detected,
            df,
            95.0,
            "Three consecutive strong bullish candles",
        )

    # ========================================================
    # CANDLE: TWEEZER BOTTOM
    # ========================================================

    def _tweezer_bottom(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        prev = df.iloc[-2]
        curr = df.iloc[-1]

        low_diff = (
            abs(
                float(prev["low"])
                - float(curr["low"])
            )
            / max(
                float(prev["low"]),
                1e-9,
            )
        )

        detected = (
            low_diff <= 0.003
            and prev["close"] < prev["open"]
            and curr["close"] > curr["open"]
        )

        return self._candle_match(
            "tweezer_bottom",
            detected,
            df,
            76.0,
            "Two nearly equal lows with bullish reversal",
        )

    # ========================================================
    # CANDLE: DOJI + CONFIRMATION
    # ========================================================

    def _doji_bullish_confirmation(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
    ) -> PatternMatch:
        doji = df.iloc[-2]
        curr = df.iloc[-1]

        body, _, _, rng = (
            self._candle_geometry(doji)
        )

        doji_detected = (
            rng > 0
            and body / rng <= 0.10
        )

        bullish_confirmation = (
            curr["close"] > curr["open"]
            and curr["close"] > doji["high"]
        )

        detected = (
            doji_detected
            and bullish_confirmation
        )

        return self._candle_match(
            "doji_bullish_confirmation",
            detected,
            df,
            74.0,
            "Doji followed by bullish breakout confirmation",
        )

    # ========================================================
    # SHARED CONFIRMATION
    # ========================================================

    def _confirmed_breakout(
        self,
        df: pd.DataFrame,
        resistance: float,
    ) -> bool:
        if resistance <= 0:
            return False

        close = float(
            df["close"].iloc[-1]
        )

        volume = float(
            df["volume"].iloc[-1]
        )

        avg_volume = float(
            df["volume"]
            .tail(Config.VOLUME_AVG_PERIOD)
            .mean()
        )

        volume_ratio = (
            volume / avg_volume
            if avg_volume > 0
            else 0.0
        )

        required_price = (
            resistance
            * (
                1.0
                + Config.BREAKOUT_BUFFER_PERCENT
                / 100.0
            )
        )

        return (
            close >= required_price
            and volume_ratio
            >= Config.SWING_MIN_VOLUME_RATIO
        )

    @staticmethod
    def _pattern_score(
        *,
        detected: bool,
        confirmed: bool,
        structure_strength: float,
        slope_strength: float,
    ) -> float:
        if not detected:
            return 0.0

        base = 40.0

        base += (
            max(
                0.0,
                min(
                    structure_strength,
                    1.0,
                ),
            )
            * 25.0
        )

        base += (
            max(
                0.0,
                min(
                    slope_strength,
                    1.0,
                ),
            )
            * 15.0
        )

        if confirmed:
            base += 20.0

        return round(
            min(
                base,
                100.0,
            ),
            2,
        )

    def _candle_match(
        self,
        name: str,
        detected: bool,
        df: pd.DataFrame,
        base_score: float,
        reason: str,
    ) -> PatternMatch:
        row = df.iloc[-1]

        avg_volume = float(
            df["volume"]
            .tail(Config.VOLUME_AVG_PERIOD)
            .mean()
        )

        current_volume = float(
            row["volume"]
        )

        volume_ratio = (
            current_volume / avg_volume
            if avg_volume > 0
            else 0.0
        )

        confirmed = (
            detected
            and row["close"] > row["open"]
            and volume_ratio >= 1.0
        )

        score = (
            min(
                100.0,
                base_score
                + (
                    7.0
                    if volume_ratio
                    >= Config.STRONG_VOLUME_RATIO
                    else 0.0
                ),
            )
            if confirmed
            else (
                base_score * 0.70
                if detected
                else 0.0
            )
        )

        return PatternMatch(
            name=name,
            detected=detected,
            confirmed=confirmed,
            score=round(
                score,
                2,
            ),
            confidence=round(
                score,
                2,
            ),
            breakout_price=float(
                row["high"]
            ),
            support=float(
                row["low"]
            ),
            resistance=float(
                row["high"]
            ),
            reason=(
                reason
                if detected
                else f"{name} not detected"
            ),
            details={
                "volume_ratio": round(
                    volume_ratio,
                    3,
                ),
            },
        )

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _best_match(
        matches: list[PatternMatch],
    ) -> PatternMatch | None:
        if not matches:
            return None

        return max(
            matches,
            key=lambda item: (
                item.score,
                item.confidence,
            ),
        )

    @staticmethod
    def _empty_match(
        name: str,
        *,
        reason: str,
    ) -> PatternMatch:
        clean = (
            name.lstrip("_")
        )

        return PatternMatch(
            name=clean,
            detected=False,
            confirmed=False,
            score=0.0,
            confidence=0.0,
            breakout_price=0.0,
            support=0.0,
            resistance=0.0,
            reason=reason,
            details={},
        )

    @staticmethod
    def _return(
        start: float,
        end: float,
    ) -> float:
        if start <= 0:
            return 0.0

        return (
            (end - start)
            / start
        ) * 100.0

    @staticmethod
    def _slope(
        values: np.ndarray,
    ) -> float:
        if len(values) < 2:
            return 0.0

        x = np.arange(
            len(values),
            dtype=float,
        )

        slope = np.polyfit(
            x,
            values.astype(float),
            1,
        )[0]

        return float(slope)

    @staticmethod
    def _candle_geometry(
        row: pd.Series,
    ) -> tuple[
        float,
        float,
        float,
        float,
    ]:
        open_ = float(
            row["open"]
        )
        high = float(
            row["high"]
        )
        low = float(
            row["low"]
        )
        close = float(
            row["close"]
        )

        body = abs(
            close - open_
        )

        upper = (
            high
            - max(open_, close)
        )

        lower = (
            min(open_, close)
            - low
        )

        rng = (
            high - low
        )

        return (
            max(body, 0.0),
            max(upper, 0.0),
            max(lower, 0.0),
            max(rng, 0.0),
        )

    @staticmethod
    def _prepare_dataframe(
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        if not isinstance(
            df,
            pd.DataFrame,
        ):
            raise PatternScannerError(
                "Pattern input must be a pandas DataFrame"
            )

        required = {
            "open",
            "high",
            "low",
            "close",
            "volume",
        }

        missing = required.difference(
            df.columns
        )

        if missing:
            raise PatternScannerError(
                f"Missing OHLCV columns: {sorted(missing)}"
            )

        data = df.copy()

        for column in required:
            data[column] = pd.to_numeric(
                data[column],
                errors="coerce",
            )

        data = data.dropna(
            subset=list(required)
        ).reset_index(drop=True)

        if not Config.ALLOW_ZERO_PRICE:
            data = data[
                (data["open"] > 0)
                & (data["high"] > 0)
                & (data["low"] > 0)
                & (data["close"] > 0)
            ].reset_index(drop=True)

        data = data[
            (data["high"] >= data["low"])
            & (
                data["high"]
                >= data[
                    ["open", "close"]
                ].max(axis=1)
            )
            & (
                data["low"]
                <= data[
                    ["open", "close"]
                ].min(axis=1)
            )
            & (data["volume"] >= 0)
        ].reset_index(drop=True)

        if data.empty:
            raise PatternScannerError(
                "No valid OHLCV rows after validation"
            )

        return data


_default_pattern_scanner = PatternScanner()


def get_pattern_scanner(
) -> PatternScanner:
    return _default_pattern_scanner


def scan_patterns(
    df: pd.DataFrame,
    *,
    mode: str | None = None,
) -> PatternScanResult:
    return (
        _default_pattern_scanner
        .scan(
            df,
            mode=mode,
        )
    )
