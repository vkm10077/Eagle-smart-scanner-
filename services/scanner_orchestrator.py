from __future__ import annotations

import threading
from dataclasses import asdict
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
    RankedStock,
    build_top_sector_stock_universe,
)
from services.technical_metrics_service import (
    TechnicalMetricsService,
    get_technical_metrics_service,
)
from utils.helpers import (
    clean_text,
    normalize_symbol,
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
    """Raised when the Eagle scanner pipeline fails."""


class ScannerOrchestrator:
    """
    Master Eagle Smart Scanner workflow.

    Flow:

    1. Load dynamic NSE sector universe
    2. Build technical metrics
    3. Rank all sectors
    4. Select Top 10 sectors
    5. Rank stocks inside selected sectors
    6. Select Top 10 stocks per sector
    7. Save current-day candidates
    8. Compare with previous-day candidates
    9. Keep only common stocks
    10. Run full technical analysis
    11. Return only STRONG BUY
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

        self._scan_lock = threading.RLock()

    # =========================================================
    # PREPARE CANDIDATES
    # =========================================================

    def build_candidate_universe(
        self,
        access_token: str,
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:

        normalized_mode = (
            Config.normalize_trading_mode(
                mode
            )
        )

        stocks = (
            self.universe_service
            .get_all_stocks(
                force_refresh=force_refresh
            )
        )

        if not stocks:
            raise ScannerOrchestratorError(
                "Dynamic NSE sector universe is empty."
            )

        metrics_by_symbol = (
            self.metrics_service
            .build_metrics_for_stocks(
                access_token,
                stocks,
                mode=normalized_mode,
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
                force_refresh=force_refresh,
            )
        )

        if not metrics_by_symbol:
            raise ScannerOrchestratorError(
                "No verified technical metrics were produced."
            )

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

        top_sector_names = [
            result.sector
            for result
            in top_sector_results
        ]

        if not top_sector_names:
            raise ScannerOrchestratorError(
                "No technically strong sector was found."
            )

        top_stocks = (
            build_top_sector_stock_universe(
                top_sectors=top_sector_names,
                stocks=stocks,
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
            )
        )

        if not top_stocks:
            raise ScannerOrchestratorError(
                "No top stocks were produced from selected sectors."
            )

        current_candidates = (
            save_current_day_candidates(
                top_stocks
            )
        )

        return {
            "mode": normalized_mode,
            "top_sectors": [
                item.to_dict()
                for item
                in top_sector_results
            ],
            "top_sector_names": (
                top_sector_names
            ),
            "candidate_count": len(
                current_candidates
            ),
            "candidates": (
                current_candidates
            ),
            "metrics_count": len(
                metrics_by_symbol
            ),
            "updated_at": (
                utc_now().isoformat()
            ),
        }

    # =========================================================
    # COMMON STOCKS
    # =========================================================

    def build_common_universe(
        self,
    ) -> list[dict[str, Any]]:

        common_stocks = (
            build_and_save_common_stocks()
        )

        return common_stocks

    # =========================================================
    # FINAL STRONG BUY SCAN
    # =========================================================

    def scan_common_stocks(
        self,
        access_token: str,
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
    ) -> list[dict[str, Any]]:

        normalized_mode = (
            Config.normalize_trading_mode(
                mode
            )
        )

        common_stocks = (
            get_common_stocks()
        )

        if not common_stocks:
            return []

        results = (
            self.market_data_service
            .scan_stocks(
                access_token,
                common_stocks,
                mode=normalized_mode,
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
            )
        )

        return results

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

        normalized_token = clean_text(
            access_token
        )

        if not normalized_token:
            raise ScannerOrchestratorError(
                "FYERS access token is required."
            )

        normalized_mode = (
            Config.normalize_trading_mode(
                mode
            )
        )

        with self._scan_lock:

            try:
                candidate_data = (
                    self.build_candidate_universe(
                        normalized_token,
                        mode=normalized_mode,
                        benchmark_change_pct=(
                            benchmark_change_pct
                        ),
                        force_refresh=(
                            force_refresh
                        ),
                    )
                )

                common_stocks = (
                    self.build_common_universe()
                )

                strong_buy_results = (
                    self.scan_common_stocks(
                        normalized_token,
                        mode=normalized_mode,
                        benchmark_change_pct=(
                            benchmark_change_pct
                        ),
                    )
                )

                logger.info(
                    (
                        "Eagle scan complete | "
                        "mode=%s | sectors=%s | "
                        "candidates=%s | common=%s | "
                        "strong_buy=%s"
                    ),
                    normalized_mode,
                    len(
                        candidate_data[
                            "top_sectors"
                        ]
                    ),
                    candidate_data[
                        "candidate_count"
                    ],
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
                    ),
                )

                return {
                    "status": "success",

                    "mode": (
                        normalized_mode
                    ),

                    "top_sectors": (
                        candidate_data[
                            "top_sectors"
                        ]
                    ),

                    "candidate_count": (
                        candidate_data[
                            "candidate_count"
                        ]
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
                        utc_now()
                        .isoformat()
                    ),
                }

            except Exception as exception:

                log_exception(
                    logger,
                    "Eagle scanner orchestration failed",
                    exception=exception,
                    component=(
                        "scanner_orchestrator"
                    ),
                    error_code=(
                        "SCANNER_ORCHESTRATION_FAILED"
                    ),
                )

                raise ScannerOrchestratorError(
                    "Eagle Smart Scanner failed."
                ) from exception

    # =========================================================
    # NEW TRADING DAY
    # =========================================================

    def start_new_trading_day(
        self,
    ) -> bool:
        """
        Call once before saving the first candidate universe
        of a new trading day.

        Current day becomes Previous day.
        """

        return (
            archive_current_as_previous()
        )

    # =========================================================
    # STATUS
    # =========================================================

    def status(
        self,
    ) -> dict[str, Any]:

        universe_health = (
            self.universe_service
            .health()
        )

        common_stocks = (
            get_common_stocks()
        )

        return {
            "service": (
                "Eagle Scanner Orchestrator"
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

            "updated_at": (
                utc_now()
                .isoformat()
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
