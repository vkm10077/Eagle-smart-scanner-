from __future__ import annotations

import threading
from typing import Any

from config import Config
from services.common_stock_engine import (
    archive_current_as_previous,
    build_and_save_common_stocks,
    get_common_stocks,
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
    build_top_sector_stock_universe,
)
from services.technical_metrics_service import (
    TechnicalMetricsService,
    get_technical_metrics_service,
)
from utils.helpers import (
    clean_text,
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


class ScannerOrchestratorError(
    RuntimeError
):
    """Raised when Eagle scanner orchestration fails."""


class ScannerOrchestrator:
    """
    Master Eagle Smart Scanner pipeline.

    Pipeline:

        Dynamic NSE Sector Universe
                    ↓
        Technical Metrics
                    ↓
        Rank All Sectors
                    ↓
        Top 10 Sectors
                    ↓
        Top 10 Stocks Per Sector
                    ↓
        Current Day Candidates
                    ↓
        Previous Day ∩ Current Day
                    ↓
        Common Stocks
                    ↓
        Full Technical Analysis
                    ↓
        STRONG BUY Only

    INTRADAY and SWING candidate history
    are maintained separately.
    """

    def __init__(
        self,
        *,
        universe_service: (
            NSESectorUniverseService | None
        ) = None,
        metrics_service: (
            TechnicalMetricsService | None
        ) = None,
        sector_scanner: (
            SectorScanner | None
        ) = None,
        market_data_service: (
            MarketDataService | None
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

    # =========================================================
    # MODE
    # =========================================================

    @staticmethod
    def _normalize_mode(
        mode: str,
    ) -> str:

        return (
            Config.normalize_trading_mode(
                mode
            )
        )

    # =========================================================
    # BUILD CANDIDATE UNIVERSE
    # =========================================================

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

        using technical metrics only.
        """

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        normalized_token = (
            clean_text(
                access_token
            )
        )

        if not normalized_token:
            raise ScannerOrchestratorError(
                "FYERS access token is required."
            )

        # -----------------------------------------------------
        # Dynamic NSE sector stock universe
        # -----------------------------------------------------

        stocks = (
            self.universe_service
            .get_all_stocks(
                force_refresh=(
                    force_refresh
                )
            )
        )

        if not stocks:
            raise ScannerOrchestratorError(
                (
                    "Dynamic NSE sector "
                    "universe is empty."
                )
            )

        # -----------------------------------------------------
        # Build verified technical metrics
        # -----------------------------------------------------

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

        # -----------------------------------------------------
        # Rank sectors
        # -----------------------------------------------------

        top_sector_results = (
            self.sector_scanner
            .get_top_sectors(
                stocks=(
                    stocks
                ),
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
            result.sector
            for result
            in top_sector_results
        ]

        # -----------------------------------------------------
        # Top stocks per selected sector
        # -----------------------------------------------------

        top_stocks = (
            build_top_sector_stock_universe(
                top_sectors=(
                    top_sector_names
                ),
                stocks=(
                    stocks
                ),
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
            )
        )

        if not top_stocks:
            raise ScannerOrchestratorError(
                (
                    "No top stocks were produced "
                    "from selected sectors."
                )
            )

        # -----------------------------------------------------
        # Save CURRENT candidates
        #
        # IMPORTANT:
        # INTRADAY and SWING are stored separately.
        # -----------------------------------------------------

        current_candidates = (
            save_current_day_candidates(
                top_stocks,
                mode=(
                    normalized_mode
                ),
            )
        )

        return {
            "mode": (
                normalized_mode
            ),

            "top_sectors": [
                item.to_dict()
                for item
                in top_sector_results
            ],

            "top_sector_names": (
                top_sector_names
            ),

            "sector_count": (
                len(
                    top_sector_results
                )
            ),

            "candidate_count": (
                len(
                    current_candidates
                )
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

    # =========================================================
    # BUILD COMMON UNIVERSE
    # =========================================================

    def build_common_universe(
        self,
        *,
        mode: str,
    ) -> list[dict[str, Any]]:
        """
        Previous Day ∩ Current Day.

        Mode-specific:
        - Intraday compares only Intraday history
        - Swing compares only Swing history
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

        return common_stocks

    # =========================================================
    # FINAL TECHNICAL SCAN
    # =========================================================

    def scan_common_stocks(
        self,
        access_token: str,
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Run full technical analysis only on
        previous/current common stocks.

        MarketDataService returns only
        STRONG BUY results.
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

        # Additional safety:
        # Even if downstream implementation changes,
        # only STRONG BUY survives here.

        strong_buy_results = [
            item
            for item
            in results
            if (
                isinstance(
                    item,
                    dict,
                )
                and clean_text(
                    item.get(
                        "signal"
                    )
                ).upper()
                == "STRONG BUY"
            )
        ]

        strong_buy_results.sort(
            key=lambda item: (
                -float(
                    item.get(
                        "technical_score",
                        0.0,
                    )
                    or 0.0
                ),
                -float(
                    item.get(
                        "risk_reward",
                        0.0,
                    )
                    or 0.0
                ),
                clean_text(
                    item.get(
                        "symbol"
                    )
                ),
            )
        )

        return (
            strong_buy_results
        )

    # =========================================================
    # FULL SCAN
    # =========================================================

    def run_scan(
        self,
        access_token: str,
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """
        Run complete Eagle Smart Scanner pipeline.
        """

        normalized_token = (
            clean_text(
                access_token
            )
        )

        if not normalized_token:
            raise ScannerOrchestratorError(
                "FYERS access token is required."
            )

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        with self._scan_lock:

            try:

                # ---------------------------------------------
                # STEP 1
                # Top sectors + Top stocks
                # ---------------------------------------------

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

                # ---------------------------------------------
                # STEP 2
                # Previous ∩ Current
                # ---------------------------------------------

                common_stocks = (
                    self.build_common_universe(
                        mode=(
                            normalized_mode
                        )
                    )
                )

                # ---------------------------------------------
                # STEP 3
                # Final technical scan
                # ---------------------------------------------

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
                    len(
                        candidate_data.get(
                            "top_sectors",
                            [],
                        )
                    ),
                    candidate_data.get(
                        "candidate_count",
                        0,
                    ),
                    len(
                        common_stocks
                    ),
                    len(
                        strong_buy_results
                    ),
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
                        sector_count=len(
                            candidate_data.get(
                                "top_sectors",
                                [],
                            )
                        ),
                        candidate_count=(
                            candidate_data.get(
                                "candidate_count",
                                0,
                            )
                        ),
                        common_count=(
                            len(
                                common_stocks
                            )
                        ),
                        strong_buy_count=(
                            len(
                                strong_buy_results
                            )
                        ),
                    ),
                )

                return {
                    "success": True,

                    "status": (
                        "success"
                    ),

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

                    "common_stocks": (
                        common_stocks
                    ),

                    "results": (
                        strong_buy_results
                    ),

                    "updated_at": (
                        utc_now().isoformat()
                    ),
                }

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
                        f"failed for {normalized_mode}."
                    )
                ) from exception

    # =========================================================
    # TRADING DAY ARCHIVE
    # =========================================================

    def start_new_trading_day(
        self,
        *,
        mode: str,
    ) -> bool:
        """
        Archive the latest CURRENT candidate list
        into PREVIOUS storage for one specific mode.

        Example:

        Swing current
            -> Swing previous

        Intraday current
            -> Intraday previous
        """

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        return (
            archive_current_as_previous(
                mode=(
                    normalized_mode
                )
            )
        )

    # =========================================================
    # COMMON STOCKS FOR ONE MODE
    # =========================================================

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

    # =========================================================
    # STATUS
    # =========================================================

    def status(
        self,
        *,
        mode: str | None = None,
    ) -> dict[str, Any]:

        normalized_mode = (
            self._normalize_mode(
                mode
                or Config.DEFAULT_TRADING_MODE
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


# =============================================================
# GLOBAL INSTANCE
# =============================================================

_global_scanner_orchestrator: (
    ScannerOrchestrator | None
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
