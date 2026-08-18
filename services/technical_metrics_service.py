from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from config import Config
from services.market_data_service import (
    MarketDataService,
    get_market_data_service,
)
from utils.helpers import (
    normalize_symbol,
    safe_float,
)
from utils.logger import (
    get_logger,
    log_exception,
)


logger = get_logger(
    "services.technical_metrics_service"
)


# ============================================================
# ERRORS
# ============================================================


class TechnicalMetricsError(
    RuntimeError
):
    """Raised when verified technical metrics cannot be created."""


# ============================================================
# SERVICE
# ============================================================


class TechnicalMetricsService:
    """
    Technical-only metrics service for Eagle Smart Scanner.

    Used for:

    1. Sector ranking
    2. Top-stock ranking
    3. Relative-strength ranking
    4. Multi-timeframe confirmation

    Modes:

    INTRADAY
        5m + 15m + Daily

    BTST
        15m + 60m + Daily

    SWING
        Daily + Weekly

    No fundamentals.
    No synthetic/fake values.
    """

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

            raise TechnicalMetricsError(
                "Required OHLCV columns are missing."
            )

        for column in required:

            dataframe[
                column
            ] = pd.to_numeric(
                dataframe[
                    column
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
            .reset_index(
                drop=True
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

        if len(
            dataframe
        ) < minimum:

            raise TechnicalMetricsError(
                (
                    f"Only {len(dataframe)} "
                    "verified candles available; "
                    f"{minimum} required."
                )
            )

        return dataframe


    # ========================================================
    # EMA
    # ========================================================

    @staticmethod
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


    # ========================================================
    # RSI
    # ========================================================

    @staticmethod
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
                pd.NA,
            )
        )

        rsi = (
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
            rsi.fillna(
                50.0
            )
        )


    # ========================================================
    # MACD
    # ========================================================

    def _macd(
        self,
        series: pd.Series,
    ) -> tuple[
        pd.Series,
        pd.Series,
        pd.Series,
    ]:

        fast = self._ema(
            series,
            Config.MACD_FAST,
        )

        slow = self._ema(
            series,
            Config.MACD_SLOW,
        )

        macd_line = (
            fast
            - slow
        )

        signal_line = self._ema(
            macd_line,
            Config.MACD_SIGNAL,
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
    # TRUE RANGE / ATR
    # ========================================================

    @staticmethod
    def _true_range(
        dataframe: pd.DataFrame,
    ) -> pd.Series:

        previous_close = (
            dataframe[
                "close"
            ]
            .shift(
                1
            )
        )

        range_1 = (
            dataframe[
                "high"
            ]
            - dataframe[
                "low"
            ]
        )

        range_2 = (
            dataframe[
                "high"
            ]
            - previous_close
        ).abs()

        range_3 = (
            dataframe[
                "low"
            ]
            - previous_close
        ).abs()

        return pd.concat(
            [
                range_1,
                range_2,
                range_3,
            ],
            axis=1,
        ).max(
            axis=1
        )


    def _atr(
        self,
        dataframe: pd.DataFrame,
        period: int,
    ) -> pd.Series:

        true_range = (
            self._true_range(
                dataframe
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


    # ========================================================
    # ADX
    # ========================================================

    def _adx(
        self,
        dataframe: pd.DataFrame,
        period: int,
    ) -> pd.Series:

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

        plus_dm = (
            up_move.where(
                (
                    up_move
                    > down_move
                )
                & (
                    up_move
                    > 0
                ),
                0.0,
            )
        )

        minus_dm = (
            down_move.where(
                (
                    down_move
                    > up_move
                )
                & (
                    down_move
                    > 0
                ),
                0.0,
            )
        )

        atr = self._atr(
            dataframe,
            period,
        )

        plus_di = (
            100
            * (
                plus_dm.ewm(
                    alpha=(
                        1 / period
                    ),
                    adjust=False,
                ).mean()
                / atr.replace(
                    0,
                    pd.NA,
                )
            )
        )

        minus_di = (
            100
            * (
                minus_dm.ewm(
                    alpha=(
                        1 / period
                    ),
                    adjust=False,
                ).mean()
                / atr.replace(
                    0,
                    pd.NA,
                )
            )
        )

        denominator = (
            plus_di
            + minus_di
        ).replace(
            0,
            pd.NA,
        )

        dx = (
            (
                plus_di
                - minus_di
            )
            .abs()
            / denominator
            * 100
        )

        return (
            dx.ewm(
                alpha=(
                    1 / period
                ),
                adjust=False,
            )
            .mean()
            .fillna(
                0.0
            )
        )


    # ========================================================
    # VWAP
    # ========================================================

    @staticmethod
    def _vwap(
        dataframe: pd.DataFrame,
    ) -> pd.Series:

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

        cumulative_volume = (
            dataframe[
                "volume"
            ]
            .cumsum()
        )

        cumulative_value = (
            (
                typical_price
                * dataframe[
                    "volume"
                ]
            )
            .cumsum()
        )

        return (
            cumulative_value
            / cumulative_volume.replace(
                0,
                pd.NA,
            )
        ).fillna(
            dataframe[
                "close"
            ]
        )


    # ========================================================
    # SUPERTREND
    # ========================================================

    def _supertrend(
        self,
        dataframe: pd.DataFrame,
    ) -> tuple[
        pd.Series,
        pd.Series,
    ]:

        period = (
            Config.SUPERTREND_PERIOD
        )

        multiplier = (
            Config.SUPERTREND_MULTIPLIER
        )

        atr = self._atr(
            dataframe,
            period,
        )

        hl2 = (
            dataframe[
                "high"
            ]
            + dataframe[
                "low"
            ]
        ) / 2.0

        basic_upper = (
            hl2
            + (
                multiplier
                * atr
            )
        )

        basic_lower = (
            hl2
            - (
                multiplier
                * atr
            )
        )

        final_upper = (
            basic_upper.copy()
        )

        final_lower = (
            basic_lower.copy()
        )

        supertrend = pd.Series(
            index=dataframe.index,
            dtype=float,
        )

        direction = pd.Series(
            index=dataframe.index,
            dtype=bool,
        )

        for index in range(
            len(
                dataframe
            )
        ):

            if index == 0:

                final_upper.iloc[
                    index
                ] = (
                    basic_upper.iloc[
                        index
                    ]
                )

                final_lower.iloc[
                    index
                ] = (
                    basic_lower.iloc[
                        index
                    ]
                )

                supertrend.iloc[
                    index
                ] = (
                    final_lower.iloc[
                        index
                    ]
                )

                direction.iloc[
                    index
                ] = True

                continue

            previous_close = (
                dataframe[
                    "close"
                ]
                .iloc[
                    index - 1
                ]
            )

            if (
                basic_upper.iloc[
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
                    basic_upper.iloc[
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
                basic_lower.iloc[
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
                    basic_lower.iloc[
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

            previous_supertrend = (
                supertrend.iloc[
                    index - 1
                ]
            )

            current_close = (
                dataframe[
                    "close"
                ]
                .iloc[
                    index
                ]
            )

            if (
                previous_supertrend
                == final_upper.iloc[
                    index - 1
                ]
            ):

                if (
                    current_close
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
                    ] = False

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
                    ] = True

            else:

                if (
                    current_close
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
                    ] = True

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
                    ] = False

        return (
            supertrend,
            direction.fillna(
                False
            ),
        )


    # ========================================================
    # CHANGE %
    # ========================================================

    @staticmethod
    def _change_percent(
        current: float,
        previous: float,
    ) -> float:

        if previous <= 0:
            return 0.0

        return (
            (
                current
                / previous
            )
            - 1.0
        ) * 100.0


    # ========================================================
    # CLOSE POSITION IN RANGE
    # ========================================================

    @staticmethod
    def _close_position_percent(
        *,
        high: float,
        low: float,
        close: float,
    ) -> float:

        candle_range = (
            high
            - low
        )

        if candle_range <= 0:
            return 50.0

        return (
            (
                close
                - low
            )
            / candle_range
        ) * 100.0


    # ========================================================
    # METRICS FOR ONE TIMEFRAME
    # ========================================================

    def _build_timeframe_metrics(
        self,
        candles: list[
            dict[str, Any]
        ],
        *,
        breakout_lookback: int,
        benchmark_change_pct: float,
    ) -> dict[str, Any]:

        dataframe = (
            self._build_dataframe(
                candles,
                minimum=30,
            )
        )

        close = (
            dataframe[
                "close"
            ]
        )

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

        volume = (
            dataframe[
                "volume"
            ]
        )

        ema20 = self._ema(
            close,
            Config.EMA_FAST,
        )

        ema50 = self._ema(
            close,
            Config.EMA_MEDIUM,
        )

        ema200 = self._ema(
            close,
            Config.EMA_LONG,
        )

        rsi = self._rsi(
            close,
            Config.RSI_PERIOD,
        )

        (
            macd,
            macd_signal,
            macd_histogram,
        ) = self._macd(
            close
        )

        atr = self._atr(
            dataframe,
            Config.ATR_PERIOD,
        )

        adx = self._adx(
            dataframe,
            Config.ADX_PERIOD,
        )

        vwap = self._vwap(
            dataframe
        )

        (
            supertrend,
            supertrend_direction,
        ) = self._supertrend(
            dataframe
        )

        current_price = (
            safe_float(
                close.iloc[-1]
            )
            or 0.0
        )

        previous_1 = (
            safe_float(
                close.iloc[-2]
            )
            if len(close) >= 2
            else None
        )

        previous_5 = (
            safe_float(
                close.iloc[-6]
            )
            if len(close) >= 6
            else None
        )

        previous_20 = (
            safe_float(
                close.iloc[-21]
            )
            if len(close) >= 21
            else None
        )

        change_1d = (
            self._change_percent(
                current_price,
                previous_1,
            )
            if (
                previous_1 is not None
                and previous_1 > 0
            )
            else 0.0
        )

        change_5d = (
            self._change_percent(
                current_price,
                previous_5,
            )
            if (
                previous_5 is not None
                and previous_5 > 0
            )
            else 0.0
        )

        change_20d = (
            self._change_percent(
                current_price,
                previous_20,
            )
            if (
                previous_20 is not None
                and previous_20 > 0
            )
            else 0.0
        )

        ema20_value = (
            safe_float(
                ema20.iloc[-1]
            )
            or 0.0
        )

        ema50_value = (
            safe_float(
                ema50.iloc[-1]
            )
            or 0.0
        )

        ema200_value = (
            safe_float(
                ema200.iloc[-1]
            )
            or 0.0
        )

        rsi_value = (
            safe_float(
                rsi.iloc[-1]
            )
            or 50.0
        )

        macd_value = (
            safe_float(
                macd.iloc[-1]
            )
            or 0.0
        )

        macd_signal_value = (
            safe_float(
                macd_signal.iloc[-1]
            )
            or 0.0
        )

        macd_histogram_value = (
            safe_float(
                macd_histogram.iloc[-1]
            )
            or 0.0
        )

        previous_macd_histogram = (
            safe_float(
                macd_histogram.iloc[-2]
            )
            or 0.0
        )

        atr_value = (
            safe_float(
                atr.iloc[-1]
            )
            or 0.0
        )

        adx_value = (
            safe_float(
                adx.iloc[-1]
            )
            or 0.0
        )

        vwap_value = (
            safe_float(
                vwap.iloc[-1]
            )
            or current_price
        )

        supertrend_value = (
            safe_float(
                supertrend.iloc[-1]
            )
            or 0.0
        )

        supertrend_buy = bool(
            supertrend_direction.iloc[
                -1
            ]
        )

        rolling_volume = (
            volume
            .rolling(
                Config.VOLUME_AVG_PERIOD
            )
            .mean()
        )

        average_volume = (
            safe_float(
                rolling_volume.iloc[
                    -1
                ]
            )
        )

        latest_volume = (
            safe_float(
                volume.iloc[-1]
            )
            or 0.0
        )

        volume_ratio = (
            latest_volume
            / average_volume
            if (
                average_volume is not None
                and average_volume > 0
            )
            else 0.0
        )

        lookback = max(
            2,
            min(
                int(
                    breakout_lookback
                ),
                len(
                    dataframe
                ) - 1,
            ),
        )

        previous_high = (
            high.iloc[
                -(
                    lookback
                    + 1
                ):
                -1
            ]
            .max()
        )

        previous_low = (
            low.iloc[
                -(
                    lookback
                    + 1
                ):
                -1
            ]
            .min()
        )

        breakout = bool(
            current_price
            > float(
                previous_high
            )
        )

        breakdown_support = bool(
            current_price
            < float(
                previous_low
            )
        )

        latest_open = (
            safe_float(
                dataframe[
                    "open"
                ]
                .iloc[
                    -1
                ]
            )
            or current_price
        )

        latest_high = (
            safe_float(
                high.iloc[-1]
            )
            or current_price
        )

        latest_low = (
            safe_float(
                low.iloc[-1]
            )
            or current_price
        )

        bullish_candle = bool(
            current_price
            > latest_open
        )

        close_position = (
            self._close_position_percent(
                high=latest_high,
                low=latest_low,
                close=current_price,
            )
        )

        distance_from_high = (
            (
                latest_high
                - current_price
            )
            / latest_high
            * 100.0
            if latest_high > 0
            else 0.0
        )

        above_ema20 = bool(
            current_price
            > ema20_value
        )

        above_ema50 = bool(
            current_price
            > ema50_value
        )

        above_ema200 = bool(
            current_price
            > ema200_value
        )

        bullish_ema_structure = bool(
            above_ema20
            and above_ema50
            and (
                ema20_value
                > ema50_value
            )
        )

        macd_bullish = bool(
            macd_value
            > macd_signal_value
        )

        macd_rising = bool(
            macd_histogram_value
            >= previous_macd_histogram
        )

        above_vwap = bool(
            current_price
            > vwap_value
        )

        relative_strength = (
            change_20d
            - float(
                benchmark_change_pct
                or 0.0
            )
        )

        bullish = bool(
            bullish_ema_structure
            and macd_bullish
            and supertrend_buy
        )

        return {
            "current_price": round(
                current_price,
                4,
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
                ema20_value,
                4,
            ),

            "ema50": round(
                ema50_value,
                4,
            ),

            "ema200": round(
                ema200_value,
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

            "bullish_ema_structure": (
                bullish_ema_structure
            ),

            "rsi": round(
                rsi_value,
                4,
            ),

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

            "macd_rising": (
                macd_rising
            ),

            "adx": round(
                adx_value,
                4,
            ),

            "atr": round(
                atr_value,
                4,
            ),

            "vwap": round(
                vwap_value,
                4,
            ),

            "above_vwap": (
                above_vwap
            ),

            "supertrend": round(
                supertrend_value,
                4,
            ),

            "supertrend_buy": (
                supertrend_buy
            ),

            "volume": round(
                latest_volume,
                2,
            ),

            "volume_ratio": round(
                volume_ratio,
                4,
            ),

            "breakout": (
                breakout
            ),

            "breakdown_support": (
                breakdown_support
            ),

            "breakout_level": round(
                float(
                    previous_high
                ),
                4,
            ),

            "support_level": round(
                float(
                    previous_low
                ),
                4,
            ),

            "bullish_candle": (
                bullish_candle
            ),

            "close_position_pct": round(
                close_position,
                4,
            ),

            "distance_from_high_pct": round(
                distance_from_high,
                4,
            ),

            "relative_strength_pct": round(
                relative_strength,
                4,
            ),

            "bullish": (
                bullish
            ),
        }


    # ========================================================
    # MODE-AWARE FINAL METRICS
    # ========================================================

    def build_mode_metrics(
        self,
        *,
        symbol: str,
        mode: str,
        primary_candles: list[
            dict[str, Any]
        ],
        confirmation_candles: list[
            dict[str, Any]
        ],
        higher_timeframe_candles: list[
            dict[str, Any]
        ],
        benchmark_change_pct: float = 0.0,
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
                "Valid stock symbol required."
            )

        breakout_lookback = (
            Config.get_breakout_lookback(
                normalized_mode
            )
        )

        primary = (
            self._build_timeframe_metrics(
                primary_candles,
                breakout_lookback=(
                    breakout_lookback
                ),
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
            )
        )

        confirmation = (
            self._build_timeframe_metrics(
                confirmation_candles,
                breakout_lookback=max(
                    10,
                    int(
                        breakout_lookback
                        / 2
                    ),
                ),
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
            )
        )

        higher = (
            self._build_timeframe_metrics(
                higher_timeframe_candles,
                breakout_lookback=max(
                    20,
                    breakout_lookback,
                ),
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
            )
        )

        rsi_min, rsi_max = (
            Config.get_rsi_range(
                normalized_mode
            )
        )

        minimum_adx = (
            Config.get_min_adx(
                normalized_mode
            )
        )

        minimum_volume_ratio = (
            Config.get_min_volume_ratio(
                normalized_mode
            )
        )

        primary_rsi_valid = bool(
            rsi_min
            <= primary[
                "rsi"
            ]
            <= rsi_max
        )

        volume_confirmed = bool(
            primary[
                "volume_ratio"
            ]
            >= minimum_volume_ratio
        )

        adx_confirmed = bool(
            primary[
                "adx"
            ]
            >= minimum_adx
        )

        confirmation_bullish = bool(
            confirmation[
                "bullish"
            ]
            or (
                confirmation[
                    "above_ema20"
                ]
                and confirmation[
                    "macd_bullish"
                ]
            )
        )

        higher_bullish = bool(
            higher[
                "above_ema20"
            ]
            and higher[
                "above_ema50"
            ]
            and higher[
                "supertrend_buy"
            ]
        )

        multi_timeframe_confirmed = bool(
            confirmation_bullish
            and higher_bullish
        )

        btst_closing_strength = False

        if (
            normalized_mode
            == Config.MODE_BTST
        ):

            btst_closing_strength = bool(
                primary[
                    "close_position_pct"
                ]
                >= Config
                .BTST_MIN_CLOSE_POSITION_PERCENT
                and primary[
                    "distance_from_high_pct"
                ]
                <= Config
                .BTST_MAX_DISTANCE_FROM_DAY_HIGH_PERCENT
            )

        return {
            "symbol": (
                normalized_symbol
            ),

            "mode": (
                normalized_mode
            ),

            # ------------------------------------------------
            # Primary fields kept flat for sector_scanner.py
            # and stock_ranker.py compatibility
            # ------------------------------------------------

            "current_price": (
                primary[
                    "current_price"
                ]
            ),

            "change_1d_pct": (
                primary[
                    "change_1d_pct"
                ]
            ),

            "change_5d_pct": (
                primary[
                    "change_5d_pct"
                ]
            ),

            "change_20d_pct": (
                primary[
                    "change_20d_pct"
                ]
            ),

            "ema20": (
                primary[
                    "ema20"
                ]
            ),

            "ema50": (
                primary[
                    "ema50"
                ]
            ),

            "ema200": (
                primary[
                    "ema200"
                ]
            ),

            "above_ema20": (
                primary[
                    "above_ema20"
                ]
            ),

            "above_ema50": (
                primary[
                    "above_ema50"
                ]
            ),

            "above_ema200": (
                primary[
                    "above_ema200"
                ]
            ),

            "bullish": (
                primary[
                    "bullish"
                ]
            ),

            "rsi": (
                primary[
                    "rsi"
                ]
            ),

            "volume_ratio": (
                primary[
                    "volume_ratio"
                ]
            ),

            "relative_strength_pct": (
                primary[
                    "relative_strength_pct"
                ]
            ),

            # ------------------------------------------------
            # Expanded technical fields
            # ------------------------------------------------

            "macd": (
                primary[
                    "macd"
                ]
            ),

            "macd_signal": (
                primary[
                    "macd_signal"
                ]
            ),

            "macd_histogram": (
                primary[
                    "macd_histogram"
                ]
            ),

            "macd_bullish": (
                primary[
                    "macd_bullish"
                ]
            ),

            "macd_rising": (
                primary[
                    "macd_rising"
                ]
            ),

            "adx": (
                primary[
                    "adx"
                ]
            ),

            "atr": (
                primary[
                    "atr"
                ]
            ),

            "vwap": (
                primary[
                    "vwap"
                ]
            ),

            "above_vwap": (
                primary[
                    "above_vwap"
                ]
            ),

            "supertrend": (
                primary[
                    "supertrend"
                ]
            ),

            "supertrend_buy": (
                primary[
                    "supertrend_buy"
                ]
            ),

            "breakout": (
                primary[
                    "breakout"
                ]
            ),

            "breakout_level": (
                primary[
                    "breakout_level"
                ]
            ),

            "support_level": (
                primary[
                    "support_level"
                ]
            ),

            "bullish_candle": (
                primary[
                    "bullish_candle"
                ]
            ),

            "close_position_pct": (
                primary[
                    "close_position_pct"
                ]
            ),

            "distance_from_high_pct": (
                primary[
                    "distance_from_high_pct"
                ]
            ),

            # ------------------------------------------------
            # Validation / mode rules
            # ------------------------------------------------

            "rsi_valid": (
                primary_rsi_valid
            ),

            "volume_confirmed": (
                volume_confirmed
            ),

            "adx_confirmed": (
                adx_confirmed
            ),

            "confirmation_bullish": (
                confirmation_bullish
            ),

            "higher_timeframe_bullish": (
                higher_bullish
            ),

            "multi_timeframe_confirmed": (
                multi_timeframe_confirmed
            ),

            "btst_closing_strength": (
                btst_closing_strength
            ),

            # ------------------------------------------------
            # Complete nested timeframe data
            # ------------------------------------------------

            "primary_metrics": (
                primary
            ),

            "confirmation_metrics": (
                confirmation
            ),

            "higher_timeframe_metrics": (
                higher
            ),

            "technical_only": True,

            "verified": True,
        }


    # ========================================================
    # FETCH ONE STOCK FROM MARKET DATA SERVICE
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
                "Valid stock symbol required."
            )

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

        if not primary:

            raise (
                TechnicalMetricsError(
                    (
                        f"{normalized_symbol}: "
                        "verified primary candles "
                        "unavailable."
                    )
                )
            )

        if not confirmation:

            raise (
                TechnicalMetricsError(
                    (
                        f"{normalized_symbol}: "
                        "confirmation candles "
                        "unavailable."
                    )
                )
            )

        if not higher:

            raise (
                TechnicalMetricsError(
                    (
                        f"{normalized_symbol}: "
                        "higher-timeframe candles "
                        "unavailable."
                    )
                )
            )

        metrics = (
            self.build_mode_metrics(
                symbol=(
                    normalized_symbol
                ),
                mode=(
                    normalized_mode
                ),
                primary_candles=(
                    primary
                ),
                confirmation_candles=(
                    confirmation
                ),
                higher_timeframe_candles=(
                    higher
                ),
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
            )
        )

        metrics[
            "primary_resolution"
        ] = (
            mode_data.get(
                "primary_resolution"
            )
        )

        metrics[
            "confirmation_resolution"
        ] = (
            mode_data.get(
                "confirmation_resolution"
            )
        )

        metrics[
            "higher_resolution"
        ] = (
            mode_data.get(
                "higher_resolution"
            )
        )

        metrics[
            "source"
        ] = "FYERS"

        return metrics


    # ========================================================
    # BULK METRICS
    # ========================================================

    def build_metrics_for_stocks(
        self,
        access_token: str,
        stocks: Iterable[Any],
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[
        str,
        dict[str, Any],
    ]:
        """
        Build verified metrics keyed by normalized stock symbol.

        Failed symbols are skipped.
        No fabricated metrics are inserted.
        """

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

                results[
                    symbol
                ] = metrics

            except Exception as exception:

                log_exception(
                    logger,
                    (
                        "Technical metric "
                        "generation failed"
                    ),
                    exception=exception,
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

                continue

        return results


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

            "supported_modes": [
                Config.MODE_INTRADAY,
                Config.MODE_BTST,
                Config.MODE_SWING,
            ],

            "indicators": [
                "EMA20",
                "EMA50",
                "EMA200",
                "RSI",
                "MACD",
                "ADX",
                "ATR",
                "Supertrend",
                "VWAP",
                "Volume Ratio",
                "Breakout",
                "Relative Strength",
                "Price Action",
            ],
        }


# ============================================================
# GLOBAL INSTANCE
# ============================================================


_global_technical_metrics_service: (
    TechnicalMetricsService
    | None
) = None


def get_technical_metrics_service(
) -> TechnicalMetricsService:

    global (
        _global_technical_metrics_service
    )
