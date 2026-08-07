from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable

from config import Config
from data.nse_universe import NSEStock
from utils.helpers import (
    normalize_score,
    normalize_symbol,
    safe_float,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_exception,
)


logger = get_logger(
    "services.sector_scanner"
)


class SectorScannerError(
    RuntimeError
):
    """Raised when sector ranking cannot be completed."""


@dataclass
class SectorRankResult:
    sector: str

    score: float

    momentum_score: float
    trend_score: float
    breadth_score: float
    volume_score: float
    relative_strength_score: float

    stock_count: int

    bullish_stock_count: int
    above_ema20_count: int
    above_ema50_count: int
    above_ema200_count: int

    average_change_1d_pct: float
    average_change_5d_pct: float
    average_change_20d_pct: float

    average_volume_ratio: float
    average_relative_strength_pct: float

    generated_at: str

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "sector": self.sector,

            "score": round(
                self.score,
                2,
            ),

            "momentum_score": round(
                self.momentum_score,
                2,
            ),

            "trend_score": round(
                self.trend_score,
                2,
            ),

            "breadth_score": round(
                self.breadth_score,
                2,
            ),

            "volume_score": round(
                self.volume_score,
                2,
            ),

            "relative_strength_score": round(
                self.relative_strength_score,
                2,
            ),

            "stock_count": (
                self.stock_count
            ),

            "bullish_stock_count": (
                self.bullish_stock_count
            ),

            "above_ema20_count": (
                self.above_ema20_count
            ),

            "above_ema50_count": (
                self.above_ema50_count
            ),

            "above_ema200_count": (
                self.above_ema200_count
            ),

            "average_change_1d_pct": round(
                self.average_change_1d_pct,
                2,
            ),

            "average_change_5d_pct": round(
                self.average_change_5d_pct,
                2,
            ),

            "average_change_20d_pct": round(
                self.average_change_20d_pct,
                2,
            ),

            "average_volume_ratio": round(
                self.average_volume_ratio,
                2,
            ),

            "average_relative_strength_pct": round(
                self.average_relative_strength_pct,
                2,
            ),

            "generated_at": (
                self.generated_at
            ),
        }


class SectorScanner:
    """
    Ranks NSE sectors using technical strength only.

    Final flow:

    NSE sector universe
        ↓
    Technical metrics for stocks
        ↓
    Sector aggregation
        ↓
    Sector score
        ↓
    Top 10 strongest sectors

    No fixed NIFTY 500 dependency.
    No fundamental analysis.
    """

    MINIMUM_STOCKS_PER_SECTOR = 3

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _average(
        values: Iterable[
            float | int | None
        ],
    ) -> float:

        clean_values: list[
            float
        ] = []

        for value in values:
            number = safe_float(
                value
            )

            if number is None:
                continue

            clean_values.append(
                float(number)
            )

        if not clean_values:
            return 0.0

        return float(
            mean(
                clean_values
            )
        )

    @staticmethod
    def _clamp(
        value: float,
    ) -> float:

        return normalize_score(
            value
        )

    # =========================================================
    # MOMENTUM
    # =========================================================

    def _momentum_score(
        self,
        metrics: list[
            dict[str, Any]
        ],
    ) -> tuple[
        float,
        float,
        float,
        float,
    ]:

        if not metrics:
            return (
                0.0,
                0.0,
                0.0,
                0.0,
            )

        average_1d = (
            self._average(
                item.get(
                    "change_1d_pct"
                )
                for item
                in metrics
            )
        )

        average_5d = (
            self._average(
                item.get(
                    "change_5d_pct"
                )
                for item
                in metrics
            )
        )

        average_20d = (
            self._average(
                item.get(
                    "change_20d_pct"
                )
                for item
                in metrics
            )
        )

        score = (
            50.0
            + average_1d * 5.0
            + average_5d * 2.0
            + average_20d * 1.0
        )

        return (
            self._clamp(
                score
            ),
            average_1d,
            average_5d,
            average_20d,
        )

    # =========================================================
    # TREND
    # =========================================================

    def _trend_score(
        self,
        metrics: list[
            dict[str, Any]
        ],
    ) -> tuple[
        float,
        int,
        int,
        int,
    ]:

        if not metrics:
            return (
                0.0,
                0,
                0,
                0,
            )

        total = len(
            metrics
        )

        above_ema20_count = sum(
            1
            for item
            in metrics
            if item.get(
                "above_ema20"
            ) is True
        )

        above_ema50_count = sum(
            1
            for item
            in metrics
            if item.get(
                "above_ema50"
            ) is True
        )

        above_ema200_count = sum(
            1
            for item
            in metrics
            if item.get(
                "above_ema200"
            ) is True
        )

        ema20_score = (
            above_ema20_count
            / total
            * 100.0
        )

        ema50_score = (
            above_ema50_count
            / total
            * 100.0
        )

        ema200_score = (
            above_ema200_count
            / total
            * 100.0
        )

        score = (
            ema20_score * 0.40
            + ema50_score * 0.35
            + ema200_score * 0.25
        )

        return (
            self._clamp(
                score
            ),
            above_ema20_count,
            above_ema50_count,
            above_ema200_count,
        )

    # =========================================================
    # BREADTH
    # =========================================================

    def _breadth_score(
        self,
        metrics: list[
            dict[str, Any]
        ],
    ) -> tuple[
        float,
        int,
    ]:

        if not metrics:
            return (
                0.0,
                0,
            )

        total = len(
            metrics
        )

        bullish_count = sum(
            1
            for item
            in metrics
            if item.get(
                "bullish"
            ) is True
        )

        score = (
            bullish_count
            / total
            * 100.0
        )

        return (
            self._clamp(
                score
            ),
            bullish_count,
        )

    # =========================================================
    # VOLUME
    # =========================================================

    def _volume_score(
        self,
        metrics: list[
            dict[str, Any]
        ],
    ) -> tuple[
        float,
        float,
    ]:

        if not metrics:
            return (
                0.0,
                0.0,
            )

        average_volume_ratio = (
            self._average(
                item.get(
                    "volume_ratio"
                )
                for item
                in metrics
            )
        )

        # 1x volume = 50
        # 1.5x volume = 75
        # 2x volume = 100
        score = (
            average_volume_ratio
            * 50.0
        )

        return (
            self._clamp(
                score
            ),
            average_volume_ratio,
        )

    # =========================================================
    # RELATIVE STRENGTH
    # =========================================================

    def _relative_strength_score(
        self,
        metrics: list[
            dict[str, Any]
        ],
    ) -> tuple[
        float,
        float,
    ]:

        if not metrics:
            return (
                0.0,
                0.0,
            )

        average_rs = (
            self._average(
                item.get(
                    "relative_strength_pct"
                )
                for item
                in metrics
            )
        )

        score = (
            50.0
            + average_rs * 5.0
        )

        return (
            self._clamp(
                score
            ),
            average_rs,
        )

    # =========================================================
    # ONE SECTOR SCORE
    # =========================================================

    def calculate_sector_score(
        self,
        *,
        sector: str,
        stock_metrics: list[
            dict[str, Any]
        ],
    ) -> SectorRankResult:

        if not sector:
            raise SectorScannerError(
                "Sector name is missing."
            )

        if (
            len(
                stock_metrics
            )
            < self.MINIMUM_STOCKS_PER_SECTOR
        ):
            raise SectorScannerError(
                (
                    f"{sector}: at least "
                    f"{self.MINIMUM_STOCKS_PER_SECTOR} "
                    "valid stocks are required."
                )
            )

        (
            momentum_score,
            average_1d,
            average_5d,
            average_20d,
        ) = self._momentum_score(
            stock_metrics
        )

        (
            trend_score,
            above_ema20_count,
            above_ema50_count,
            above_ema200_count,
        ) = self._trend_score(
            stock_metrics
        )

        (
            breadth_score,
            bullish_stock_count,
        ) = self._breadth_score(
            stock_metrics
        )

        (
            volume_score,
            average_volume_ratio,
        ) = self._volume_score(
            stock_metrics
        )

        (
            relative_strength_score,
            average_relative_strength,
        ) = self._relative_strength_score(
            stock_metrics
        )

        # Final sector score = 100
        final_score = (
            momentum_score
            * 0.25
            + trend_score
            * 0.25
            + breadth_score
            * 0.20
            + volume_score
            * 0.15
            + relative_strength_score
            * 0.15
        )

        return SectorRankResult(
            sector=sector,

            score=self._clamp(
                final_score
            ),

            momentum_score=(
                momentum_score
            ),

            trend_score=(
                trend_score
            ),

            breadth_score=(
                breadth_score
            ),

            volume_score=(
                volume_score
            ),

            relative_strength_score=(
                relative_strength_score
            ),

            stock_count=len(
                stock_metrics
            ),

            bullish_stock_count=(
                bullish_stock_count
            ),

            above_ema20_count=(
                above_ema20_count
            ),

            above_ema50_count=(
                above_ema50_count
            ),

            above_ema200_count=(
                above_ema200_count
            ),

            average_change_1d_pct=(
                average_1d
            ),

            average_change_5d_pct=(
                average_5d
            ),

            average_change_20d_pct=(
                average_20d
            ),

            average_volume_ratio=(
                average_volume_ratio
            ),

            average_relative_strength_pct=(
                average_relative_strength
            ),

            generated_at=(
                utc_now().isoformat()
            ),
        )

    # =========================================================
    # GROUP METRICS BY SECTOR
    # =========================================================

    def _group_metrics_by_sector(
        self,
        stocks: Iterable[
            NSEStock
        ],
        metrics_by_symbol: dict[
            str,
            dict[str, Any],
        ],
    ) -> dict[
        str,
        list[dict[str, Any]],
    ]:

        sector_metrics: dict[
            str,
            list[dict[str, Any]],
        ] = {}

        for stock in stocks:

            symbol = normalize_symbol(
                stock.symbol
            )

            if not symbol:
                continue

            metrics = (
                metrics_by_symbol.get(
                    symbol
                )
            )

            if not isinstance(
                metrics,
                dict,
            ):
                continue

            sector = str(
                stock.sector
                or ""
            ).strip()

            if not sector:
                continue

            sector_metrics.setdefault(
                sector,
                [],
            ).append(
                metrics
            )

        return sector_metrics

    # =========================================================
    # RANK ALL SECTORS
    # =========================================================

    def rank_sectors(
        self,
        *,
        stocks: Iterable[
            NSEStock
        ],
        metrics_by_symbol: dict[
            str,
            dict[str, Any],
        ],
    ) -> list[
        SectorRankResult
    ]:

        try:
            sector_metrics = (
                self
                ._group_metrics_by_sector(
                    stocks,
                    metrics_by_symbol,
                )
            )

            results: list[
                SectorRankResult
            ] = []

            for (
                sector,
                metrics,
            ) in sector_metrics.items():

                if (
                    len(metrics)
                    < self.MINIMUM_STOCKS_PER_SECTOR
                ):
                    continue

                try:
                    result = (
                        self
                        .calculate_sector_score(
                            sector=sector,
                            stock_metrics=(
                                metrics
                            ),
                        )
                    )

                    results.append(
                        result
                    )

                except SectorScannerError:
                    continue

            results.sort(
                key=lambda item: (
                    -item.score,
                    -item.breadth_score,
                    -item.trend_score,
                    -item.momentum_score,
                    item.sector,
                )
            )

            logger.info(
                (
                    "Sector ranking completed. "
                    "%s sectors ranked."
                ),
                len(
                    results
                ),
                extra=build_log_extra(
                    component=(
                        "sector_scanner"
                    ),
                    event=(
                        "sector_ranking_completed"
                    ),
                    status="success",
                    sector_count=len(
                        results
                    ),
                ),
            )

            return results

        except Exception as exception:
            log_exception(
                logger,
                (
                    "Sector ranking failed"
                ),
                exception=exception,
                component=(
                    "sector_scanner"
                ),
                error_code=(
                    "SECTOR_RANKING_FAILED"
                ),
            )

            raise SectorScannerError(
                (
                    "Unable to rank NSE sectors."
                )
            ) from exception

    # =========================================================
    # TOP 10 SECTORS
    # =========================================================

    def get_top_sectors(
        self,
        *,
        stocks: Iterable[
            NSEStock
        ],
        metrics_by_symbol: dict[
            str,
            dict[str, Any],
        ],
        limit: int | None = None,
    ) -> list[
        SectorRankResult
    ]:

        if limit is None:
            limit = (
                Config.TOP_SECTORS_COUNT
            )

        safe_limit = max(
            1,
            int(
                limit
            ),
        )

        ranked = (
            self.rank_sectors(
                stocks=stocks,
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
            )
        )

        return ranked[
            :safe_limit
        ]

    # =========================================================
    # TOP SECTOR NAMES
    # =========================================================

    def get_top_sector_names(
        self,
        *,
        stocks: Iterable[
            NSEStock
        ],
        metrics_by_symbol: dict[
            str,
            dict[str, Any],
        ],
        limit: int | None = None,
    ) -> list[str]:

        top_sectors = (
            self.get_top_sectors(
                stocks=stocks,
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
                limit=limit,
            )
        )

        return [
            item.sector
            for item
            in top_sectors
        ]

    # =========================================================
    # TOP SECTORS AS DICTS
    # =========================================================

    def get_top_sectors_as_dicts(
        self,
        *,
        stocks: Iterable[
            NSEStock
        ],
        metrics_by_symbol: dict[
            str,
            dict[str, Any],
        ],
        limit: int | None = None,
    ) -> list[
        dict[str, Any]
    ]:

        return [
            result.to_dict()
            for result
            in self.get_top_sectors(
                stocks=stocks,
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
                limit=limit,
            )
        ]


# =============================================================
# GLOBAL INSTANCE
# =============================================================

_global_sector_scanner: (
    SectorScanner | None
) = None


def get_sector_scanner(
) -> SectorScanner:

    global (
        _global_sector_scanner
    )

    if (
        _global_sector_scanner
        is None
    ):
        _global_sector_scanner = (
            SectorScanner()
        )

    return (
        _global_sector_scanner
    )
