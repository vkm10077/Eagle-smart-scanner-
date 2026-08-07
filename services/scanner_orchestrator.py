from __future__ import annotations

import threading
from typing import Any

from config import Config

from services.common_stock_engine import (
    build_and_save_common_stocks,
    get_common_stocks,
    rollover_if_new_day,
    save_current_day_candidates,
)

from services.market_data_service import (
    MarketDataService,
    get_market_data_service,
)

from services.nse_sector_universe_service import (
    NSESectorUniverseService,
    get_nse_sector_universe_service,
)

from services.sector_scanner import (
    SectorScanner,
    get_sector_scanner,
)

from services.stock_ranker import (
    RankedStock,
    build_top_sector_stock_universe,
    get_top_stocks_for_sector,
)

from services.technical_metrics_service import (
    TechnicalMetricsService,
    get_technical_metrics_service,
)

from utils.helpers import (
    clean_text,
    safe_float,
    utc_now,
)

from utils.logger import (
    build_log_extra,
    get_logger,
    log_exception,
)


logger = get_logger(
    "services.scanner_orchestrator"
)


# ============================================================
# ERROR
# ============================================================

class ScannerOrchestratorError(
    RuntimeError
):
    """
    Raised when the complete Eagle scanner
    pipeline cannot be completed.
    """


# ============================================================
# ORCHESTRATOR
# ============================================================

class ScannerOrchestrator:
    """
    Eagle Smart Scanner master pipeline.

    Final Flow:

        Dynamic NSE Sector Universe
                    ↓
        Technical Metrics
                    ↓
        Rank All NSE Sectors
                    ↓
        Top 10 Sectors
                    ↓
        Top 10 Stocks per Sector
                    ↓
        Maximum 100 Candidates
                    ↓
        Save Current-Day Candidates
                    ↓
        Previous Day ∩ Current Day
                    ↓
        Common Stocks
                    ↓
        Full Multi-Timeframe Technical Scan
                    ↓
        STRONG BUY only

    Dashboard also receives:

        Top Sector
            ↓
        Top 10 Stocks of that Sector

    Therefore tapping a sector can immediately
    show its Top 10 technically ranked stocks.

    Important:
    - No fixed NIFTY 500 universe.
    - No fundamental analysis.
    - No fake data.
    - Intraday and Swing history are separate.
    """

    def __init__(
        self,
        *,
        universe_service: (
            NSESectorUniverseService
            | None
        ) = None,
        metrics_service: (
            TechnicalMetricsService
            | None
        ) = None,
        sector_scanner: (
            SectorScanner
            | None
        ) = None,
        market_data_service: (
            MarketDataService
            | None
        ) = None,
    ) -> None:

        self.universe_service = (
            universe_service
            or get_nse_sector_universe_service()
        )

        self.metrics_service = (
            metrics_service
            or get_technical_metrics_service()
        )

        self.sector_scanner = (
            sector_scanner
            or get_sector_scanner()
        )

        self.market_data_service = (
            market_data_service
            or get_market_data_service()
        )

        self._scan_lock = (
            threading.RLock()
        )

    # ========================================================
    # MODE
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

    # ========================================================
    # SAFE NUMBER
    # ========================================================

    @staticmethod
    def _number(
        value: Any,
    ) -> float:

        number = safe_float(
            value,
            default=0.0,
        )

        return float(
            number
            or 0.0
        )

    # ========================================================
    # RANKED STOCK → DICT
    # ========================================================

    @staticmethod
    def _ranked_stock_to_dict(
        stock: RankedStock,
    ) -> dict[str, Any]:

        data = stock.to_dict()

        return {
            "symbol": (
                data.get(
                    "symbol",
                    ""
                )
            ),

            "company_name": (
                data.get(
                    "company_name",
                    ""
                )
            ),

            "sector": (
                data.get(
                    "sector",
                    ""
                )
            ),

            "score": (
                data.get(
                    "score",
                    0.0,
                )
            ),

            "momentum_score": (
                data.get(
                    "momentum_score",
                    0.0,
                )
            ),

            "trend_score": (
                data.get(
                    "trend_score",
                    0.0,
                )
            ),

            "volume_score": (
                data.get(
                    "volume_score",
                    0.0,
                )
            ),

            "rsi_score": (
                data.get(
                    "rsi_score",
                    0.0,
                )
            ),

            "relative_strength_score": (
                data.get(
                    "relative_strength_score",
                    0.0,
                )
            ),
        }

    # ========================================================
    # TOP STOCKS BY SECTOR
    # ========================================================

    def _build_top_stocks_by_sector(
        self,
        *,
        top_sector_names: list[str],
        stocks: list[Any],
        metrics_by_symbol: dict[
            str,
            dict[str, Any],
        ],
    ) -> dict[
        str,
        list[dict[str, Any]],
    ]:

        output: dict[
            str,
            list[dict[str, Any]],
        ] = {}

        for sector in top_sector_names:

            ranked_stocks = (
                get_top_stocks_for_sector(
                    sector=sector,
                    stocks=stocks,
                    metrics_by_symbol=(
                        metrics_by_symbol
                    ),
                    limit=(
                        Config
                        .TOP_STOCKS_PER_SECTOR
                    ),
                )
            )

            output[
                sector
            ] = [
                self._ranked_stock_to_dict(
                    stock
                )
                for stock
                in ranked_stocks
            ]

        return output

    # ========================================================
    # ENRICH TOP SECTOR RESPONSE
    # ========================================================

    @staticmethod
    def _attach_top_stocks_to_sectors(
        sector_results: list[Any],
        top_stocks_by_sector: dict[
            str,
            list[dict[str, Any]],
        ],
    ) -> list[dict[str, Any]]:

        output: list[
            dict[str, Any]
        ] = []

        for rank, sector_result in enumerate(
            sector_results,
            start=1,
        ):

            if hasattr(
                sector_result,
                "to_dict",
            ):
                sector_data = (
                    sector_result.to_dict()
                )

            elif isinstance(
                sector_result,
                dict,
            ):
                sector_data = dict(
                    sector_result
                )

            else:
                continue

            sector_name = clean_text(
                sector_data.get(
                    "sector"
                )
            )

            sector_stocks = (
                top_stocks_by_sector.get(
                    sector_name,
                    [],
                )
            )

            sector_data[
                "rank"
            ] = rank

            sector_data[
                "top_stocks"
            ] = sector_stocks

            sector_data[
                "top_stock_count"
            ] = len(
                sector_stocks
            )

            output.append(
                sector_data
            )

        return output

    # ========================================================
    # CANDIDATE UNIVERSE
    # ========================================================

    def build_candidate_universe(
        self,
        access_token: str,
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """
        Build:

            Top 10 sectors
                    ×
            Top 10 stocks per sector

        Maximum candidate universe = 100.
        """

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        normalized_token = clean_text(
            access_token
        )

        if not normalized_token:

            raise ScannerOrchestratorError(
                (
                    "FYERS access token "
                    "is required."
                )
            )

        # ----------------------------------------------------
        # Trading-day rollover
        # ----------------------------------------------------

        try:

            rollover_if_new_day(
                mode=(
                    normalized_mode
                )
            )

        except Exception as exception:

            logger.warning(
                (
                    "Trading-day rollover "
                    "check failed for %s: %s"
                ),
                normalized_mode,
                exception,
            )

        # ----------------------------------------------------
        # Dynamic NSE Sector Universe
        # ----------------------------------------------------

        stocks = (
            self.universe_service
            .get_all_stocks(
                force_refresh=(
                    force_refresh
                )
            )
        )

        stocks = list(
            stocks
        )

        if not stocks:

            raise ScannerOrchestratorError(
                (
                    "Dynamic NSE sector "
                    "universe is empty."
                )
            )

        logger.info(
            (
                "Universe loaded | "
                "mode=%s | stocks=%s"
            ),
            normalized_mode,
            len(
                stocks
            ),
        )

        # ----------------------------------------------------
        # Technical Metrics
        # ----------------------------------------------------

        metrics_by_symbol = (
            self.metrics_service
            .build_metrics_for_stocks(
                normalized_token,
                stocks,
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

        if not metrics_by_symbol:

            raise ScannerOrchestratorError(
                (
                    "No verified technical "
                    "metrics were produced."
                )
            )

        logger.info(
            (
                "Technical metrics ready | "
                "mode=%s | metrics=%s"
            ),
            normalized_mode,
            len(
                metrics_by_symbol
            ),
        )

        # ----------------------------------------------------
        # Rank Sectors
        # ----------------------------------------------------

        top_sector_results = (
            self.sector_scanner
            .get_top_sectors(
                stocks=stocks,
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
                limit=(
                    Config.TOP_SECTORS_COUNT
                ),
            )
        )

        if not top_sector_results:

            raise ScannerOrchestratorError(
                (
                    "No technically strong "
                    "sector was found."
                )
            )

        top_sector_names = [
            clean_text(
                result.sector
            )
            for result
            in top_sector_results
            if clean_text(
                result.sector
            )
        ]

        # ----------------------------------------------------
        # Top 10 stocks of each selected sector
        # ----------------------------------------------------

        top_stocks_by_sector = (
            self._build_top_stocks_by_sector(
                top_sector_names=(
                    top_sector_names
                ),
                stocks=stocks,
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
            )
        )

        # ----------------------------------------------------
        # Flat maximum 100-stock candidate universe
        # ----------------------------------------------------

        top_stocks_flat = (
            build_top_sector_stock_universe(
                top_sectors=(
                    top_sector_names
                ),
                stocks=stocks,
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
            )
        )

        if not top_stocks_flat:

            raise ScannerOrchestratorError(
                (
                    "No top stocks were "
                    "produced from the "
                    "selected sectors."
                )
            )

        # Defensive maximum limit
        top_stocks_flat = (
            top_stocks_flat[
                :Config.MAX_SCANNER_UNIVERSE
            ]
        )

        # ----------------------------------------------------
        # Enriched sectors for dashboard
        # ----------------------------------------------------

        enriched_top_sectors = (
            self
            ._attach_top_stocks_to_sectors(
                top_sector_results,
                top_stocks_by_sector,
            )
        )

        # ----------------------------------------------------
        # Save CURRENT candidates
        # ----------------------------------------------------

        current_candidates = (
            save_current_day_candidates(
                top_stocks_flat,
                mode=(
                    normalized_mode
                ),
            )
        )

        logger.info(
            (
                "Candidate universe built | "
                "mode=%s | sectors=%s | "
                "candidates=%s"
            ),
            normalized_mode,
            len(
                enriched_top_sectors
            ),
            len(
                current_candidates
            ),
            extra=build_log_extra(
                component=(
                    "scanner_orchestrator"
                ),
                event=(
                    "candidate_universe_built"
                ),
                status="success",
                mode=(
                    normalized_mode
                ),
                sector_count=(
                    len(
                        enriched_top_sectors
                    )
                ),
                candidate_count=(
                    len(
                        current_candidates
                    )
                ),
            ),
        )

        return {
            "mode": (
                normalized_mode
            ),

            "top_sectors": (
                enriched_top_sectors
            ),

            "top_sector_names": (
                top_sector_names
            ),

            "top_stocks_by_sector": (
                top_stocks_by_sector
            ),

            "sector_count": (
                len(
                    enriched_top_sectors
                )
            ),

            "candidate_count": (
                len(
                    current_candidates
                )
            ),

            "maximum_candidate_count": (
                Config.MAX_SCANNER_UNIVERSE
            ),

            "candidates": (
                current_candidates
            ),

            "metrics_count": (
                len(
                    metrics_by_symbol
                )
            ),

            "updated_at": (
                utc_now().isoformat()
            ),
        }

    # ========================================================
    # COMMON UNIVERSE
    # ========================================================

    def build_common_universe(
        self,
        *,
        mode: str,
    ) -> list[dict[str, Any]]:
        """
        Previous Day ∩ Current Day.

        Intraday and Swing are kept separate.
        """

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        common_stocks = (
            build_and_save_common_stocks(
                mode=(
                    normalized_mode
                )
            )
        )

        return [
            dict(
                stock
            )
            for stock
            in common_stocks
            if isinstance(
                stock,
                dict,
            )
        ]

    # ========================================================
    # FINAL STRONG BUY SCAN
    # ========================================================

    def scan_common_stocks(
        self,
        access_token: str,
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Run complete technical analysis
        only on previous/current common stocks.

        Final output:
            STRONG BUY only.
        """

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        common_stocks = (
            get_common_stocks(
                mode=(
                    normalized_mode
                )
            )
        )

        if not common_stocks:

            logger.info(
                (
                    "No common stocks "
                    "available yet | mode=%s"
                ),
                normalized_mode,
            )

            return []

        results = (
            self.market_data_service
            .scan_stocks(
                access_token,
                common_stocks,
                mode=(
                    normalized_mode
                ),
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
            )
        )

        strong_buy_results: list[
            dict[str, Any]
        ] = []

        for item in results:

            if not isinstance(
                item,
                dict,
            ):
                continue

            signal = clean_text(
                item.get(
                    "signal"
                )
            ).upper()

            if signal != "STRONG BUY":
                continue

            strong_buy_results.append(
                item
            )

        strong_buy_results.sort(
            key=lambda item: (
                -self._number(
                    item.get(
                        "technical_score"
                    )
                ),
                -self._number(
                    item.get(
                        "risk_reward"
                    )
                ),
                clean_text(
                    item.get(
                        "symbol"
                    )
                ),
            )
        )

        return strong_buy_results

    # ========================================================
    # COMPLETE SCAN
    # ========================================================

    def run_scan(
        self,
        access_token: str,
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """
        Run complete Eagle scanner.
        """

        normalized_token = clean_text(
            access_token
        )

        if not normalized_token:

            raise ScannerOrchestratorError(
                (
                    "FYERS access token "
                    "is required."
                )
            )

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        with self._scan_lock:

            try:

                # ============================================
                # STEP 1
                # Top sectors + Top stocks
                # ============================================

                candidate_data = (
                    self.build_candidate_universe(
                        normalized_token,
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

                # ============================================
                # STEP 2
                # Previous Day ∩ Current Day
                # ============================================

                common_stocks = (
                    self.build_common_universe(
                        mode=(
                            normalized_mode
                        )
                    )
                )

                # ============================================
                # STEP 3
                # STRONG BUY analysis
                # ============================================

                strong_buy_results = (
                    self.scan_common_stocks(
                        normalized_token,
                        mode=(
                            normalized_mode
                        ),
                        benchmark_change_pct=(
                            benchmark_change_pct
                        ),
                    )
                )

                payload = {
                    "success": True,

                    "status": "success",

                    "mode": (
                        normalized_mode
                    ),

                    "top_sectors": (
                        candidate_data.get(
                            "top_sectors",
                            [],
                        )
                    ),

                    "top_sector_names": (
                        candidate_data.get(
                            "top_sector_names",
                            [],
                        )
                    ),

                    "top_stocks_by_sector": (
                        candidate_data.get(
                            "top_stocks_by_sector",
                            {},
                        )
                    ),

                    "sector_count": (
                        candidate_data.get(
                            "sector_count",
                            0,
                        )
                    ),

                    "metrics_count": (
                        candidate_data.get(
                            "metrics_count",
                            0,
                        )
                    ),

                    "candidate_count": (
                        candidate_data.get(
                            "candidate_count",
                            0,
                        )
                    ),

                    "maximum_candidate_count": (
                        Config
                        .MAX_SCANNER_UNIVERSE
                    ),

                    "common_count": (
                        len(
                            common_stocks
                        )
                    ),

                    "strong_buy_count": (
                        len(
                            strong_buy_results
                        )
                    ),

                    "candidates": (
                        candidate_data.get(
                            "candidates",
                            [],
                        )
                    ),

                    "common_stocks": (
                        common_stocks
                    ),

                    "results": (
                        strong_buy_results
                    ),

                    "verified": True,

                    "technical_only": True,

                    "fixed_nifty500": False,

                    "updated_at": (
                        utc_now().isoformat()
                    ),
                }

                logger.info(
                    (
                        "Eagle scan completed | "
                        "mode=%s | "
                        "sectors=%s | "
                        "candidates=%s | "
                        "common=%s | "
                        "strong_buy=%s"
                    ),
                    normalized_mode,
                    payload[
                        "sector_count"
                    ],
                    payload[
                        "candidate_count"
                    ],
                    payload[
                        "common_count"
                    ],
                    payload[
                        "strong_buy_count"
                    ],
                    extra=build_log_extra(
                        component=(
                            "scanner_orchestrator"
                        ),
                        event=(
                            "scan_completed"
                        ),
                        status="success",
                        mode=(
                            normalized_mode
                        ),
                        sector_count=(
                            payload[
                                "sector_count"
                            ]
                        ),
                        candidate_count=(
                            payload[
                                "candidate_count"
                            ]
                        ),
                        common_count=(
                            payload[
                                "common_count"
                            ]
                        ),
                        strong_buy_count=(
                            payload[
                                "strong_buy_count"
                            ]
                        ),
                    ),
                )

                return payload

            except ScannerOrchestratorError:
                raise

            except Exception as exception:

                log_exception(
                    logger,
                    (
                        "Eagle scanner "
                        "orchestration failed"
                    ),
                    exception=(
                        exception
                    ),
                    component=(
                        "scanner_orchestrator"
                    ),
                    error_code=(
                        "SCANNER_ORCHESTRATION_FAILED"
                    ),
                    mode=(
                        normalized_mode
                    ),
                )

                raise ScannerOrchestratorError(
                    (
                        "Eagle Smart Scanner "
                        f"failed for "
                        f"{normalized_mode}: "
                        f"{exception}"
                    )
                ) from exception

    # ========================================================
    # SAVED COMMON STOCKS
    # ========================================================

    def get_saved_common_stocks(
        self,
        *,
        mode: str,
    ) -> list[dict[str, Any]]:

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        return (
            get_common_stocks(
                mode=(
                    normalized_mode
                )
            )
        )

    # ========================================================
    # STATUS
    # ========================================================

    def status(
        self,
        *,
        mode: str | None = None,
    ) -> dict[str, Any]:

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        try:

            universe_health = (
                self.universe_service
                .health()
            )

        except Exception as exception:

            universe_health = {
                "status": (
                    "unhealthy"
                ),

                "is_healthy": False,

                "error": str(
                    exception
                ),
            }

        common_stocks = (
            get_common_stocks(
                mode=(
                    normalized_mode
                )
            )
        )

        return {
            "service": (
                "Eagle Scanner Orchestrator"
            ),

            "mode": (
                normalized_mode
            ),

            "universe": (
                universe_health
            ),

            "common_stock_count": (
                len(
                    common_stocks
                )
            ),

            "top_sector_limit": (
                Config.TOP_SECTORS_COUNT
            ),

            "top_stocks_per_sector": (
                Config.TOP_STOCKS_PER_SECTOR
            ),

            "maximum_candidates": (
                Config.MAX_SCANNER_UNIVERSE
            ),

            "supported_modes": [
                Config.MODE_INTRADAY,
                Config.MODE_SWING,
            ],

            "technical_only": True,

            "fixed_nifty500": False,

            "updated_at": (
                utc_now().isoformat()
            ),
        }


# ============================================================
# GLOBAL INSTANCE
# ============================================================

_global_scanner_orchestrator: (
    ScannerOrchestrator
    | None
) = None

_global_scanner_lock = (
    threading.Lock()
)


def get_scanner_orchestrator(
) -> ScannerOrchestrator:

    global _global_scanner_orchestrator

    if (
        _global_scanner_orchestrator
        is not None
    ):
        return (
            _global_scanner_orchestrator
        )

    with _global_scanner_lock:

        if (
            _global_scanner_orchestrator
            is None
        ):

            _global_scanner_orchestrator = (
                ScannerOrchestrator()
            )

    return (
        _global_scanner_orchestrator
    )
