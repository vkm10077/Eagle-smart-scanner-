from __future__ import annotations

import threading
from typing import Any, Iterable

import numpy as np
import pandas as pd

from config import Config

from services.market_data_service import (
    MarketDataService,
    get_market_data_service,
)

from utils.helpers import (
    normalize_symbol,
    safe_float,
    utc_now,
)

from utils.logger import (
    get_logger,
    log_exception,
)


logger = get_logger(
    "services.technical_metrics_service"
)


# ============================================================
# ERROR
# ============================================================


class TechnicalMetricsError(
    RuntimeError
):
    """
    Raised when verified technical metrics
    cannot be generated safely.

    No fake / fabricated market values are allowed.
    """


# ============================================================
# TECHNICAL METRICS SERVICE
# ============================================================


class TechnicalMetricsService:
    """
    Technical ranking metrics engine.

    Used by:

        sector_scanner.py
        stock_ranker.py
        scanner_orchestrator.py

    ==========================================================
    SUPPORTED MODES
    ==========================================================

    INTRADAY
        Primary       = 5m
        Confirmation  = 15m
        Higher        = Daily

    BTST
        Primary       = 15m
        Confirmation  = 60m
        Higher        = Daily

    SWING
        Primary       = Daily
        Confirmation  = Weekly
        Higher        = Weekly

    ==========================================================
    OUTPUT INCLUDES
    ==========================================================

    Momentum:
        change_1d_pct
        change_5d_pct
        change_20d_pct

    Trend:
        EMA20
        EMA50
        EMA200

    Momentum indicators:
        RSI
        MACD

    Trend indicators:
        Supertrend
        ADX

    Participation:
        Volume ratio
        Volume confirmation

    Relative Strength

    Multi-timeframe:
        confirmation_bullish
        higher_timeframe_bullish
        multi_timeframe_confirmed

    IMPORTANT:
        This service ranks stocks.

        Final STRONG BUY remains the responsibility
        of scanners/technical_scanner.py
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        *,
        market_data_service: (
            MarketDataService
            | None
        ) = None,
    ) -> None:

        self.market_data_service = (
            market_data_service
            or get_market_data_service()
        )


    # ========================================================
    # SAFE FLOAT
    # ========================================================

    @staticmethod
    def _number(
        value: Any,
        default: float = 0.0,
    ) -> float:

        number = safe_float(
            value,
            default=default,
        )

        return float(
            number
            if number is not None
            else default
        )


    # ========================================================
    # EMA
    # ========================================================

    @staticmethod
    def _ema(
        series: pd.Series,
        period: int,
    ) -> pd.Series:

        if series.empty:

            return pd.Series(
                dtype="float64"
            )

        return (
            series
            .ewm(
                span=int(
                    period
                ),
                adjust=False,
            )
            .mean()
        )


    # ========================================================
    # RSI
    # ========================================================

    @staticmethod
    def _rsi(
        series: pd.Series,
        period: int,
    ) -> pd.Series:

        if series.empty:

            return pd.Series(
                dtype="float64"
            )

        delta = (
            series.diff()
        )

        gain = (
            delta.clip(
                lower=0.0
            )
        )

        loss = (
            -delta.clip(
                upper=0.0
            )
        )

        average_gain = (
            gain
            .ewm(
                alpha=(
                    1.0
                    / float(
                        period
                    )
                ),
                adjust=False,
            )
            .mean()
        )

        average_loss = (
            loss
            .ewm(
                alpha=(
                    1.0
                    / float(
                        period
                    )
                ),
                adjust=False,
            )
            .mean()
        )

        safe_loss = (
            average_loss.replace(
                0.0,
                np.nan,
            )
        )

        rs = (
            average_gain
            / safe_loss
        )

        rsi = (
            100.0
            - (
                100.0
                / (
                    1.0
                    + rs
                )
            )
        )

        # Rising market with zero average loss.
        rsi = rsi.mask(
            (
                average_loss
                == 0.0
            )
            & (
                average_gain
                > 0.0
            ),
            100.0,
        )

        # Completely flat market.
        rsi = rsi.mask(
            (
                average_loss
                == 0.0
            )
            & (
                average_gain
                == 0.0
            ),
            50.0,
        )

        return (
            rsi
            .fillna(
                50.0
            )
        )


    # ========================================================
    # MACD
    # ========================================================

    @classmethod
    def _macd(
        cls,
        series: pd.Series,
    ) -> tuple[
        pd.Series,
        pd.Series,
        pd.Series,
    ]:

        fast = cls._ema(
            series,
            Config.MACD_FAST,
        )

        slow = cls._ema(
            series,
            Config.MACD_SLOW,
        )

        macd_line = (
            fast
            - slow
        )

        signal_line = (
            cls._ema(
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


    # ========================================================
    # ATR
    # ========================================================

    @staticmethod
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

        high_low = (
            dataframe[
                "high"
            ]
            - dataframe[
                "low"
            ]
        )

        high_previous = (
            dataframe[
                "high"
            ]
            - previous_close
        ).abs()

        low_previous = (
            dataframe[
                "low"
            ]
            - previous_close
        ).abs()

        true_range = (
            pd.concat(
                [
                    high_low,
                    high_previous,
                    low_previous,
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
                    1.0
                    / float(
                        period
                    )
                ),
                adjust=False,
            )
            .mean()
        )


    # ========================================================
    # ADX
    # ========================================================

    @classmethod
    def _adx(
        cls,
        dataframe: pd.DataFrame,
        period: int,
    ) -> tuple[
        pd.Series,
        pd.Series,
        pd.Series,
    ]:

        high = (
            dataframe[
                "high"
            ]
        )

        low = (
            dataframe[
                "low"
            ]
        )

        up_move = (
            high.diff()
        )

        down_move = (
            -low.diff()
        )

        plus_dm = pd.Series(
            np.where(
                (
                    up_move
                    > down_move
                )
                & (
                    up_move
                    > 0
                ),
                up_move,
                0.0,
            ),
            index=(
                dataframe.index
            ),
            dtype="float64",
        )

        minus_dm = pd.Series(
            np.where(
                (
                    down_move
                    > up_move
                )
                & (
                    down_move
                    > 0
                ),
                down_move,
                0.0,
            ),
            index=(
                dataframe.index
            ),
            dtype="float64",
        )

        atr = (
            cls._atr(
                dataframe,
                period,
            )
        )

        smoothed_plus_dm = (
            plus_dm
            .ewm(
                alpha=(
                    1.0
                    / float(
                        period
                    )
                ),
                adjust=False,
            )
            .mean()
        )

        smoothed_minus_dm = (
            minus_dm
            .ewm(
                alpha=(
                    1.0
                    / float(
                        period
                    )
                ),
                adjust=False,
            )
            .mean()
        )

        safe_atr = (
            atr.replace(
                0.0,
                np.nan,
            )
        )

        plus_di = (
            100.0
            * smoothed_plus_dm
            / safe_atr
        )

        minus_di = (
            100.0
            * smoothed_minus_dm
            / safe_atr
        )

        denominator = (
            plus_di
            + minus_di
        ).replace(
            0.0,
            np.nan,
        )

        dx = (
            (
                plus_di
                - minus_di
            )
            .abs()
            / denominator
            * 100.0
        )

        adx = (
            dx
            .ewm(
                alpha=(
                    1.0
                    / float(
                        period
                    )
                ),
                adjust=False,
            )
            .mean()
        )

        return (
            adx.fillna(
                0.0
            ),
            plus_di.fillna(
                0.0
            ),
            minus_di.fillna(
                0.0
            ),
        )


    # ========================================================
    # SUPERTREND
    # ========================================================

    @classmethod
    def _supertrend(
        cls,
        dataframe: pd.DataFrame,
    ) -> tuple[
        pd.Series,
        pd.Series,
    ]:

        atr = (
            cls._atr(
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

        upper_band = (
            hl2
            + (
                Config
                .SUPERTREND_MULTIPLIER
                * atr
            )
        )

        lower_band = (
            hl2
            - (
                Config
                .SUPERTREND_MULTIPLIER
                * atr
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

            previous_close = (
                close.iloc[
                    index - 1
                ]
            )

            if (
                upper_band.iloc[
                    index
                ]
                < final_upper.iloc[
                    index - 1
                ]
                or previous_close
                > final_upper.iloc[
                    index - 1
                ]
            ):

                final_upper.iloc[
                    index
                ] = (
                    upper_band.iloc[
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
                lower_band.iloc[
                    index
                ]
                > final_lower.iloc[
                    index - 1
                ]
                or previous_close
                < final_lower.iloc[
                    index - 1
                ]
            ):

                final_lower.iloc[
                    index
                ] = (
                    lower_band.iloc[
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


        supertrend = pd.Series(
            np.nan,
            index=(
                dataframe.index
            ),
            dtype="float64",
        )

        direction = pd.Series(
            0,
            index=(
                dataframe.index
            ),
            dtype="int64",
        )

        if dataframe.empty:

            return (
                supertrend,
                direction,
            )


        # Initial state based on first candle.
        if (
            close.iloc[0]
            >= lower_band.iloc[0]
        ):

            supertrend.iloc[0] = (
                lower_band.iloc[0]
            )

            direction.iloc[0] = 1

        else:

            supertrend.iloc[0] = (
                upper_band.iloc[0]
            )

            direction.iloc[0] = -1


        for index in range(
            1,
            len(
                dataframe
            ),
        ):

            previous_direction = int(
                direction.iloc[
                    index - 1
                ]
            )

            if (
                previous_direction
                == 1
            ):

                if (
                    close.iloc[
                        index
                    ]
                    < final_lower.iloc[
                        index
                    ]
                ):

                    direction.iloc[
                        index
                    ] = -1

                    supertrend.iloc[
                        index
                    ] = (
                        final_upper.iloc[
                            index
                        ]
                    )

                else:

                    direction.iloc[
                        index
                    ] = 1

                    supertrend.iloc[
                        index
                    ] = (
                        final_lower.iloc[
                            index
                        ]
                    )

            else:

                if (
                    close.iloc[
                        index
                    ]
                    > final_upper.iloc[
                        index
                    ]
                ):

                    direction.iloc[
                        index
                    ] = 1

                    supertrend.iloc[
                        index
                    ] = (
                        final_lower.iloc[
                            index
                        ]
                    )

                else:

                    direction.iloc[
                        index
                    ] = -1

                    supertrend.iloc[
                        index
                    ] = (
                        final_upper.iloc[
                            index
                        ]
                    )


        return (
            supertrend,
            direction,
        )


    # ========================================================
    # VWAP
    # ========================================================

    @staticmethod
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
            .astype(
                float
            )
        )

        cumulative_volume = (
            volume
            .cumsum()
        )

        cumulative_price_volume = (
            (
                typical_price
                * volume
            )
            .cumsum()
        )

        safe_volume = (
            cumulative_volume
            .replace(
                0.0,
                np.nan,
            )
        )

        return (
            cumulative_price_volume
            / safe_volume
        ).ffill()


    # ========================================================
    # CHANGE %
    # ========================================================

    @staticmethod
    def _change_percent(
        current: float,
        previous: float,
    ) -> float:

        if (
            current <= 0
            or previous <= 0
        ):

            return 0.0

        return (
            (
                current
                / previous
            )
            - 1.0
        ) * 100.0


    # ========================================================
    # DATAFRAME
    # ========================================================

    @staticmethod
    def _build_dataframe(
        candles: list[
            dict[str, Any]
        ],
        *,
        minimum: int = 30,
    ) -> pd.DataFrame:

        if not isinstance(
            candles,
            list,
        ):

            raise (
                TechnicalMetricsError(
                    (
                        "Candle data "
                        "must be a list."
                    )
                )
            )

        if not candles:

            raise (
                TechnicalMetricsError(
                    (
                        "Verified candles "
                        "are unavailable."
                    )
                )
            )

        dataframe = pd.DataFrame(
            candles
        )

        required = {
            "open",
            "high",
            "low",
            "close",
            "volume",
        }

        if not required.issubset(
            dataframe.columns
        ):

            raise (
                TechnicalMetricsError(
                    (
                        "Required OHLCV "
                        "columns are missing."
                    )
                )
            )


        # ----------------------------------------------------
        # NUMERIC
        # ----------------------------------------------------

        for column in (
            "open",
            "high",
            "low",
            "close",
            "volume",
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


        if (
            "timestamp"
            in dataframe.columns
        ):

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
                    "open",
                    "high",
                    "low",
                    "close",
                ]
            )
            .copy()
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


        # ----------------------------------------------------
        # POSITIVE PRICES
        # ----------------------------------------------------

        dataframe = dataframe[
            (
                dataframe[
                    "open"
                ]
                > 0
            )
            & (
                dataframe[
                    "high"
                ]
                > 0
            )
            & (
                dataframe[
                    "low"
                ]
                > 0
            )
            & (
                dataframe[
                    "close"
                ]
                > 0
            )
        ].copy()


        # ----------------------------------------------------
        # OHLC VALIDATION
        # ----------------------------------------------------

        dataframe = dataframe[
            (
                dataframe[
                    "high"
                ]
                >= dataframe[
                    [
                        "open",
                        "close",
                        "low",
                    ]
                ]
                .max(
                    axis=1
                )
            )
            & (
                dataframe[
                    "low"
                ]
                <= dataframe[
                    [
                        "open",
                        "close",
                        "high",
                    ]
                ]
                .min(
                    axis=1
                )
            )
            & (
                dataframe[
                    "volume"
                ]
                >= 0
            )
        ].copy()


        # ----------------------------------------------------
        # SORT
        # ----------------------------------------------------

        if (
            "timestamp"
            in dataframe.columns
        ):

            dataframe = (
                dataframe
                .dropna(
                    subset=[
                        "timestamp"
                    ]
                )
                .drop_duplicates(
                    subset=[
                        "timestamp"
                    ],
                    keep="last",
                )
                .sort_values(
                    "timestamp"
                )
            )


        dataframe = (
            dataframe
            .reset_index(
                drop=True
            )
        )


        if (
            len(
                dataframe
            )
            < int(
                minimum
            )
        ):

            raise (
                TechnicalMetricsError(
                    (
                        "Insufficient verified "
                        "candles. "
                        f"{len(dataframe)} available; "
                        f"{minimum} required."
                    )
                )
            )


        return dataframe


    # ========================================================
    # LATEST SERIES VALUE
    # ========================================================

    @staticmethod
    def _series_value(
        series: pd.Series,
        position: int = -1,
    ) -> float:

        try:

            value = safe_float(
                series.iloc[
                    position
                ]
            )

        except Exception:

            value = None

        return float(
            value
            or 0.0
        )


    # ========================================================
    # RSI VALID
    # ========================================================

    @staticmethod
    def _rsi_valid(
        rsi_value: float,
        mode: str,
    ) -> bool:

        minimum, maximum = (
            Config
            .get_rsi_range(
                mode
            )
        )

        return bool(
            minimum
            <= rsi_value
            <= maximum
        )


    # ========================================================
    # TIMEFRAME SUMMARY
    # ========================================================

    def _timeframe_summary(
        self,
        *,
        candles: list[
            dict[str, Any]
        ],
        mode: str,
    ) -> dict[str, Any]:
        """
        Summary for confirmation / higher timeframe.

        Only ~50 candles are required because
        confirmation datasets such as 60-minute BTST
        may legitimately contain fewer than EMA200 candles.

        EMA20 + EMA50 + MACD + RSI + ADX + Supertrend
        are used for confirmation.
        """

        dataframe = (
            self._build_dataframe(
                candles,
                minimum=50,
            )
        )

        close = (
            dataframe[
                "close"
            ]
            .astype(
                float
            )
        )

        ema20 = (
            self._ema(
                close,
                Config.EMA_FAST,
            )
        )

        ema50 = (
            self._ema(
                close,
                Config.EMA_MEDIUM,
            )
        )

        rsi_series = (
            self._rsi(
                close,
                Config.RSI_PERIOD,
            )
        )

        (
            macd_line,
            macd_signal,
            macd_histogram,
        ) = (
            self._macd(
                close
            )
        )

        (
            adx_series,
            plus_di,
            minus_di,
        ) = (
            self._adx(
                dataframe,
                Config.ADX_PERIOD,
            )
        )

        (
            _,
            supertrend_direction,
        ) = (
            self._supertrend(
                dataframe
            )
        )


        current_price = (
            self._series_value(
                close
            )
        )

        ema20_value = (
            self._series_value(
                ema20
            )
        )

        ema50_value = (
            self._series_value(
                ema50
            )
        )

        rsi_value = (
            self._series_value(
                rsi_series
            )
        )

        adx_value = (
            self._series_value(
                adx_series
            )
        )


        above_ema20 = bool(
            current_price
            > ema20_value
        )

        ema20_above_ema50 = bool(
            ema20_value
            > ema50_value
        )

        macd_bullish = bool(
            self._series_value(
                macd_line
            )
            > self._series_value(
                macd_signal
            )
            and self._series_value(
                macd_histogram
            )
            > 0
        )

        supertrend_bullish = bool(
            int(
                self._series_value(
                    supertrend_direction
                )
            )
            == 1
        )

        rsi_valid = (
            self._rsi_valid(
                rsi_value,
                mode,
            )
        )

        adx_confirmed = bool(
            adx_value
            >= Config
            .get_min_adx(
                mode
            )
        )

        positive_di = bool(
            self._series_value(
                plus_di
            )
            > self._series_value(
                minus_di
            )
        )


        # ----------------------------------------------------
        # TIMEFRAME SCORE
        # ----------------------------------------------------

        score = 0.0

        if above_ema20:
            score += 20.0

        if ema20_above_ema50:
            score += 20.0

        if macd_bullish:
            score += 20.0

        if supertrend_bullish:
            score += 20.0

        if rsi_valid:
            score += 10.0

        if (
            adx_confirmed
            and positive_di
        ):
            score += 10.0


        bullish = bool(
            score
            >= 60.0
            and above_ema20
            and ema20_above_ema50
        )


        return {
            "score": round(
                min(
                    100.0,
                    score,
                ),
                2,
            ),

            "bullish": (
                bullish
            ),

            "current_price": round(
                current_price,
                4,
            ),

            "above_ema20": (
                above_ema20
            ),

            "ema20_above_ema50": (
                ema20_above_ema50
            ),

            "macd_bullish": (
                macd_bullish
            ),

            "supertrend_bullish": (
                supertrend_bullish
            ),

            "rsi": round(
                rsi_value,
                4,
            ),

            "rsi_valid": (
                rsi_valid
            ),

            "adx": round(
                adx_value,
                4,
            ),

            "adx_confirmed": (
                adx_confirmed
            ),

            "positive_di": (
                positive_di
            ),

            "candle_count": len(
                dataframe
            ),
        }


    # ========================================================
    # PRIMARY METRICS
    # ========================================================

    def build_metrics_from_candles(
        self,
        *,
        symbol: str,
        candles: list[
            dict[str, Any]
        ],
        benchmark_change_pct: float = 0.0,
        mode: str | None = None,
    ) -> dict[str, Any]:

        normalized_symbol = (
            normalize_symbol(
                symbol
            )
        )

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

        if not normalized_symbol:

            raise ValueError(
                (
                    "Valid stock symbol "
                    "is required."
                )
            )


        # EMA200 is used for ranking,
        # therefore we need at least 200 candles.
        minimum_required = max(
            200,
            int(
                Config.EMA_LONG
            ),
            int(
                Config.VOLUME_AVG_PERIOD
            ),
        )


        dataframe = (
            self._build_dataframe(
                candles,
                minimum=(
                    minimum_required
                ),
            )
        )


        close = (
            dataframe[
                "close"
            ]
            .astype(
                float
            )
        )

        volume = (
            dataframe[
                "volume"
            ]
            .astype(
                float
            )
        )


        # ====================================================
        # EMA
        # ====================================================

        ema20_series = (
            self._ema(
                close,
                Config.EMA_FAST,
            )
        )

        ema50_series = (
            self._ema(
                close,
                Config.EMA_MEDIUM,
            )
        )

        ema200_series = (
            self._ema(
                close,
                Config.EMA_LONG,
            )
        )


        # ====================================================
        # RSI
        # ====================================================

        rsi_series = (
            self._rsi(
                close,
                Config.RSI_PERIOD,
            )
        )


        # ====================================================
        # MACD
        # ====================================================

        (
            macd_line,
            macd_signal,
            macd_histogram,
        ) = (
            self._macd(
                close
            )
        )


        # ====================================================
        # ATR / ADX
        # ====================================================

        atr_series = (
            self._atr(
                dataframe,
                Config.ATR_PERIOD,
            )
        )

        (
            adx_series,
            plus_di_series,
            minus_di_series,
        ) = (
            self._adx(
                dataframe,
                Config.ADX_PERIOD,
            )
        )


        # ====================================================
        # SUPERTREND
        # ====================================================

        (
            supertrend_series,
            supertrend_direction,
        ) = (
            self._supertrend(
                dataframe
            )
        )


        # ====================================================
        # VWAP
        # ====================================================

        vwap_series = (
            self._vwap(
                dataframe
            )
        )


        # ====================================================
        # PRICE
        # ====================================================

        current_price = (
            self._series_value(
                close,
                -1,
            )
        )

        if current_price <= 0:

            raise (
                TechnicalMetricsError(
                    (
                        f"{normalized_symbol}: "
                        "invalid verified "
                        "current price."
                    )
                )
            )


        previous_1 = (
            self._series_value(
                close,
                -2,
            )
        )

        previous_5 = (
            self._series_value(
                close,
                -6,
            )
            if len(close) >= 6
            else 0.0
        )

        previous_20 = (
            self._series_value(
                close,
                -21,
            )
            if len(close) >= 21
            else 0.0
        )


        # ====================================================
        # CHANGE %
        # ====================================================

        change_1d = (
            self._change_percent(
                current_price,
                previous_1,
            )
            if previous_1 > 0
            else 0.0
        )

        change_5d = (
            self._change_percent(
                current_price,
                previous_5,
            )
            if previous_5 > 0
            else 0.0
        )

        change_20d = (
            self._change_percent(
                current_price,
                previous_20,
            )
            if previous_20 > 0
            else 0.0
        )


        # ====================================================
        # LATEST INDICATOR VALUES
        # ====================================================

        ema20 = (
            self._series_value(
                ema20_series
            )
        )

        ema50 = (
            self._series_value(
                ema50_series
            )
        )

        ema200 = (
            self._series_value(
                ema200_series
            )
        )

        rsi_value = (
            self._series_value(
                rsi_series
            )
        )

        macd_value = (
            self._series_value(
                macd_line
            )
        )

        macd_signal_value = (
            self._series_value(
                macd_signal
            )
        )

        macd_histogram_value = (
            self._series_value(
                macd_histogram
            )
        )

        atr_value = (
            self._series_value(
                atr_series
            )
        )

        adx_value = (
            self._series_value(
                adx_series
            )
        )

        plus_di = (
            self._series_value(
                plus_di_series
            )
        )

        minus_di = (
            self._series_value(
                minus_di_series
            )
        )

        supertrend_value = (
            self._series_value(
                supertrend_series
            )
        )

        supertrend_direction_value = int(
            self._series_value(
                supertrend_direction
            )
        )

        vwap_value = (
            self._series_value(
                vwap_series
            )
        )


        # ====================================================
        # VOLUME
        # ====================================================

        average_volume_series = (
            volume
            .rolling(
                window=(
                    Config
                    .VOLUME_AVG_PERIOD
                ),
                min_periods=(
                    Config
                    .VOLUME_AVG_PERIOD
                ),
            )
            .mean()
        )

        average_volume = (
            self._series_value(
                average_volume_series
            )
        )

        latest_volume = (
            self._series_value(
                volume
            )
        )

        volume_ratio = (
            latest_volume
            / average_volume
            if average_volume > 0
            else 0.0
        )

        volume_confirmed = bool(
            volume_ratio
            >= Config
            .get_min_volume_ratio(
                normalized_mode
            )
        )


        # ====================================================
        # EMA CONDITIONS
        # ====================================================

        above_ema20 = bool(
            current_price
            > ema20
        )

        above_ema50 = bool(
            current_price
            > ema50
        )

        above_ema200 = bool(
            current_price
            > ema200
        )

        ema20_above_ema50 = bool(
            ema20
            > ema50
        )

        ema50_above_ema200 = bool(
            ema50
            > ema200
        )

        bullish_ema_structure = bool(
            current_price
            > ema20
            and ema20
            > ema50
            and ema50
            > ema200
        )


        # ====================================================
        # RSI CONDITION
        # ====================================================

        rsi_valid = (
            self._rsi_valid(
                rsi_value,
                normalized_mode,
            )
        )


        # ====================================================
        # MACD CONDITION
        # ====================================================

        macd_bullish = bool(
            macd_value
            > macd_signal_value
            and macd_histogram_value
            > 0
        )


        # ====================================================
        # SUPERTREND
        # ====================================================

        supertrend_bullish = bool(
            supertrend_direction_value
            == 1
        )


        # ====================================================
        # ADX
        # ====================================================

        adx_confirmed = bool(
            adx_value
            >= Config
            .get_min_adx(
                normalized_mode
            )
        )

        positive_direction = bool(
            plus_di
            > minus_di
        )


        # ====================================================
        # VWAP
        # ====================================================

        above_vwap = bool(
            vwap_value > 0
            and current_price
            > vwap_value
        )


        # ====================================================
        # GENERIC BULLISH BREADTH
        # ====================================================

        bullish = bool(
            above_ema20
            and ema20_above_ema50
            and macd_bullish
            and supertrend_bullish
        )


        # ====================================================
        # RELATIVE STRENGTH
        # ====================================================

        benchmark_change = (
            self._number(
                benchmark_change_pct
            )
        )

        relative_strength_pct = (
            change_20d
            - benchmark_change
        )


        # ====================================================
        # RETURN
        # ====================================================

        return {
            "symbol": (
                normalized_symbol
            ),

            "mode": (
                normalized_mode
            ),

            # ------------------------------------------------
            # PRICE
            # ------------------------------------------------

            "current_price": round(
                current_price,
                2,
            ),

            # ------------------------------------------------
            # MOMENTUM
            # ------------------------------------------------

            "change_1d_pct": round(
                change_1d,
                4,
            ),

            "change_5d_pct": round(
                change_5d,
                4,
            ),

            "change_20d_pct": round(
                change_20d,
                4,
            ),

            # ------------------------------------------------
            # EMA
            # ------------------------------------------------

            "ema20": round(
                ema20,
                4,
            ),

            "ema50": round(
                ema50,
                4,
            ),

            "ema200": round(
                ema200,
                4,
            ),

            "above_ema20": (
                above_ema20
            ),

            "above_ema50": (
                above_ema50
            ),

            "above_ema200": (
                above_ema200
            ),

            "ema20_above_ema50": (
                ema20_above_ema50
            ),

            "ema50_above_ema200": (
                ema50_above_ema200
            ),

            "bullish_ema_structure": (
                bullish_ema_structure
            ),

            # ------------------------------------------------
            # RSI
            # ------------------------------------------------

            "rsi": round(
                rsi_value,
                4,
            ),

            "rsi_valid": (
                rsi_valid
            ),

            # ------------------------------------------------
            # MACD
            # ------------------------------------------------

            "macd": round(
                macd_value,
                6,
            ),

            "macd_signal": round(
                macd_signal_value,
                6,
            ),

            "macd_histogram": round(
                macd_histogram_value,
                6,
            ),

            "macd_bullish": (
                macd_bullish
            ),

            # ------------------------------------------------
            # ATR
            # ------------------------------------------------

            "atr": round(
                atr_value,
                4,
            ),

            # ------------------------------------------------
            # ADX
            # ------------------------------------------------

            "adx": round(
                adx_value,
                4,
            ),

            "plus_di": round(
                plus_di,
                4,
            ),

            "minus_di": round(
                minus_di,
                4,
            ),

            "adx_confirmed": (
                adx_confirmed
            ),

            "positive_direction": (
                positive_direction
            ),

            # ------------------------------------------------
            # SUPERTREND
            # ------------------------------------------------

            "supertrend": round(
                supertrend_value,
                4,
            ),

            "supertrend_direction": (
                supertrend_direction_value
            ),

            # Both names provided intentionally.
            # sector_scanner currently uses supertrend_buy.
            "supertrend_buy": (
                supertrend_bullish
            ),

            "supertrend_bullish": (
                supertrend_bullish
            ),

            # ------------------------------------------------
            # VWAP
            # ------------------------------------------------

            "vwap": round(
                vwap_value,
                4,
            ),

            "above_vwap": (
                above_vwap
            ),

            # ------------------------------------------------
            # VOLUME
            # ------------------------------------------------

            "latest_volume": round(
                latest_volume,
                2,
            ),

            "average_volume": round(
                average_volume,
                2,
            ),

            "volume_ratio": round(
                volume_ratio,
                4,
            ),

            "volume_confirmed": (
                volume_confirmed
            ),

            # ------------------------------------------------
            # RELATIVE STRENGTH
            # ------------------------------------------------

            "benchmark_change_pct": round(
                benchmark_change,
                4,
            ),

            "relative_strength_pct": round(
                relative_strength_pct,
                4,
            ),

            "relative_strength_bullish": bool(
                relative_strength_pct
                >= Config
                .MIN_RELATIVE_STRENGTH_PCT
            ),

            # ------------------------------------------------
            # BREADTH
            # ------------------------------------------------

            "bullish": (
                bullish
            ),

            # ------------------------------------------------
            # VERIFICATION
            # ------------------------------------------------

            "verified": True,

            "source": "FYERS",

            "candle_count": len(
                dataframe
            ),

            "generated_at": (
                utc_now()
                .isoformat()
            ),
        }


    # ========================================================
    # STOCK METRICS FROM FYERS
    # ========================================================

    def build_stock_metrics(
        self,
        access_token: str,
        *,
        symbol: str,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:

        normalized_symbol = (
            normalize_symbol(
                symbol
            )
        )

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

        if not normalized_symbol:

            raise ValueError(
                (
                    "Valid stock symbol "
                    "is required."
                )
            )


        # ====================================================
        # MARKET DATA
        # ====================================================

        mode_data = (
            self
            .market_data_service
            .get_mode_market_data(
                access_token,
                normalized_symbol,
                mode=(
                    normalized_mode
                ),
                force_refresh=(
                    force_refresh
                ),
            )
        )

        if not isinstance(
            mode_data,
            dict,
        ):

            raise (
                TechnicalMetricsError(
                    (
                        f"{normalized_symbol}: "
                        "market-data response "
                        "is invalid."
                    )
                )
            )


        if not bool(
            mode_data.get(
                "verified",
                False,
            )
        ):

            raise (
                TechnicalMetricsError(
                    (
                        f"{normalized_symbol}: "
                        "unverified market data "
                        "was rejected."
                    )
                )
            )


        primary = (
            mode_data.get(
                "primary",
                [],
            )
        )

        confirmation = (
            mode_data.get(
                "confirmation",
                [],
            )
        )

        higher = (
            mode_data.get(
                "higher_timeframe",
                [],
            )
        )


        if not isinstance(
            primary,
            list,
        ):

            primary = []

        if not isinstance(
            confirmation,
            list,
        ):

            confirmation = []

        if not isinstance(
            higher,
            list,
        ):

            higher = []


        if not primary:

            raise (
                TechnicalMetricsError(
                    (
                        f"{normalized_symbol}: "
                        "primary candles "
                        "are unavailable."
                    )
                )
            )


        # ====================================================
        # PRIMARY METRICS
        # ====================================================

        metrics = (
            self
            .build_metrics_from_candles(
                symbol=(
                    normalized_symbol
                ),
                candles=(
                    primary
                ),
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
                mode=(
                    normalized_mode
                ),
            )
        )


        # ====================================================
        # CONFIRMATION TIMEFRAME
        # ====================================================

        confirmation_summary: dict[
            str,
            Any,
        ] = {
            "score": 0.0,
            "bullish": False,
        }

        if confirmation:

            try:

                confirmation_summary = (
                    self
                    ._timeframe_summary(
                        candles=(
                            confirmation
                        ),
                        mode=(
                            normalized_mode
                        ),
                    )
                )

            except Exception as exception:

                logger.warning(
                    (
                        "Confirmation timeframe "
                        "metrics unavailable | "
                        "symbol=%s | mode=%s | %s"
                    ),
                    normalized_symbol,
                    normalized_mode,
                    exception,
                )


        # ====================================================
        # HIGHER TIMEFRAME
        # ====================================================

        higher_summary: dict[
            str,
            Any,
        ] = {
            "score": 0.0,
            "bullish": False,
        }

        if higher:

            try:

                higher_summary = (
                    self
                    ._timeframe_summary(
                        candles=(
                            higher
                        ),
                        mode=(
                            normalized_mode
                        ),
                    )
                )

            except Exception as exception:

                logger.warning(
                    (
                        "Higher timeframe "
                        "metrics unavailable | "
                        "symbol=%s | mode=%s | %s"
                    ),
                    normalized_symbol,
                    normalized_mode,
                    exception,
                )


        confirmation_bullish = bool(
            confirmation_summary.get(
                "bullish",
                False,
            )
        )

        higher_bullish = bool(
            higher_summary.get(
                "bullish",
                False,
            )
        )

        primary_bullish = bool(
            metrics.get(
                "bullish",
                False,
            )
        )


        # ====================================================
        # MULTI-TIMEFRAME
        # ====================================================

        multi_timeframe_confirmed = bool(
            primary_bullish
            and confirmation_bullish
            and higher_bullish
        )


        # ====================================================
        # MODE DATA
        # ====================================================

        metrics[
            "mode"
        ] = (
            normalized_mode
        )

        metrics[
            "primary_resolution"
        ] = (
            mode_data.get(
                "primary_resolution"
            )
            or Config
            .get_primary_resolution(
                normalized_mode
            )
        )

        metrics[
            "confirmation_resolution"
        ] = (
            mode_data.get(
                "confirmation_resolution"
            )
            or Config
            .get_confirmation_resolution(
                normalized_mode
            )
        )

        metrics[
            "higher_resolution"
        ] = (
            mode_data.get(
                "higher_resolution"
            )
            or Config
            .get_higher_timeframe_resolution(
                normalized_mode
            )
        )


        # ====================================================
        # TIMEFRAME SCORES
        # ====================================================

        metrics[
            "primary_bullish"
        ] = (
            primary_bullish
        )

        metrics[
            "confirmation_bullish"
        ] = (
            confirmation_bullish
        )

        metrics[
            "higher_timeframe_bullish"
        ] = (
            higher_bullish
        )

        metrics[
            "multi_timeframe_confirmed"
        ] = (
            multi_timeframe_confirmed
        )

        metrics[
            "confirmation_score"
        ] = round(
            self._number(
                confirmation_summary.get(
                    "score"
                )
            ),
            2,
        )

        metrics[
            "higher_timeframe_score"
        ] = round(
            self._number(
                higher_summary.get(
                    "score"
                )
            ),
            2,
        )

        metrics[
            "confirmation_metrics"
        ] = (
            confirmation_summary
        )

        metrics[
            "higher_timeframe_metrics"
        ] = (
            higher_summary
        )

        metrics[
            "primary_candle_count"
        ] = len(
            primary
        )

        metrics[
            "confirmation_candle_count"
        ] = len(
            confirmation
        )

        metrics[
            "higher_timeframe_candle_count"
        ] = len(
            higher
        )

        metrics[
            "market_data_verified"
        ] = True

        metrics[
            "verified"
        ] = True

        metrics[
            "source"
        ] = "FYERS"

        metrics[
            "generated_at"
        ] = (
            utc_now()
            .isoformat()
        )


        return metrics


    # ========================================================
    # BULK METRICS
    # ========================================================

    def build_metrics_for_stocks(
        self,
        access_token: str,
        stocks: Iterable[
            Any
        ],
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[
        str,
        dict[str, Any],
    ]:

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

        results: dict[
            str,
            dict[str, Any],
        ] = {}

        seen_symbols: set[
            str
        ] = set()

        success_count = 0

        failure_count = 0


        for stock in stocks:

            if isinstance(
                stock,
                dict,
            ):

                raw_symbol = (
                    stock.get(
                        "symbol"
                    )
                )

            else:

                raw_symbol = (
                    getattr(
                        stock,
                        "symbol",
                        "",
                    )
                )


            symbol = (
                normalize_symbol(
                    raw_symbol
                )
            )

            if not symbol:

                continue

            if symbol in seen_symbols:

                continue

            seen_symbols.add(
                symbol
            )


            try:

                metrics = (
                    self
                    .build_stock_metrics(
                        access_token,
                        symbol=(
                            symbol
                        ),
                        mode=(
                            normalized_mode
                        ),
                        benchmark_change_pct=(
                            benchmark_change_pct
                        ),
                        force_refresh=(
                            force_refresh
                        ),
                    )
                )


                if not isinstance(
                    metrics,
                    dict,
                ):

                    failure_count += 1

                    continue


                if not bool(
                    metrics.get(
                        "verified",
                        False,
                    )
                ):

                    failure_count += 1

                    continue


                current_price = (
                    safe_float(
                        metrics.get(
                            "current_price"
                        )
                    )
                )

                if (
                    current_price is None
                    or current_price <= 0
                ):

                    failure_count += 1

                    continue


                results[
                    symbol
                ] = (
                    metrics
                )

                success_count += 1


            except Exception as exception:

                failure_count += 1

                log_exception(
                    logger,
                    (
                        "Technical metric "
                        "generation failed"
                    ),
                    exception=(
                        exception
                    ),
                    symbol=(
                        symbol
                    ),
                    component=(
                        "technical_metrics_service"
                    ),
                    error_code=(
                        "TECHNICAL_METRICS_FAILED"
                    ),
                    mode=(
                        normalized_mode
                    ),
                )


        logger.info(
            (
                "Technical metrics completed | "
                "mode=%s | requested=%s | "
                "success=%s | failed=%s"
            ),
            normalized_mode,
            len(
                seen_symbols
            ),
            success_count,
            failure_count,
        )


        return results


    # ========================================================
    # ONE SYMBOL
    # ========================================================

    def get_metrics(
        self,
        access_token: str,
        *,
        symbol: str,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:

        return (
            self
            .build_stock_metrics(
                access_token,
                symbol=(
                    symbol
                ),
                mode=(
                    mode
                ),
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
                force_refresh=(
                    force_refresh
                ),
            )
        )


    # ========================================================
    # HEALTH
    # ========================================================

    def health(
        self,
    ) -> dict[str, Any]:

        return {
            "service": (
                "Technical Metrics Service"
            ),

            "status": "healthy",

            "technical_only": True,

            "fake_data_allowed": bool(
                Config.ALLOW_FAKE_DATA
            ),

            "source": "FYERS",

            "supported_modes": list(
                Config
                .SUPPORTED_TRADING_MODES
            ),

            "top_sectors": int(
                Config.TOP_SECTORS_COUNT
            ),

            "top_stocks_per_sector": int(
                Config.TOP_STOCKS_PER_SECTOR
            ),

            "maximum_candidate_universe": int(
                Config.MAX_SCANNER_UNIVERSE
            ),

            "indicators": [
                "EMA20",
                "EMA50",
                "EMA200",
                "RSI",
                "MACD",
                "ATR",
                "ADX",
                "Supertrend",
                "VWAP",
                "Volume",
                "Relative Strength",
                "Multi Timeframe",
            ],

            "multi_timeframe": True,

            "sector_scanner_compatible": True,

            "btst_supported": True,

            "checked_at": (
                utc_now()
                .isoformat()
            ),
        }


# ============================================================
# GLOBAL INSTANCE
# ============================================================


_global_technical_metrics_service: (
    TechnicalMetricsService
    | None
) = None


_global_technical_metrics_lock = (
    threading.Lock()
)


# ============================================================
# GET SERVICE
# ============================================================


def get_technical_metrics_service(
) -> TechnicalMetricsService:

    global _global_technical_metrics_service

    if (
        _global_technical_metrics_service
        is not None
    ):

        return (
            _global_technical_metrics_service
        )


    with (
        _global_technical_metrics_lock
    ):

        if (
            _global_technical_metrics_service
            is None
        ):

            _global_technical_metrics_service = (
                TechnicalMetricsService()
            )


    return (
        _global_technical_metrics_service
    )
