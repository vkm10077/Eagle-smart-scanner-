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


# ============================================================
# ERROR
# ============================================================


class SectorScannerError(
    RuntimeError
):
    """
    Raised when technical sector ranking
    cannot be completed safely.
    """


# ============================================================
# RESULT MODEL
# ============================================================


@dataclass
class SectorRankResult:

    sector: str

    mode: str

    score: float

    momentum_score: float

    trend_score: float

    breadth_score: float

    volume_score: float

    relative_strength_score: float

    multi_timeframe_score: float

    stock_count: int

    bullish_stock_count: int

    above_ema20_count: int

    above_ema50_count: int

    above_ema200_count: int

    macd_bullish_count: int

    supertrend_buy_count: int

    volume_confirmed_count: int

    confirmation_bullish_count: int

    higher_timeframe_bullish_count: int

    multi_timeframe_confirmed_count: int

    average_change_1d_pct: float

    average_change_5d_pct: float

    average_change_20d_pct: float

    average_volume_ratio: float

    average_relative_strength_pct: float

    average_rsi: float

    average_adx: float

    generated_at: str

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "sector": (
                self.sector
            ),

            "mode": (
                self.mode
            ),

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

            "multi_timeframe_score": round(
                self.multi_timeframe_score,
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

            "macd_bullish_count": (
                self.macd_bullish_count
            ),

            "supertrend_buy_count": (
                self.supertrend_buy_count
            ),

            "volume_confirmed_count": (
                self.volume_confirmed_count
            ),

            "confirmation_bullish_count": (
                self.confirmation_bullish_count
            ),

            "higher_timeframe_bullish_count": (
                self.higher_timeframe_bullish_count
            ),

            "multi_timeframe_confirmed_count": (
                self.multi_timeframe_confirmed_count
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

            "average_rsi": round(
                self.average_rsi,
                2,
            ),

            "average_adx": round(
                self.average_adx,
                2,
            ),

            "generated_at": (
                self.generated_at
            ),
        }


# ============================================================
# SECTOR SCANNER
# ============================================================


class SectorScanner:
    """
    Technical-only NSE sector scanner.

    Flow:

        NSE sector universe
                ↓
        Verified stock technical metrics
                ↓
        Mode-aware sector aggregation
                ↓
        Technical sector strength
                ↓
        Top 10 sectors

    Supported:

        Intraday
        BTST
        Swing

    No NIFTY-500 fixed universe.
    No fundamental filter.
    No fabricated market values.
    """

    MINIMUM_STOCKS_PER_SECTOR = 3


    # ========================================================
    # GENERIC HELPERS
    # ========================================================

    @staticmethod
    def _average(
        values: Iterable[
            float
            | int
            | None
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
                float(
                    number
                )
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


    @staticmethod
    def _percentage_score(
        passed_count: int,
        total: int,
    ) -> float:

        if total <= 0:
            return 0.0

        return (
            passed_count
            / total
            * 100.0
        )


    # ========================================================
    # MODE WEIGHTS
    # ========================================================

    @staticmethod
    def _get_final_weights(
        mode: str,
    ) -> dict[str, float]:

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

        # ----------------------------------------------------
        # INTRADAY
        # Current momentum, breadth and volume
        # get higher importance.
        # ----------------------------------------------------

        if (
            normalized_mode
            == Config.MODE_INTRADAY
        ):

            return {
                "momentum": 0.25,
                "trend": 0.18,
                "breadth": 0.18,
                "volume": 0.18,
                "relative_strength": 0.11,
                "multi_timeframe": 0.10,
            }

        # ----------------------------------------------------
        # BTST
        # Trend + momentum + overnight confirmation.
        # ----------------------------------------------------

        if (
            normalized_mode
            == Config.MODE_BTST
        ):

            return {
                "momentum": 0.23,
                "trend": 0.22,
                "breadth": 0.17,
                "volume": 0.14,
                "relative_strength": 0.11,
                "multi_timeframe": 0.13,
            }

        # ----------------------------------------------------
        # SWING
        # Trend + relative strength + higher timeframe.
        # ----------------------------------------------------

        return {
            "momentum": 0.18,
            "trend": 0.26,
            "breadth": 0.16,
            "volume": 0.10,
            "relative_strength": 0.14,
            "multi_timeframe": 0.16,
        }


    # ========================================================
    # MOMENTUM SCORE
    # ========================================================

    def _momentum_score(
        self,
        metrics: list[
            dict[str, Any]
        ],
        *,
        mode: str,
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

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

        # Intraday primary candles are 5-minute.
        if (
            normalized_mode
            == Config.MODE_INTRADAY
        ):

            score = (
                50.0
                + (
                    average_1d
                    * 10.0
                )
                + (
                    average_5d
                    * 3.0
                )
                + (
                    average_20d
                    * 1.0
                )
            )

        elif (
            normalized_mode
            == Config.MODE_BTST
        ):

            score = (
                50.0
                + (
                    average_1d
                    * 7.0
                )
                + (
                    average_5d
                    * 3.0
                )
                + (
                    average_20d
                    * 1.5
                )
            )

        else:

            score = (
                50.0
                + (
                    average_1d
                    * 3.0
                )
                + (
                    average_5d
                    * 2.5
                )
                + (
                    average_20d
                    * 2.0
                )
            )

        return (
            self._clamp(
                score
            ),

            average_1d,

            average_5d,

            average_20d,
        )


    # ========================================================
    # TREND SCORE
    # ========================================================

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
        int,
        int,
        float,
        float,
    ]:

        if not metrics:

            return (
                0.0,
                0,
                0,
                0,
                0,
                0,
                0.0,
                0.0,
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

        macd_bullish_count = sum(
            1
            for item
            in metrics
            if item.get(
                "macd_bullish"
            ) is True
        )

        supertrend_buy_count = sum(
            1
            for item
            in metrics
            if item.get(
                "supertrend_buy"
            ) is True
        )

        ema20_score = (
            self._percentage_score(
                above_ema20_count,
                total,
            )
        )

        ema50_score = (
            self._percentage_score(
                above_ema50_count,
                total,
            )
        )

        ema200_score = (
            self._percentage_score(
                above_ema200_count,
                total,
            )
        )

        macd_score = (
            self._percentage_score(
                macd_bullish_count,
                total,
            )
        )

        supertrend_score = (
            self._percentage_score(
                supertrend_buy_count,
                total,
            )
        )

        average_rsi = (
            self._average(
                item.get(
                    "rsi"
                )
                for item
                in metrics
            )
        )

        average_adx = (
            self._average(
                item.get(
                    "adx"
                )
                for item
                in metrics
            )
        )

        adx_score = self._clamp(
            (
                average_adx
                / 40.0
            )
            * 100.0
        )

        score = (
            ema20_score
            * 0.22
            + ema50_score
            * 0.18
            + ema200_score
            * 0.12
            + macd_score
            * 0.18
            + supertrend_score
            * 0.20
            + adx_score
            * 0.10
        )

        return (
            self._clamp(
                score
            ),

            above_ema20_count,

            above_ema50_count,

            above_ema200_count,

            macd_bullish_count,

            supertrend_buy_count,

            average_rsi,

            average_adx,
        )


    # ========================================================
    # BREADTH SCORE
    # ========================================================

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
            self._percentage_score(
                bullish_count,
                total,
            )
        )

        return (
            self._clamp(
                score
            ),
            bullish_count,
        )


    # ========================================================
    # VOLUME SCORE
    # ========================================================

    def _volume_score(
        self,
        metrics: list[
            dict[str, Any]
        ],
    ) -> tuple[
        float,
        float,
        int,
    ]:

        if not metrics:

            return (
                0.0,
                0.0,
                0,
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

        volume_confirmed_count = sum(
            1
            for item
            in metrics
            if item.get(
                "volume_confirmed"
            ) is True
        )

        total = len(
            metrics
        )

        ratio_score = (
            self._clamp(
                average_volume_ratio
                * 50.0
            )
        )

        breadth_score = (
            self._percentage_score(
                volume_confirmed_count,
                total,
            )
        )

        final_score = (
            ratio_score
            * 0.60
            + breadth_score
            * 0.40
        )

        return (
            self._clamp(
                final_score
            ),

            average_volume_ratio,

            volume_confirmed_count,
        )


    # ========================================================
    # RELATIVE STRENGTH SCORE
    # ========================================================

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
            + (
                average_rs
                * 5.0
            )
        )

        return (
            self._clamp(
                score
            ),
            average_rs,
        )


    # ========================================================
    # MULTI-TIMEFRAME SCORE
    # ========================================================

    def _multi_timeframe_score(
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

        confirmation_count = sum(
            1
            for item
            in metrics
            if item.get(
                "confirmation_bullish"
            ) is True
        )

        higher_count = sum(
            1
            for item
            in metrics
            if item.get(
                "higher_timeframe_bullish"
            ) is True
        )

        multi_count = sum(
            1
            for item
            in metrics
            if item.get(
                "multi_timeframe_confirmed"
            ) is True
        )

        confirmation_score = (
            self._percentage_score(
                confirmation_count,
                total,
            )
        )

        higher_score = (
            self._percentage_score(
                higher_count,
                total,
            )
        )

        multi_score = (
            self._percentage_score(
                multi_count,
                total,
            )
        )

        final_score = (
            confirmation_score
            * 0.30
            + higher_score
            * 0.30
            + multi_score
            * 0.40
        )

        return (
            self._clamp(
                final_score
            ),

            confirmation_count,

            higher_count,

            multi_count,
        )


    # ========================================================
    # ONE SECTOR
    # ========================================================

    def calculate_sector_score(
        self,
        *,
        sector: str,
        stock_metrics: list[
            dict[str, Any]
        ],
        mode: str | None = None,
    ) -> SectorRankResult:

        normalized_sector = str(
            sector
            or ""
        ).strip()

        if not normalized_sector:

            raise (
                SectorScannerError(
                    (
                        "Sector name "
                        "is missing."
                    )
                )
            )

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

        valid_metrics = [
            item
            for item
            in stock_metrics
            if isinstance(
                item,
                dict,
            )
        ]

        if (
            len(
                valid_metrics
            )
            < self
            .MINIMUM_STOCKS_PER_SECTOR
        ):

            raise (
                SectorScannerError(
                    (
                        f"{normalized_sector}: "
                        "at least "
                        f"{self.MINIMUM_STOCKS_PER_SECTOR} "
                        "verified stocks "
                        "are required."
                    )
                )
            )

        (
            momentum_score,
            average_1d,
            average_5d,
            average_20d,
        ) = (
            self._momentum_score(
                valid_metrics,
                mode=(
                    normalized_mode
                ),
            )
        )

        (
            trend_score,
            above_ema20_count,
            above_ema50_count,
            above_ema200_count,
            macd_bullish_count,
            supertrend_buy_count,
            average_rsi,
            average_adx,
        ) = (
            self._trend_score(
                valid_metrics
            )
        )

        (
            breadth_score,
            bullish_stock_count,
        ) = (
            self._breadth_score(
                valid_metrics
            )
        )

        (
            volume_score,
            average_volume_ratio,
            volume_confirmed_count,
        ) = (
            self._volume_score(
                valid_metrics
            )
        )

        (
            relative_strength_score,
            average_relative_strength,
        ) = (
            self
            ._relative_strength_score(
                valid_metrics
            )
        )

        (
            multi_timeframe_score,
            confirmation_bullish_count,
            higher_timeframe_bullish_count,
            multi_timeframe_confirmed_count,
        ) = (
            self
            ._multi_timeframe_score(
                valid_metrics
            )
        )

        weights = (
            self
            ._get_final_weights(
                normalized_mode
            )
        )

        final_score = (
            momentum_score
            * weights[
                "momentum"
            ]
            + trend_score
            * weights[
                "trend"
            ]
            + breadth_score
            * weights[
                "breadth"
            ]
            + volume_score
            * weights[
                "volume"
            ]
            + relative_strength_score
            * weights[
                "relative_strength"
            ]
            + multi_timeframe_score
            * weights[
                "multi_timeframe"
            ]
        )

        return (
            SectorRankResult(
                sector=(
                    normalized_sector
                ),

                mode=(
                    normalized_mode
                ),

                score=(
                    self._clamp(
                        final_score
                    )
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

                multi_timeframe_score=(
                    multi_timeframe_score
                ),

                stock_count=len(
                    valid_metrics
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

                macd_bullish_count=(
                    macd_bullish_count
                ),

                supertrend_buy_count=(
                    supertrend_buy_count
                ),

                volume_confirmed_count=(
                    volume_confirmed_count
                ),

                confirmation_bullish_count=(
                    confirmation_bullish_count
                ),

                higher_timeframe_bullish_count=(
                    higher_timeframe_bullish_count
                ),

                multi_timeframe_confirmed_count=(
                    multi_timeframe_confirmed_count
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

                average_rsi=(
                    average_rsi
                ),

                average_adx=(
                    average_adx
                ),

                generated_at=(
                    utc_now()
                    .isoformat()
                ),
            )
        )


    # ========================================================
    # GROUP METRICS BY SECTOR
    # ========================================================

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
        list[
            dict[str, Any]
        ],
    ]:

        sector_metrics: dict[
            str,
            list[
                dict[str, Any]
            ],
        ] = {}

        for stock in stocks:

            symbol = (
                normalize_symbol(
                    stock.symbol
                )
            )

            if not symbol:
                continue

            metrics = (
                metrics_by_symbol
                .get(
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


    # ========================================================
    # RANK ALL SECTORS
    # ========================================================

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
        mode: str | None = None,
    ) -> list[
        SectorRankResult
    ]:

        normalized_mode = (
            Config
            .normalize_trading_mode(
                mode
            )
        )

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
            ) in (
                sector_metrics
                .items()
            ):

                if (
                    len(
                        metrics
                    )
                    < self
                    .MINIMUM_STOCKS_PER_SECTOR
                ):

                    continue

                try:

                    result = (
                        self
                        .calculate_sector_score(
                            sector=(
                                sector
                            ),
                            stock_metrics=(
                                metrics
                            ),
                            mode=(
                                normalized_mode
                            ),
                        )
                    )

                    results.append(
                        result
                    )

                except (
                    SectorScannerError
                ):

                    continue

            # Strongest sector first.
            results.sort(
                key=lambda item: (
                    -item.score,
                    -item.multi_timeframe_score,
                    -item.breadth_score,
                    -item.trend_score,
                    -item.momentum_score,
                    -item.relative_strength_score,
                    item.sector,
                )
            )

            logger.info(
                (
                    "Sector ranking completed | "
                    "mode=%s | sectors=%s"
                ),
                normalized_mode,
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
                    mode=(
                        normalized_mode
                    ),
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
                mode=(
                    normalized_mode
                ),
            )

            raise (
                SectorScannerError(
                    (
                        "Unable to rank "
                        "NSE sectors."
                    )
                )
            ) from exception


    # ========================================================
    # TOP SECTORS
    # ========================================================

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
        mode: str | None = None,
    ) -> list[
        SectorRankResult
    ]:

        if limit is None:

            limit = (
                Config
                .TOP_SECTORS_COUNT
            )

        try:

            safe_limit = int(
                limit
            )

        except (
            TypeError,
            ValueError,
        ):

            safe_limit = (
                Config
                .TOP_SECTORS_COUNT
            )

        safe_limit = max(
            1,
            min(
                safe_limit,
                Config
                .TOP_SECTORS_COUNT,
            ),
        )

        ranked = (
            self
            .rank_sectors(
                stocks=(
                    stocks
                ),
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
                mode=(
                    mode
                ),
            )
        )

        return ranked[
            :safe_limit
        ]


    # ========================================================
    # TOP SECTOR NAMES
    # ========================================================

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
        mode: str | None = None,
    ) -> list[str]:

        top_sectors = (
            self
            .get_top_sectors(
                stocks=(
                    stocks
                ),
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
                limit=(
                    limit
                ),
                mode=(
                    mode
                ),
            )
        )

        return [
            item.sector
            for item
            in top_sectors
        ]


    # ========================================================
    # TOP SECTORS AS DICTS
    # ========================================================

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
        mode: str | None = None,
    ) -> list[
        dict[str, Any]
    ]:

        return [
            result.to_dict()
            for result
            in self.get_top_sectors(
                stocks=(
                    stocks
                ),
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
                limit=(
                    limit
                ),
                mode=(
                    mode
                ),
            )
        ]


# ============================================================
# GLOBAL INSTANCE
# ============================================================


_global_sector_scanner: (
    SectorScanner | None
) = None


_global_sector_scanner_lock = (
    __import__(
        "threading"
    ).Lock()
)


def get_sector_scanner(
) -> SectorScanner:

    global _global_sector_scanner

    if (
        _global_sector_scanner
        is not None
    ):

        return (
            _global_sector_scanner
        )

    with (
        _global_sector_scanner_lock
    ):

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
