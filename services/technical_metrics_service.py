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
    cannot be created.

    No fake or fabricated metrics are generated.
    """


# ============================================================
# TECHNICAL METRICS SERVICE
# ============================================================

class TechnicalMetricsService:
    """
    Technical-only ranking metrics service.

    Used for:

        NSE sector ranking
        Top-stock ranking
        Candidate universe creation

    Final STRONG BUY is NOT generated here.
    It belongs to scanners/technical_scanner.py.

    ----------------------------------------------------------
    EXPECTED MODE DATA
    ----------------------------------------------------------

    Intraday:
        primary           = 5 minute
        confirmation      = 15 minute
        higher_timeframe  = Daily

    BTST:
        primary           = 15 minute
        confirmation      = 60 minute
        higher_timeframe  = Daily

    Swing:
        primary           = Daily
        confirmation      = Weekly
        higher_timeframe  = Weekly

    ----------------------------------------------------------
    OUTPUT INCLUDES
    ----------------------------------------------------------

        EMA
        RSI
        MACD
        Supertrend
        ADX
        Volume
        Momentum
        Relative Strength
        Confirmation trend
        Higher timeframe trend
        Multi-timeframe confirmation

    No fundamentals.
    No synthetic OHLCV.
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(
        self,
        *,
        market_data_service: (
            MarketDataService | None
        ) = None,
    ) -> None:

        self.market_data_service = (
            market_data_service
            or get_market_data_service()
        )

    # ========================================================
    # MODE HELPERS
    # ========================================================

    @staticmethod
    def _normalize_mode(
        mode: str | None,
    ) -> str:

        return (
            Config.normalize_trading_mode(
                mode
                or Config.DEFAULT_TRADING_MODE
            )
        )

    @staticmethod
    def _is_btst(
        mode: str,
    ) -> bool:

        btst_mode = getattr(
            Config,
            "MODE_BTST",
            "btst",
        )

        return (
            str(mode).strip().lower()
            == str(btst_mode).strip().lower()
        )

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

            raise TechnicalMetricsError(
                "Verified candle data must be a list."
            )

        if not candles:

            raise TechnicalMetricsError(
                "Verified candle data is unavailable."
            )

        dataframe = pd.DataFrame(
            candles
        )

        required_columns = {
            "open",
            "high",
            "low",
            "close",
            "volume",
        }

        if not required_columns.issubset(
            dataframe.columns
        ):

            raise TechnicalMetricsError(
                "Required OHLCV columns are missing."
            )

        for column in (
            "open",
            "high",
            "low",
            "close",
            "volume",
        ):

            dataframe[
                column
            ] = pd.to_numeric(
                dataframe[
                    column
                ],
                errors="coerce",
            )

        if (
            "timestamp"
            in dataframe.columns
        ):

            dataframe[
                "timestamp"
            ] = pd.to_numeric(
                dataframe[
                    "timestamp"
                ],
                errors="coerce",
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
            .fillna(0.0)
        )

        # ----------------------------------------------------
        # VALID PRICE
        # ----------------------------------------------------

        dataframe = dataframe[
            (
                dataframe["open"] > 0
            )
            & (
                dataframe["high"] > 0
            )
            & (
                dataframe["low"] > 0
            )
            & (
                dataframe["close"] > 0
            )
            & (
                dataframe["volume"] >= 0
            )
        ].copy()

        # ----------------------------------------------------
        # VALID OHLC STRUCTURE
        # ----------------------------------------------------

        dataframe = dataframe[
            (
                dataframe["high"]
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
                dataframe["low"]
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
            len(dataframe)
            < minimum
        ):

            raise TechnicalMetricsError(
                (
                    "Insufficient verified candles. "
                    f"{len(dataframe)} available; "
                    f"{minimum} required."
                )
            )

        return dataframe

    # ========================================================
    # SAFE VALUE
    # ========================================================

    @staticmethod
    def _value(
        value: Any,
        default: float = 0.0,
    ) -> float:

        result = safe_float(
            value,
            default=default,
        )

        return float(
            result
            if result is not None
            else default
        )

    @classmethod
    def _series_value(
        cls,
        series: pd.Series,
        position: int = -1,
        default: float = 0.0,
    ) -> float:

        try:

            return cls._value(
                series.iloc[
                    position
                ],
                default,
            )

        except (
            IndexError,
            TypeError,
        ):

            return float(
                default
            )

    # ========================================================
    # EMA
    # ========================================================

    @staticmethod
    def _ema(
        series: pd.Series,
        period: int,
    ) -> pd.Series:

        return series.ewm(
            span=int(
                period
            ),
            adjust=False,
        ).mean()

    # ========================================================
    # RSI
    # ========================================================

    @staticmethod
    def _rsi(
        series: pd.Series,
        period: int,
    ) -> pd.Series:

        delta = series.diff()

        gain = delta.clip(
            lower=0.0
        )

        loss = (
            -delta.clip(
                upper=0.0
            )
        )

        average_gain = gain.ewm(
            alpha=(
                1.0
                / float(
                    period
                )
            ),
            adjust=False,
        ).mean()

        average_loss = loss.ewm(
            alpha=(
                1.0
                / float(
                    period
                )
            ),
            adjust=False,
        ).mean()

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
                    1.0 + rs
                )
            )
        )

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

        return rsi.fillna(
            50.0
        )

    # ========================================================
    # MACD
    # ========================================================

    @staticmethod
    def _macd(
        series: pd.Series,
    ) -> tuple[
        pd.Series,
        pd.Series,
        pd.Series,
    ]:

        fast = series.ewm(
            span=int(
                Config.MACD_FAST
            ),
            adjust=False,
        ).mean()

        slow = series.ewm(
            span=int(
                Config.MACD_SLOW
            ),
            adjust=False,
        ).mean()

        macd_line = (
            fast
            - slow
        )

        signal_line = (
            macd_line
            .ewm(
                span=int(
                    Config.MACD_SIGNAL
                ),
                adjust=False,
            )
            .mean()
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
    # ATR / TRUE RANGE
    # ========================================================

    @staticmethod
    def _true_range(
        dataframe: pd.DataFrame,
    ) -> pd.Series:

        previous_close = (
            dataframe[
                "close"
            ]
            .shift(1)
        )

        return pd.concat(
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
        ).max(
            axis=1
        )

    @classmethod
    def _atr(
        cls,
        dataframe: pd.DataFrame,
        period: int,
    ) -> pd.Series:

        true_range = (
            cls._true_range(
                dataframe
            )
        )

        return true_range.ewm(
            alpha=(
                1.0
                / float(
                    period
                )
            ),
            adjust=False,
        ).mean()

    # ========================================================
    # ADX
    # ========================================================

    @classmethod
    def _adx(
        cls,
        dataframe: pd.DataFrame,
        period: int = 14,
    ) -> pd.Series:

        high = dataframe[
            "high"
        ]

        low = dataframe[
            "low"
        ]

        up_move = (
            high.diff()
        )

        down_move = (
            -low.diff()
        )

        plus_dm = pd.Series(
            np.where(
                (
                    up_move > down_move
                )
                & (
                    up_move > 0
                ),
                up_move,
                0.0,
            ),
            index=dataframe.index,
            dtype=float,
        )

        minus_dm = pd.Series(
            np.where(
                (
                    down_move > up_move
                )
                & (
                    down_move > 0
                ),
                down_move,
                0.0,
            ),
            index=dataframe.index,
            dtype=float,
        )

        atr = (
            cls._atr(
                dataframe,
                period,
            )
            .replace(
                0.0,
                np.nan,
            )
        )

        plus_di = (
            100.0
            * plus_dm.ewm(
                alpha=(
                    1.0
                    / period
                ),
                adjust=False,
            ).mean()
            / atr
        )

        minus_di = (
            100.0
            * minus_dm.ewm(
                alpha=(
                    1.0
                    / period
                ),
                adjust=False,
            ).mean()
            / atr
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

        adx = dx.ewm(
            alpha=(
                1.0
                / period
            ),
            adjust=False,
        ).mean()

        return adx.fillna(
            0.0
        )

    # ========================================================
    # SUPERTREND
    # ========================================================

    @classmethod
    def _supertrend_direction(
        cls,
        dataframe: pd.DataFrame,
    ) -> pd.Series:

        period = int(
            Config.SUPERTREND_PERIOD
        )

        multiplier = float(
            Config
            .SUPERTREND_MULTIPLIER
        )

        atr = cls._atr(
            dataframe,
            period,
        )

        hl2 = (
            dataframe["high"]
            + dataframe["low"]
        ) / 2.0

        upper_band = (
            hl2
            + multiplier
            * atr
        )

        lower_band = (
            hl2
            - multiplier
            * atr
        )

        final_upper = (
            upper_band.copy()
        )

        final_lower = (
            lower_band.copy()
        )

        close = dataframe[
            "close"
        ]

        for index in range(
            1,
            len(dataframe),
        ):

            previous_close = (
                close.iloc[
                    index - 1
                ]
            )

            previous_upper = (
                final_upper.iloc[
                    index - 1
                ]
            )

            previous_lower = (
                final_lower.iloc[
                    index - 1
                ]
            )

            if (
                upper_band.iloc[index]
                < previous_upper
                or previous_close
                > previous_upper
            ):

                final_upper.iloc[
                    index
                ] = upper_band.iloc[
                    index
                ]

            else:

                final_upper.iloc[
                    index
                ] = previous_upper

            if (
                lower_band.iloc[index]
                > previous_lower
                or previous_close
                < previous_lower
            ):

                final_lower.iloc[
                    index
                ] = lower_band.iloc[
                    index
                ]

            else:

                final_lower.iloc[
                    index
                ] = previous_lower

        direction = pd.Series(
            1,
            index=dataframe.index,
            dtype=int,
        )

        for index in range(
            1,
            len(dataframe),
        ):

            previous_direction = (
                int(
                    direction.iloc[
                        index - 1
                    ]
                )
            )

            if (
                previous_direction
                >= 0
            ):

                if (
                    close.iloc[index]
                    < final_lower.iloc[index]
                ):

                    direction.iloc[
                        index
                    ] = -1

                else:

                    direction.iloc[
                        index
                    ] = 1

            else:

                if (
                    close.iloc[index]
                    > final_upper.iloc[index]
                ):

                    direction.iloc[
                        index
                    ] = 1

                else:

                    direction.iloc[
                        index
                    ] = -1

        return direction

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
    # RSI VALID
    # ========================================================

    def _rsi_valid(
        self,
        rsi_value: float,
        mode: str,
    ) -> bool:

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        if (
            normalized_mode
            == Config.MODE_INTRADAY
        ):

            minimum = float(
                Config.INTRADAY_RSI_MIN
            )

            maximum = float(
                Config.INTRADAY_RSI_MAX
            )

        elif self._is_btst(
            normalized_mode
        ):

            minimum = float(
                getattr(
                    Config,
                    "BTST_RSI_MIN",
                    52.0,
                )
            )

            maximum = float(
                getattr(
                    Config,
                    "BTST_RSI_MAX",
                    75.0,
                )
            )

        else:

            minimum = float(
                Config.SWING_RSI_MIN
            )

            maximum = float(
                Config.SWING_RSI_MAX
            )

        return bool(
            minimum
            <= rsi_value
            <= maximum
        )

    # ========================================================
    # MIN VOLUME RATIO
    # ========================================================

    def _minimum_volume_ratio(
        self,
        mode: str,
    ) -> float:

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        if self._is_btst(
            normalized_mode
        ):

            return float(
                getattr(
                    Config,
                    "BTST_MIN_VOLUME_RATIO",
                    1.20,
                )
            )

        return float(
            Config.get_min_volume_ratio(
                normalized_mode
            )
        )

    # ========================================================
    # ONE TIMEFRAME METRICS
    # ========================================================

    def _build_timeframe_metrics(
        self,
        *,
        candles: list[
            dict[str, Any]
        ],
        mode: str,
        require_ema200: bool,
        minimum: int,
    ) -> dict[str, Any]:

        dataframe = (
            self._build_dataframe(
                candles,
                minimum=(
                    minimum
                ),
            )
        )

        close = dataframe[
            "close"
        ].astype(
            float
        )

        volume = dataframe[
            "volume"
        ].astype(
            float
        )

        # ----------------------------------------------------
        # INDICATORS
        # ----------------------------------------------------

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

        supertrend_direction = (
            self._supertrend_direction(
                dataframe
            )
        )

        adx_series = (
            self._adx(
                dataframe,
                int(
                    getattr(
                        Config,
                        "ADX_PERIOD",
                        14,
                    )
                ),
            )
        )

        # ----------------------------------------------------
        # VALUES
        # ----------------------------------------------------

        current_price = (
            self._series_value(
                close
            )
        )

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

        rsi = (
            self._series_value(
                rsi_series,
                default=50.0,
            )
        )

        macd = (
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

        supertrend_value = int(
            self._series_value(
                supertrend_direction,
                default=0.0,
            )
        )

        adx = (
            self._series_value(
                adx_series
            )
        )

        # ----------------------------------------------------
        # TREND
        # ----------------------------------------------------

        above_ema20 = bool(
            current_price
            > ema20
            > 0
        )

        above_ema50 = bool(
            current_price
            > ema50
            > 0
        )

        above_ema200 = bool(
            current_price
            > ema200
            > 0
        )

        if require_ema200:

            ema_bullish = bool(
                current_price
                > ema20
                > ema50
                > ema200
                > 0
            )

        else:

            ema_bullish = bool(
                current_price
                > ema20
                > ema50
                > 0
            )

        macd_bullish = bool(
            macd
            > macd_signal_value
            and macd_histogram_value
            > 0
        )

        supertrend_buy = bool(
            supertrend_value
            == 1
        )

        rsi_valid = (
            self._rsi_valid(
                rsi,
                mode,
            )
        )

        adx_bullish = bool(
            adx
            >= float(
                getattr(
                    Config,
                    "MIN_ADX",
                    20.0,
                )
            )
        )

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        average_volume_series = (
            volume.rolling(
                window=int(
                    Config
                    .VOLUME_AVG_PERIOD
                ),
                min_periods=int(
                    Config
                    .VOLUME_AVG_PERIOD
                ),
            ).mean()
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
            >= self._minimum_volume_ratio(
                mode
            )
        )

        # ----------------------------------------------------
        # SUMMARY SCORE
        # ----------------------------------------------------

        score = 0.0

        if ema_bullish:
            score += 35.0

        if macd_bullish:
            score += 20.0

        if supertrend_buy:
            score += 20.0

        if rsi_valid:
            score += 10.0

        if adx_bullish:
            score += 10.0

        if volume_confirmed:
            score += 5.0

        bullish = bool(
            score
            >= 65.0
        )

        return {
            "current_price": (
                current_price
            ),

            "ema20": (
                ema20
            ),

            "ema50": (
                ema50
            ),

            "ema200": (
                ema200
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

            "ema_bullish": (
                ema_bullish
            ),

            "rsi": (
                rsi
            ),

            "rsi_valid": (
                rsi_valid
            ),

            "macd": (
                macd
            ),

            "macd_signal": (
                macd_signal_value
            ),

            "macd_histogram": (
                macd_histogram_value
            ),

            "macd_bullish": (
                macd_bullish
            ),

            "supertrend_buy": (
                supertrend_buy
            ),

            "adx": (
                adx
            ),

            "adx_bullish": (
                adx_bullish
            ),

            "latest_volume": (
                latest_volume
            ),

            "average_volume": (
                average_volume
            ),

            "volume_ratio": (
                volume_ratio
            ),

            "volume_confirmed": (
                volume_confirmed
            ),

            "score": (
                min(
                    100.0,
                    max(
                        0.0,
                        score,
                    ),
                )
            ),

            "bullish": (
                bullish
            ),

            "candle_count": (
                len(
                    dataframe
                )
            ),
        }

    # ========================================================
    # PRIMARY RANKING METRICS
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

        if not normalized_symbol:

            raise ValueError(
                "Valid stock symbol is required."
            )

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        minimum_required = max(
            int(
                Config.EMA_LONG
            ),
            int(
                Config.VOLUME_AVG_PERIOD
            ),
            30,
        )

        dataframe = (
            self._build_dataframe(
                candles,
                minimum=(
                    minimum_required
                ),
            )
        )

        close = dataframe[
            "close"
        ].astype(
            float
        )

        primary = (
            self._build_timeframe_metrics(
                candles=(
                    candles
                ),
                mode=(
                    normalized_mode
                ),
                require_ema200=True,
                minimum=(
                    minimum_required
                ),
            )
        )

        current_price = float(
            primary[
                "current_price"
            ]
        )

        previous_1 = (
            self._series_value(
                close,
                -2,
            )
            if len(close) >= 2
            else 0.0
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

        change_1d = (
            self._change_percent(
                current_price,
                previous_1,
            )
        )

        change_5d = (
            self._change_percent(
                current_price,
                previous_5,
            )
        )

        change_20d = (
            self._change_percent(
                current_price,
                previous_20,
            )
        )

        benchmark_change = (
            self._value(
                benchmark_change_pct
            )
        )

        relative_strength_pct = (
            change_20d
            - benchmark_change
        )

        return {
            "symbol": (
                normalized_symbol
            ),

            "mode": (
                normalized_mode
            ),

            "current_price": round(
                current_price,
                2,
            ),

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

            "ema20": round(
                primary["ema20"],
                4,
            ),

            "ema50": round(
                primary["ema50"],
                4,
            ),

            "ema200": round(
                primary["ema200"],
                4,
            ),

            "above_ema20": bool(
                primary[
                    "above_ema20"
                ]
            ),

            "above_ema50": bool(
                primary[
                    "above_ema50"
                ]
            ),

            "above_ema200": bool(
                primary[
                    "above_ema200"
                ]
            ),

            "bullish_ema_structure": bool(
                primary[
                    "ema_bullish"
                ]
            ),

            "rsi": round(
                primary["rsi"],
                4,
            ),

            "rsi_valid": bool(
                primary[
                    "rsi_valid"
                ]
            ),

            "macd": round(
                primary["macd"],
                6,
            ),

            "macd_signal": round(
                primary[
                    "macd_signal"
                ],
                6,
            ),

            "macd_histogram": round(
                primary[
                    "macd_histogram"
                ],
                6,
            ),

            "macd_bullish": bool(
                primary[
                    "macd_bullish"
                ]
            ),

            "supertrend_buy": bool(
                primary[
                    "supertrend_buy"
                ]
            ),

            "adx": round(
                primary["adx"],
                4,
            ),

            "adx_bullish": bool(
                primary[
                    "adx_bullish"
                ]
            ),

            "latest_volume": round(
                primary[
                    "latest_volume"
                ],
                2,
            ),

            "average_volume": round(
                primary[
                    "average_volume"
                ],
                2,
            ),

            "volume_ratio": round(
                primary[
                    "volume_ratio"
                ],
                4,
            ),

            "volume_confirmed": bool(
                primary[
                    "volume_confirmed"
                ]
            ),

            "benchmark_change_pct": round(
                benchmark_change,
                4,
            ),

            "relative_strength_pct": round(
                relative_strength_pct,
                4,
            ),

            "primary_score": round(
                primary["score"],
                2,
            ),

            "primary_bullish": bool(
                primary[
                    "bullish"
                ]
            ),

            # Generic field consumed by sector/stock ranking.
            "bullish": bool(
                primary[
                    "bullish"
                ]
            ),

            "verified": True,

            "source": "FYERS",

            "candle_count": int(
                primary[
                    "candle_count"
                ]
            ),
        }

    # ========================================================
    # BUILD STOCK METRICS
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

        if not normalized_symbol:

            raise ValueError(
                "Valid stock symbol is required."
            )

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        mode_data = (
            self.market_data_service
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

            raise TechnicalMetricsError(
                (
                    f"{normalized_symbol}: "
                    "invalid market-data response."
                )
            )

        if not bool(
            mode_data.get(
                "verified"
            )
        ):

            raise TechnicalMetricsError(
                (
                    f"{normalized_symbol}: "
                    "unverified market data rejected."
                )
            )

        primary = (
            mode_data.get(
                "primary"
            )
        )

        confirmation = (
            mode_data.get(
                "confirmation"
            )
        )

        higher = (
            mode_data.get(
                "higher_timeframe"
            )
        )

        if not isinstance(
            primary,
            list,
        ) or not primary:

            raise TechnicalMetricsError(
                (
                    f"{normalized_symbol}: "
                    "primary candles unavailable."
                )
            )

        if not isinstance(
            confirmation,
            list,
        ) or not confirmation:

            raise TechnicalMetricsError(
                (
                    f"{normalized_symbol}: "
                    "confirmation candles unavailable."
                )
            )

        if not isinstance(
            higher,
            list,
        ) or not higher:

            raise TechnicalMetricsError(
                (
                    f"{normalized_symbol}: "
                    "higher timeframe candles unavailable."
                )
            )

        # ====================================================
        # PRIMARY
        # ====================================================

        metrics = (
            self.build_metrics_from_candles(
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
        # CONFIRMATION
        # ====================================================

        confirmation_require_ema200 = bool(
            len(
                confirmation
            )
            >= int(
                Config.EMA_LONG
            )
        )

        confirmation_metrics = (
            self._build_timeframe_metrics(
                candles=(
                    confirmation
                ),
                mode=(
                    normalized_mode
                ),
                require_ema200=(
                    confirmation_require_ema200
                ),
                minimum=30,
            )
        )

        # ====================================================
        # HIGHER TIMEFRAME
        # ====================================================

        higher_require_ema200 = bool(
            len(
                higher
            )
            >= int(
                Config.EMA_LONG
            )
        )

        higher_metrics = (
            self._build_timeframe_metrics(
                candles=(
                    higher
                ),
                mode=(
                    normalized_mode
                ),
                require_ema200=(
                    higher_require_ema200
                ),
                minimum=30,
            )
        )

        confirmation_bullish = bool(
            confirmation_metrics[
                "bullish"
            ]
        )

        higher_bullish = bool(
            higher_metrics[
                "bullish"
            ]
        )

        primary_bullish = bool(
            metrics[
                "primary_bullish"
            ]
        )

        # ====================================================
        # MULTI TIMEFRAME
        # ====================================================

        if (
            normalized_mode
            == Config.MODE_INTRADAY
        ):

            multi_confirmed = bool(
                primary_bullish
                and confirmation_bullish
                and higher_bullish
            )

        elif self._is_btst(
            normalized_mode
        ):

            multi_confirmed = bool(
                primary_bullish
                and confirmation_bullish
                and higher_bullish
            )

        else:

            # Swing:
            # Daily + Weekly confirmation.
            multi_confirmed = bool(
                primary_bullish
                and confirmation_bullish
            )

        # ====================================================
        # ADD MULTI-TIMEFRAME FIELDS
        # ====================================================

        metrics.update(
            {
                "confirmation_score": round(
                    confirmation_metrics[
                        "score"
                    ],
                    2,
                ),

                "confirmation_bullish": (
                    confirmation_bullish
                ),

                "confirmation_rsi": round(
                    confirmation_metrics[
                        "rsi"
                    ],
                    4,
                ),

                "confirmation_macd_bullish": bool(
                    confirmation_metrics[
                        "macd_bullish"
                    ]
                ),

                "confirmation_supertrend_buy": bool(
                    confirmation_metrics[
                        "supertrend_buy"
                    ]
                ),

                "confirmation_adx": round(
                    confirmation_metrics[
                        "adx"
                    ],
                    4,
                ),

                "higher_timeframe_score": round(
                    higher_metrics[
                        "score"
                    ],
                    2,
                ),

                "higher_timeframe_bullish": (
                    higher_bullish
                ),

                "higher_timeframe_rsi": round(
                    higher_metrics[
                        "rsi"
                    ],
                    4,
                ),

                "higher_timeframe_macd_bullish": bool(
                    higher_metrics[
                        "macd_bullish"
                    ]
                ),

                "higher_timeframe_supertrend_buy": bool(
                    higher_metrics[
                        "supertrend_buy"
                    ]
                ),

                "higher_timeframe_adx": round(
                    higher_metrics[
                        "adx"
                    ],
                    4,
                ),

                "multi_timeframe_confirmed": (
                    multi_confirmed
                ),

                "primary_resolution": (
                    mode_data.get(
                        "primary_resolution"
                    )
                    or Config
                    .get_primary_resolution(
                        normalized_mode
                    )
                ),

                "confirmation_resolution": (
                    mode_data.get(
                        "confirmation_resolution"
                    )
                    or Config
                    .get_confirmation_resolution(
                        normalized_mode
                    )
                ),

                "higher_resolution": (
                    mode_data.get(
                        "higher_resolution"
                    )
                ),

                "primary_candle_count": (
                    len(
                        primary
                    )
                ),

                "confirmation_candle_count": (
                    len(
                        confirmation
                    )
                ),

                "higher_timeframe_candle_count": (
                    len(
                        higher
                    )
                ),

                "market_data_verified": True,

                "verified": True,

                "source": "FYERS",

                "updated_at": (
                    utc_now().isoformat()
                ),
            }
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
            self._normalize_mode(
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

                raw_symbol = getattr(
                    stock,
                    "symbol",
                    "",
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
                    self.build_stock_metrics(
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
                        "verified"
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
                ] = metrics

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
    # ONE STOCK
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
            self.build_stock_metrics(
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

            "is_healthy": True,

            "technical_only": True,

            "fake_data_allowed": bool(
                Config.ALLOW_FAKE_DATA
            ),

            "top_sectors": int(
                Config.TOP_SECTORS_COUNT
            ),

            "top_stocks_per_sector": int(
                Config.TOP_STOCKS_PER_SECTOR
            ),

            "max_candidate_universe": int(
                Config.MAX_SCANNER_UNIVERSE
            ),

            "supported_modes": list(
                getattr(
                    Config,
                    "SUPPORTED_TRADING_MODES",
                    (
                        Config.MODE_INTRADAY,
                        Config.MODE_SWING,
                    ),
                )
            ),

            "metrics": [
                "EMA 20/50/200",
                "RSI",
                "MACD",
                "Supertrend",
                "ADX",
                "Volume Ratio",
                "Relative Strength",
                "Multi-Timeframe Confirmation",
            ],

            "source": "FYERS",

            "checked_at": (
                utc_now().isoformat()
            ),
        }


# ============================================================
# GLOBAL INSTANCE
# ============================================================

_global_technical_metrics_service: (
    TechnicalMetricsService | None
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

    with _global_technical_metrics_lock:

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
