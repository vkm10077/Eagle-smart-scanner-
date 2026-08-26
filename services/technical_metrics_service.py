from __future__ import annotations

"""
Eagle Smart Scanner - Technical Metrics Service

Core technical calculation engine used by TechnicalScanner.

Calculates:
- EMA 20 / 50 / 200
- RSI
- MACD
- ATR
- ADX
- Supertrend
- VWAP
- Volume ratio
- Breakout level / breakout confirmation
- Price action (higher-high / higher-low)
- Relative strength
- Distance from recent highs
- Trend / momentum helper metrics

No fundamental data.
No signal label generation.
No fake/random data.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from config import Config


class TechnicalMetricsError(RuntimeError):
    """Technical-metrics calculation error."""


@dataclass(frozen=True)
class TechnicalMetrics:
    mode: str

    price: float

    ema20: float
    ema50: float
    ema200: float
    bullish_ema_structure: bool

    rsi: float

    macd: float
    macd_signal: float
    macd_histogram: float
    macd_bullish: bool

    atr: float
    atr_percent: float

    adx: float
    plus_di: float
    minus_di: float

    supertrend: float
    supertrend_direction: int
    supertrend_buy: bool

    vwap: float
    above_vwap: bool

    volume: float
    avg_volume: float
    volume_ratio: float
    strong_volume: bool

    breakout_level: float
    breakout_confirmed: bool
    breakout_distance_percent: float

    higher_high: bool
    higher_low: bool
    bullish_price_action: bool

    return_5: float
    return_20: float
    relative_strength_percent: float

    recent_high: float
    distance_from_recent_high_percent: float


class TechnicalMetricsService:
    """
    Pure technical metric calculator.
    """

    # ========================================================
    # MAIN
    # ========================================================

    def calculate(
        self,
        df: pd.DataFrame,
        *,
        mode: str,
        benchmark_df: pd.DataFrame | None = None,
    ) -> TechnicalMetrics:
        mode = Config.normalize_trading_mode(mode)

        data = self._prepare_dataframe(df)

        minimum = max(
            Config.EMA_LONG + 5,
            Config.get_min_required_candles(mode),
        )

        if len(data) < minimum:
            raise TechnicalMetricsError(
                f"Insufficient candles: got {len(data)}, need at least {minimum}"
            )

        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)
        volume = data["volume"].astype(float)

        price = float(close.iloc[-1])

        # ----------------------------------------------------
        # EMA
        # ----------------------------------------------------
        ema20_series = close.ewm(
            span=Config.EMA_FAST,
            adjust=False,
        ).mean()

        ema50_series = close.ewm(
            span=Config.EMA_MEDIUM,
            adjust=False,
        ).mean()

        ema200_series = close.ewm(
            span=Config.EMA_LONG,
            adjust=False,
        ).mean()

        ema20 = float(ema20_series.iloc[-1])
        ema50 = float(ema50_series.iloc[-1])
        ema200 = float(ema200_series.iloc[-1])

        bullish_ema = (
            price > ema20
            and ema20 > ema50
            and ema50 > ema200
        )

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------
        rsi_series = self._rsi(
            close,
            Config.RSI_PERIOD,
        )
        rsi = float(rsi_series.iloc[-1])

        # ----------------------------------------------------
        # MACD
        # ----------------------------------------------------
        macd_series, macd_signal_series, macd_hist_series = (
            self._macd(close)
        )

        macd = float(macd_series.iloc[-1])
        macd_signal = float(
            macd_signal_series.iloc[-1]
        )
        macd_hist = float(
            macd_hist_series.iloc[-1]
        )
        macd_bullish = (
            macd > macd_signal
            and macd_hist > 0
        )

        # ----------------------------------------------------
        # ATR
        # ----------------------------------------------------
        atr_series = self._atr(
            data,
            Config.ATR_PERIOD,
        )

        atr = float(atr_series.iloc[-1])

        atr_percent = (
            (atr / price) * 100.0
            if price > 0
            else 0.0
        )

        # ----------------------------------------------------
        # ADX / DI
        # ----------------------------------------------------
        adx_series, plus_di_series, minus_di_series = (
            self._adx(
                data,
                Config.ADX_PERIOD,
            )
        )

        adx = float(adx_series.iloc[-1])
        plus_di = float(
            plus_di_series.iloc[-1]
        )
        minus_di = float(
            minus_di_series.iloc[-1]
        )

        # ----------------------------------------------------
        # SUPERTREND
        # ----------------------------------------------------
        supertrend_series, supertrend_dir = (
            self._supertrend(
                data,
                period=Config.SUPERTREND_PERIOD,
                multiplier=Config.SUPERTREND_MULTIPLIER,
            )
        )

        supertrend = float(
            supertrend_series.iloc[-1]
        )
        supertrend_direction = int(
            supertrend_dir.iloc[-1]
        )
        supertrend_buy = (
            supertrend_direction > 0
            and price >= supertrend
        )

        # ----------------------------------------------------
        # VWAP
        # ----------------------------------------------------
        vwap_series = self._vwap(data)
        vwap = float(vwap_series.iloc[-1])
        above_vwap = (
            price > vwap
            if vwap > 0
            else False
        )

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------
        avg_volume = float(
            volume.rolling(
                Config.VOLUME_AVG_PERIOD
            ).mean().iloc[-1]
        )

        current_volume = float(
            volume.iloc[-1]
        )

        volume_ratio = (
            current_volume / avg_volume
            if avg_volume > 0
            else 0.0
        )

        strong_volume = (
            volume_ratio
            >= Config.STRONG_VOLUME_RATIO
        )

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------
        breakout_lookback = (
            Config.get_breakout_lookback(
                mode
            )
        )

        breakout_level = float(
            high.shift(1)
            .rolling(
                breakout_lookback
            )
            .max()
            .iloc[-1]
        )

        breakout_buffer = (
            breakout_level
            * (
                Config.BREAKOUT_BUFFER_PERCENT
                / 100.0
            )
        )

        breakout_confirmed = (
            price
            >= (
                breakout_level
                + breakout_buffer
            )
        )

        breakout_distance = (
            (
                (price - breakout_level)
                / breakout_level
            ) * 100.0
            if breakout_level > 0
            else 0.0
        )

        # ----------------------------------------------------
        # PRICE ACTION
        # ----------------------------------------------------
        higher_high, higher_low = (
            self._price_action(
                data,
                lookback=(
                    Config.PRICE_ACTION_LOOKBACK
                ),
            )
        )

        bullish_price_action = (
            higher_high
            and higher_low
        )

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------
        return_5 = self._period_return(
            close,
            5,
        )

        return_20 = self._period_return(
            close,
            Config.RELATIVE_STRENGTH_LOOKBACK,
        )

        benchmark_return = 0.0

        if (
            benchmark_df is not None
            and not benchmark_df.empty
        ):
            benchmark_data = (
                self._prepare_dataframe(
                    benchmark_df
                )
            )

            benchmark_return = (
                self._period_return(
                    benchmark_data[
                        "close"
                    ].astype(float),
                    Config.RELATIVE_STRENGTH_LOOKBACK,
                )
            )

        relative_strength = (
            return_20
            - benchmark_return
        )

        # ----------------------------------------------------
        # RECENT HIGH
        # ----------------------------------------------------
        recent_high = float(
            high.tail(
                max(
                    breakout_lookback,
                    20,
                )
            ).max()
        )

        distance_recent_high = (
            (
                (recent_high - price)
                / recent_high
            ) * 100.0
            if recent_high > 0
            else 0.0
        )

        return TechnicalMetrics(
            mode=mode,
            price=price,
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            bullish_ema_structure=(
                bullish_ema
            ),
            rsi=rsi,
            macd=macd,
            macd_signal=macd_signal,
            macd_histogram=macd_hist,
            macd_bullish=macd_bullish,
            atr=atr,
            atr_percent=atr_percent,
            adx=adx,
            plus_di=plus_di,
            minus_di=minus_di,
            supertrend=supertrend,
            supertrend_direction=(
                supertrend_direction
            ),
            supertrend_buy=supertrend_buy,
            vwap=vwap,
            above_vwap=above_vwap,
            volume=current_volume,
            avg_volume=avg_volume,
            volume_ratio=volume_ratio,
            strong_volume=strong_volume,
            breakout_level=breakout_level,
            breakout_confirmed=(
                breakout_confirmed
            ),
            breakout_distance_percent=(
                breakout_distance
            ),
            higher_high=higher_high,
            higher_low=higher_low,
            bullish_price_action=(
                bullish_price_action
            ),
            return_5=return_5,
            return_20=return_20,
            relative_strength_percent=(
                relative_strength
            ),
            recent_high=recent_high,
            distance_from_recent_high_percent=(
                distance_recent_high
            ),
        )

    # ========================================================
    # RSI
    # ========================================================

    @staticmethod
    def _rsi(
        close: pd.Series,
        period: int,
    ) -> pd.Series:
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

        rs = avg_gain / avg_loss.replace(
            0.0,
            np.nan,
        )

        rsi = (
            100.0
            - (
                100.0
                / (1.0 + rs)
            )
        )

        # Wilder RSI edge cases.
        rsi = rsi.where(
            avg_loss != 0.0,
            100.0,
        )

        both_zero = (
            (avg_gain == 0.0)
            & (avg_loss == 0.0)
        )

        rsi = rsi.where(
            ~both_zero,
            50.0,
        )

        return rsi.fillna(50.0)

    # ========================================================
    # MACD
    # ========================================================

    @staticmethod
    def _macd(
        close: pd.Series,
    ) -> tuple[
        pd.Series,
        pd.Series,
        pd.Series,
    ]:
        fast = close.ewm(
            span=Config.MACD_FAST,
            adjust=False,
        ).mean()

        slow = close.ewm(
            span=Config.MACD_SLOW,
            adjust=False,
        ).mean()

        macd = fast - slow

        signal = macd.ewm(
            span=Config.MACD_SIGNAL,
            adjust=False,
        ).mean()

        histogram = macd - signal

        return (
            macd,
            signal,
            histogram,
        )

    # ========================================================
    # ATR
    # ========================================================

    @staticmethod
    def _atr(
        df: pd.DataFrame,
        period: int,
    ) -> pd.Series:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        previous_close = close.shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        return tr.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        ).mean().fillna(0.0)

    # ========================================================
    # ADX
    # ========================================================

    @staticmethod
    def _adx(
        df: pd.DataFrame,
        period: int,
    ) -> tuple[
        pd.Series,
        pd.Series,
        pd.Series,
    ]:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        up_move = high.diff()
        down_move = -low.diff()

        plus_dm = pd.Series(
            np.where(
                (up_move > down_move)
                & (up_move > 0),
                up_move,
                0.0,
            ),
            index=df.index,
            dtype=float,
        )

        minus_dm = pd.Series(
            np.where(
                (down_move > up_move)
                & (down_move > 0),
                down_move,
                0.0,
            ),
            index=df.index,
            dtype=float,
        )

        previous_close = close.shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr = tr.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        plus_smoothed = plus_dm.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        minus_smoothed = minus_dm.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        plus_di = (
            100.0
            * plus_smoothed
            / atr.replace(0.0, np.nan)
        )

        minus_di = (
            100.0
            * minus_smoothed
            / atr.replace(0.0, np.nan)
        )

        denominator = (
            plus_di
            + minus_di
        ).replace(
            0.0,
            np.nan,
        )

        dx = (
            100.0
            * (
                plus_di
                - minus_di
            ).abs()
            / denominator
        )

        adx = dx.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        return (
            adx.fillna(0.0),
            plus_di.fillna(0.0),
            minus_di.fillna(0.0),
        )

    # ========================================================
    # SUPERTREND
    # ========================================================

    @classmethod
    def _supertrend(
        cls,
        df: pd.DataFrame,
        *,
        period: int,
        multiplier: float,
    ) -> tuple[
        pd.Series,
        pd.Series,
    ]:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        atr = cls._atr(
            df,
            period,
        )

        hl2 = (
            high
            + low
        ) / 2.0

        basic_upper = (
            hl2
            + multiplier * atr
        )

        basic_lower = (
            hl2
            - multiplier * atr
        )

        final_upper = basic_upper.copy()
        final_lower = basic_lower.copy()

        direction = pd.Series(
            1,
            index=df.index,
            dtype=int,
        )

        supertrend = pd.Series(
            np.nan,
            index=df.index,
            dtype=float,
        )

        for i in range(1, len(df)):
            prev = i - 1

            if (
                basic_upper.iloc[i]
                < final_upper.iloc[prev]
                or close.iloc[prev]
                > final_upper.iloc[prev]
            ):
                final_upper.iloc[i] = (
                    basic_upper.iloc[i]
                )
            else:
                final_upper.iloc[i] = (
                    final_upper.iloc[prev]
                )

            if (
                basic_lower.iloc[i]
                > final_lower.iloc[prev]
                or close.iloc[prev]
                < final_lower.iloc[prev]
            ):
                final_lower.iloc[i] = (
                    basic_lower.iloc[i]
                )
            else:
                final_lower.iloc[i] = (
                    final_lower.iloc[prev]
                )

            if direction.iloc[prev] > 0:
                if (
                    close.iloc[i]
                    < final_lower.iloc[i]
                ):
                    direction.iloc[i] = -1
                else:
                    direction.iloc[i] = 1
            else:
                if (
                    close.iloc[i]
                    > final_upper.iloc[i]
                ):
                    direction.iloc[i] = 1
                else:
                    direction.iloc[i] = -1

            supertrend.iloc[i] = (
                final_lower.iloc[i]
                if direction.iloc[i] > 0
                else final_upper.iloc[i]
            )

        if len(supertrend) > 0:
            supertrend.iloc[0] = (
                final_lower.iloc[0]
            )

        return (
            supertrend.ffill().fillna(0.0),
            direction,
        )

    # ========================================================
    # VWAP
    # ========================================================

    @staticmethod
    def _vwap(
        df: pd.DataFrame,
    ) -> pd.Series:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        volume = df["volume"].astype(float)

        typical_price = (
            high
            + low
            + close
        ) / 3.0

        if "datetime" in df.columns:
            dt = pd.to_datetime(
                df["datetime"]
            )

            # Session-based VWAP for intraday data.
            group_key = dt.dt.date

            pv = (
                typical_price
                * volume
            )

            cumulative_pv = pv.groupby(
                group_key
            ).cumsum()

            cumulative_volume = volume.groupby(
                group_key
            ).cumsum()

            vwap = (
                cumulative_pv
                / cumulative_volume.replace(
                    0.0,
                    np.nan,
                )
            )

            return vwap.fillna(
                typical_price
            )

        cumulative_pv = (
            typical_price
            * volume
        ).cumsum()

        cumulative_volume = (
            volume.cumsum()
        )

        return (
            cumulative_pv
            / cumulative_volume.replace(
                0.0,
                np.nan,
            )
        ).fillna(typical_price)

    # ========================================================
    # PRICE ACTION
    # ========================================================

    @staticmethod
    def _price_action(
        df: pd.DataFrame,
        *,
        lookback: int,
    ) -> tuple[bool, bool]:
        if len(df) < max(
            lookback,
            8,
        ):
            return False, False

        recent = df.tail(
            max(
                lookback,
                8,
            )
        )

        half = max(
            len(recent) // 2,
            2,
        )

        previous = recent.iloc[
            :-half
        ]

        current = recent.iloc[
            -half:
        ]

        if (
            previous.empty
            or current.empty
        ):
            return False, False

        prev_high = float(
            previous["high"].max()
        )
        curr_high = float(
            current["high"].max()
        )

        prev_low = float(
            previous["low"].min()
        )
        curr_low = float(
            current["low"].min()
        )

        return (
            curr_high > prev_high,
            curr_low > prev_low,
        )

    # ========================================================
    # RETURN
    # ========================================================

    @staticmethod
    def _period_return(
        close: pd.Series,
        periods: int,
    ) -> float:
        if len(close) <= periods:
            return 0.0

        previous = float(
            close.iloc[
                -(periods + 1)
            ]
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

    # ========================================================
    # DATA PREP
    # ========================================================

    @staticmethod
    def _prepare_dataframe(
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        if not isinstance(
            df,
            pd.DataFrame,
        ):
            raise TechnicalMetricsError(
                "Technical input must be a pandas DataFrame."
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
            raise TechnicalMetricsError(
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
            raise TechnicalMetricsError(
                "No valid OHLCV rows after validation."
            )

        return data


_default_metrics_service = TechnicalMetricsService()


def get_technical_metrics_service(
) -> TechnicalMetricsService:
    return _default_metrics_service


def calculate_technical_metrics(
    df: pd.DataFrame,
    *,
    mode: str,
    benchmark_df: pd.DataFrame | None = None,
) -> TechnicalMetrics:
    return (
        _default_metrics_service
        .calculate(
            df,
            mode=mode,
            benchmark_df=benchmark_df,
        )
    )
