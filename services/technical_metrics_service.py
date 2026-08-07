from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from config import Config
from services.market_data_service import (
    MarketDataService,
    get_market_data_service,
)
from utils.helpers import (
    clean_text,
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


class TechnicalMetricsError(
    RuntimeError
):
    """Raised when verified technical metrics cannot be created."""


class TechnicalMetricsService:
    """
    Builds live technical metrics for:

    1. Sector ranking
    2. Top-stock ranking
    3. Relative-strength comparison

    No fundamental data.
    No fake values.
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

    # =========================================================
    # HELPERS
    # =========================================================

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
        period: int,
    ) -> pd.Series:
        delta = series.diff()

        gain = delta.clip(
            lower=0
        )

        loss = (
            -delta.clip(
                upper=0
            )
        )

        average_gain = gain.ewm(
            alpha=1 / period,
            adjust=False,
        ).mean()

        average_loss = loss.ewm(
            alpha=1 / period,
            adjust=False,
        ).mean()

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
                    1 + rs
                )
            )
        )

        return rsi.fillna(
            50.0
        )

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

    @staticmethod
    def _build_dataframe(
        candles: list[
            dict[str, Any]
        ],
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
            dataframe[column] = (
                pd.to_numeric(
                    dataframe[column],
                    errors="coerce",
                )
            )

        dataframe = dataframe.dropna(
            subset=[
                "open",
                "high",
                "low",
                "close",
            ]
        )

        dataframe["volume"] = (
            dataframe["volume"]
            .fillna(0.0)
        )

        if len(dataframe) < 30:
            raise TechnicalMetricsError(
                "Insufficient verified candles."
            )

        return dataframe.reset_index(
            drop=True
        )

    # =========================================================
    # SINGLE STOCK METRICS
    # =========================================================

    def build_metrics_from_candles(
        self,
        *,
        symbol: str,
        candles: list[
            dict[str, Any]
        ],
        benchmark_change_pct: float = 0.0,
    ) -> dict[str, Any]:
        normalized_symbol = (
            normalize_symbol(
                symbol
            )
        )

        if not normalized_symbol:
            raise ValueError(
                "Valid stock symbol required."
            )

        dataframe = (
            self._build_dataframe(
                candles
            )
        )

        close = dataframe[
            "close"
        ]

        volume = dataframe[
            "volume"
        ]

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

        rsi_series = self._rsi(
            close,
            Config.RSI_PERIOD,
        )

        current_price = safe_float(
            close.iloc[-1]
        )

        if (
            current_price is None
            or current_price <= 0
        ):
            raise TechnicalMetricsError(
                (
                    f"{normalized_symbol}: "
                    "invalid current price."
                )
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
                rsi_series.iloc[-1]
            )
            or 50.0
        )

        average_volume = safe_float(
            volume
            .rolling(
                Config.VOLUME_AVG_PERIOD
            )
            .mean()
            .iloc[-1]
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

        above_ema20 = (
            current_price
            > ema20_value
        )

        above_ema50 = (
            current_price
            > ema50_value
        )

        above_ema200 = (
            current_price
            > ema200_value
        )

        bullish = (
            above_ema20
            and above_ema50
            and (
                ema20_value
                > ema50_value
            )
        )

        relative_strength_pct = (
            change_20d
            - float(
                benchmark_change_pct
                or 0.0
            )
        )

        return {
            "symbol": (
                normalized_symbol
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

            "bullish": bullish,

            "rsi": round(
                rsi_value,
                4,
            ),

            "volume_ratio": round(
                volume_ratio,
                4,
            ),

            "relative_strength_pct": round(
                relative_strength_pct,
                4,
            ),
        }

    # =========================================================
    # FETCH ONE STOCK FROM FYERS
    # =========================================================

    def build_stock_metrics(
        self,
        access_token: str,
        *,
        symbol: str,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        normalized_mode = (
            Config.normalize_trading_mode(
                mode
            )
        )

        mode_data = (
            self.market_data_service
            .get_mode_market_data(
                access_token,
                symbol,
                mode=normalized_mode,
                force_refresh=(
                    force_refresh
                ),
            )
        )

        primary = mode_data.get(
            "primary",
            [],
        )

        if not primary:
            raise TechnicalMetricsError(
                (
                    f"{symbol}: verified "
                    "primary candles unavailable."
                )
            )

        return (
            self.build_metrics_from_candles(
                symbol=symbol,
                candles=primary,
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
            )
        )

    # =========================================================
    # BULK METRICS
    # =========================================================

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
        """
        Build metrics keyed by stock symbol.

        Accepts NSEStock objects or dict records.
        Failed/missing stocks are skipped.
        No fabricated metrics are created.
        """

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

            symbol = normalize_symbol(
                raw_symbol
            )

            if not symbol:
                continue

            try:
                metrics = (
                    self.build_stock_metrics(
                        access_token,
                        symbol=symbol,
                        mode=mode,
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
                    "Technical metric generation failed",
                    exception=exception,
                    symbol=symbol,
                    component=(
                        "technical_metrics_service"
                    ),
                    error_code=(
                        "TECHNICAL_METRICS_FAILED"
                    ),
                )

                continue

        return results


_global_technical_metrics_service: (
    TechnicalMetricsService | None
) = None


def get_technical_metrics_service(
) -> TechnicalMetricsService:
    global _global_technical_metrics_service

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
