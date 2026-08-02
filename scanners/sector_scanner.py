from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

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


logger = get_logger("scanners.sector_scanner")


class SectorScannerError(RuntimeError):
    """Raised when sector analysis cannot be completed."""


@dataclass
class SectorScanResult:
    symbol: str
    sector: str
    timeframe: str
    score: float
    sector_bullish: bool
    stock_return: float | None
    sector_return: float | None
    nifty_return: float | None
    stock_vs_sector: float | None
    sector_vs_nifty: float | None
    trend_score: float
    momentum_score: float
    reason: str
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "sector": self.sector,
            "timeframe": self.timeframe,
            "score": round(self.score, 2),
            "sector_bullish": self.sector_bullish,
            "stock_return": (
                round(self.stock_return, 2)
                if self.stock_return is not None
                else None
            ),
            "sector_return": (
                round(self.sector_return, 2)
                if self.sector_return is not None
                else None
            ),
            "nifty_return": (
                round(self.nifty_return, 2)
                if self.nifty_return is not None
                else None
            ),
            "stock_vs_sector": (
                round(self.stock_vs_sector, 2)
                if self.stock_vs_sector is not None
                else None
            ),
            "sector_vs_nifty": (
                round(self.sector_vs_nifty, 2)
                if self.sector_vs_nifty is not None
                else None
            ),
            "trend_score": round(self.trend_score, 2),
            "momentum_score": round(
                self.momentum_score,
                2,
            ),
            "reason": self.reason,
            "generated_at": self.generated_at,
        }


class SectorScanner:
    """
    Compares a stock against its sector and Nifty benchmark.

    No synthetic sector value is generated. If verified sector
    benchmark candles are unavailable, the sector result is rejected.
    """

    RETURN_PERIODS = {
        "15_30_days": 20,
        "3_month": 60,
        "6_month": 120,
        "1_year": 250,
        "3_year": 500,
    }

    MINIMUM_SCORE = {
        "15_30_days": 62.0,
        "3_month": 64.0,
        "6_month": 65.0,
        "1_year": 66.0,
        "3_year": 68.0,
    }

    MINIMUM_CANDLES = 60

    def _build_dataframe(
        self,
        candles: Iterable[dict[str, Any]] | None,
    ) -> pd.DataFrame:
        if candles is None:
            raise SectorScannerError(
                "Verified candle data is unavailable."
            )

        rows: list[dict[str, Any]] = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            close = safe_float(
                candle.get("close")
            )

            timestamp = (
                candle.get("timestamp")
                or candle.get("date")
            )

            if (
                close is None
                or close <= 0
                or not timestamp
            ):
                continue

            rows.append(
                {
                    "timestamp": str(timestamp),
                    "close": close,
                }
            )

        dataframe = pd.DataFrame(rows)

        if dataframe.empty:
            raise SectorScannerError(
                "No valid closing-price history was found."
            )

        dataframe = dataframe.drop_duplicates(
            subset=["timestamp"],
            keep="last",
        )

        dataframe = dataframe.sort_values(
            "timestamp"
        ).reset_index(drop=True)

        if len(dataframe) < self.MINIMUM_CANDLES:
            raise SectorScannerError(
                (
                    f"At least {self.MINIMUM_CANDLES} "
                    "valid candles are required."
                )
            )

        return dataframe

    @staticmethod
    def _return_percent(
        dataframe: pd.DataFrame,
        period: int,
    ) -> float | None:
        if len(dataframe) <= period:
            return None

        current = safe_float(
            dataframe["close"].iloc[-1]
        )

        previous = safe_float(
            dataframe["close"].iloc[-period]
        )

        if (
            current is None
            or previous is None
            or previous <= 0
        ):
            return None

        return (
            (current / previous) - 1
        ) * 100

    @staticmethod
    def _trend_score(
        dataframe: pd.DataFrame,
    ) -> float:
        close = dataframe["close"]

        ema20 = close.ewm(
            span=20,
            adjust=False,
        ).mean()

        ema50 = close.ewm(
            span=50,
            adjust=False,
        ).mean()

        current_price = float(
            close.iloc[-1]
        )

        ema20_value = float(
            ema20.iloc[-1]
        )

        ema50_value = float(
            ema50.iloc[-1]
        )

        score = 0.0

        if current_price > ema20_value:
            score += 40.0

        if current_price > ema50_value:
            score += 35.0

        if ema20_value > ema50_value:
            score += 25.0

        return score

    @staticmethod
    def _momentum_score(
        sector_return: float,
        nifty_return: float,
    ) -> float:
        outperformance = (
            sector_return - nifty_return
        )

        score = 50.0 + (
            outperformance * 5
        )

        return normalize_score(score)

    def scan(
        self,
        *,
        symbol: str,
        sector: str,
        stock_candles: Iterable[
            dict[str, Any]
        ],
        sector_candles: Iterable[
            dict[str, Any]
        ] | None,
        nifty_candles: Iterable[
            dict[str, Any]
        ] | None,
        timeframe: str = "3_month",
    ) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(
            symbol
        )

        normalized_timeframe = (
            normalize_timeframe(timeframe)
        )

        normalized_sector = (
            str(sector).strip()
            if sector
            else "Unknown"
        )

        if not normalized_symbol:
            raise ValueError(
                "A valid stock symbol is required."
            )

        if normalized_sector == "Unknown":
            raise SectorScannerError(
                "Verified sector information is unavailable."
            )

        try:
            stock_dataframe = (
                self._build_dataframe(
                    stock_candles
                )
            )

            sector_dataframe = (
                self._build_dataframe(
                    sector_candles
                )
            )

            nifty_dataframe = (
                self._build_dataframe(
                    nifty_candles
                )
            )

            period = self.RETURN_PERIODS[
                normalized_timeframe
            ]

            stock_return = (
                self._return_percent(
                    stock_dataframe,
                    period,
                )
            )

            sector_return = (
                self._return_percent(
                    sector_dataframe,
                    period,
                )
            )

            nifty_return = (
                self._return_percent(
                    nifty_dataframe,
                    period,
                )
            )

            if any(
                value is None
                for value in (
                    stock_return,
                    sector_return,
                    nifty_return,
                )
            ):
                raise SectorScannerError(
                    "Insufficient verified history for sector comparison."
                )

            assert stock_return is not None
            assert sector_return is not None
            assert nifty_return is not None

            stock_vs_sector = (
                stock_return
                - sector_return
            )

            sector_vs_nifty = (
                sector_return
                - nifty_return
            )

            trend_score = self._trend_score(
                sector_dataframe
            )

            momentum_score = (
                self._momentum_score(
                    sector_return,
                    nifty_return,
                )
            )

            stock_relative_score = (
                normalize_score(
                    50
                    + stock_vs_sector * 5
                )
            )

            sector_relative_score = (
                normalize_score(
                    50
                    + sector_vs_nifty * 5
                )
            )

            weighted_score = (
                trend_score * 0.35
                + momentum_score * 0.25
                + stock_relative_score * 0.25
                + sector_relative_score * 0.15
            )

            sector_bullish = (
                weighted_score
                >= self.MINIMUM_SCORE[
                    normalized_timeframe
                ]
                and sector_return > nifty_return
                and stock_return
                >= sector_return
                and trend_score >= 65
            )

            if sector_bullish:
                reason = (
                    "Sector is bullish, outperforming Nifty, "
                    "and the stock is outperforming its sector."
                )

            elif sector_return <= nifty_return:
                reason = (
                    "Sector is not outperforming Nifty."
                )

            elif stock_return < sector_return:
                reason = (
                    "Stock is underperforming its sector."
                )

            elif trend_score < 65:
                reason = (
                    "Sector trend is not sufficiently bullish."
                )

            else:
                reason = (
                    "Sector confirmation is below the required score."
                )

            result = SectorScanResult(
                symbol=normalized_symbol,
                sector=normalized_sector,
                timeframe=normalized_timeframe,
                score=normalize_score(
                    weighted_score
                ),
                sector_bullish=sector_bullish,
                stock_return=stock_return,
                sector_return=sector_return,
                nifty_return=nifty_return,
                stock_vs_sector=stock_vs_sector,
                sector_vs_nifty=sector_vs_nifty,
                trend_score=trend_score,
                momentum_score=momentum_score,
                reason=reason,
                generated_at=utc_now().isoformat(),
            )

            logger.info(
                (
                    "Sector scan completed for %s "
                    "with score %.2f."
                ),
                normalized_symbol,
                weighted_score,
                extra=build_log_extra(
                    component="sector_scanner",
                    symbol=normalized_symbol,
                    timeframe=normalized_timeframe,
                    event="sector_scan_completed",
                    status=(
                        "success"
                        if sector_bullish
                        else "rejected"
                    ),
                    sector=normalized_sector,
                    stock_vs_sector=round(
                        stock_vs_sector,
                        2,
                    ),
                    sector_vs_nifty=round(
                        sector_vs_nifty,
                        2,
                    ),
                ),
            )

            return result.to_dict()

        except SectorScannerError:
            raise

        except Exception as exception:
            log_exception(
                logger,
                "Sector analysis failed",
                exception=exception,
                symbol=normalized_symbol,
                timeframe=normalized_timeframe,
                component="sector_scanner",
                error_code="SECTOR_SCAN_FAILED",
                sector=normalized_sector,
            )

            raise SectorScannerError(
                (
                    "Sector analysis failed "
                    f"for {normalized_symbol}."
                )
            ) from exception


_global_sector_scanner: (
    SectorScanner | None
) = None


def get_sector_scanner() -> SectorScanner:
    global _global_sector_scanner

    if _global_sector_scanner is None:
        _global_sector_scanner = (
            SectorScanner()
        )

    return _global_sector_scanner
