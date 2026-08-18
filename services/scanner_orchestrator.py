from __future__ import annotations

import threading
from typing import Any, Iterable

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
    "services.scanner_orchestrator"
)


# ============================================================
# ERROR
# ============================================================


class ScannerOrchestratorError(
    RuntimeError
):
    """
    Raised when the complete Eagle Smart Scanner
    pipeline cannot be completed.
    """


# ============================================================
# ORCHESTRATOR
# ============================================================


class ScannerOrchestrator:
    """
    Eagle Smart Scanner master pipeline.

    ==========================================================
    FINAL FLOW
    ==========================================================

    Dynamic NSE Sector Universe
                ↓
    Verified FYERS Technical Metrics
                ↓
    Mode-aware Sector Ranking
                ↓
    Top 10 NSE Sectors
                ↓
    Mode-aware Stock Ranking
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
    Full Multi-Timeframe Technical Scanner
                ↓
    STRONG BUY only

    ==========================================================
    MODES
    ==========================================================

    INTRADAY
        5m + 15m + Daily

    BTST
        15m + 60m + Daily

    SWING
        Daily + Weekly

    ==========================================================
    IMPORTANT
    ==========================================================

    - No fixed NIFTY 500 universe.
    - No fundamental analysis.
    - No fake market data.
    - Ranking does NOT itself create STRONG BUY.
    - Final STRONG BUY comes only from technical scanner.
    """

    # ========================================================
    # INIT
    # ========================================================

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
            Config
            .normalize_trading_mode(
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
    # VALID TOKEN
    # ========================================================

    @staticmethod
    def _validate_token(
        access_token: str,
    ) -> str:

        normalized_token = clean_text(
            access_token
        )

        if not normalized_token:

            raise (
                ScannerOrchestratorError(
                    (
                        "FYERS access token "
                        "is required."
                    )
                )
            )

        return normalized_token


    # ========================================================
    # RANKED STOCK -> DICT
    # ========================================================

    @staticmethod
    def _ranked_stock_to_dict(
        stock: RankedStock,
    ) -> dict[str, Any]:

        if hasattr(
            stock,
            "to_dict",
        ):

            data = stock.to_dict()

        else:

            data = {}

        return {
            "symbol": (
                clean_text(
                    data.get(
                        "symbol"
                    )
                )
            ),

            "company_name": (
                clean_text(
                    data.get(
                        "company_name"
                    )
                )
            ),

            "sector": (
                clean_text(
                    data.get(
                        "sector"
                    )
                )
            ),

            "mode": (
                clean_text(
                    data.get(
                        "mode"
                    )
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

            "macd_score": (
                data.get(
                    "macd_score",
                    0.0,
                )
            ),

            "supertrend_score": (
                data.get(
                    "supertrend_score",
                    0.0,
                )
            ),

            "vwap_score": (
                data.get(
                    "vwap_score",
                    0.0,
                )
            ),

            "breakout_score": (
                data.get(
                    "breakout_score",
                    0.0,
                )
            ),

            "multi_timeframe_score": (
                data.get(
                    "multi_timeframe_score",
                    0.0,
                )
            ),

            "strong_buy": bool(
                data.get(
                    "strong_buy",
                    False,
                )
            ),

            "signal": (
                clean_text(
                    data.get(
                        "signal"
                    )
                )
                or "RANKED"
            ),
        }


    # ========================================================
    # SECTOR NAME
    # ========================================================

    @staticmethod
    def _sector_name(
        sector_result: Any,
    ) -> str:

        if hasattr(
            sector_result,
            "sector",
        ):

            return clean_text(
                getattr(
                    sector_result,
                    "sector",
                    "",
                )
            )

        if isinstance(
            sector_result,
            dict,
        ):

            return clean_text(
                sector_result.get(
                    "sector"
                )
            )

        return ""


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
        mode: str,
    ) -> dict[
        str,
        list[
            dict[str, Any]
        ],
    ]:

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        output: dict[
            str,
            list[
                dict[str, Any]
            ],
        ] = {}

        for sector in (
            top_sector_names
        ):

            clean_sector = (
                clean_text(
                    sector
                )
            )

            if not clean_sector:
                continue

            ranked_stocks = (
                get_top_stocks_for_sector(
                    sector=(
                        clean_sector
                    ),
                    stocks=(
                        stocks
                    ),
                    metrics_by_symbol=(
                        metrics_by_symbol
                    ),
                    limit=(
                        Config
                        .TOP_STOCKS_PER_SECTOR
                    ),
                    mode=(
                        normalized_mode
                    ),
                )
            )

            output[
                clean_sector
            ] = [
                self
                ._ranked_stock_to_dict(
                    stock
                )
                for stock
                in ranked_stocks
            ]

        return output


    # ========================================================
    # ATTACH STOCKS TO SECTOR CARDS
    # ========================================================

    @staticmethod
    def _attach_top_stocks_to_sectors(
        sector_results: Iterable[Any],
        top_stocks_by_sector: dict[
            str,
            list[
                dict[str, Any]
            ],
        ],
    ) -> list[
        dict[str, Any]
    ]:

        output: list[
            dict[str, Any]
        ] = []

        for (
            rank,
            sector_result,
        ) in enumerate(
            sector_results,
            start=1,
        ):

            if hasattr(
                sector_result,
                "to_dict",
            ):

                sector_data = (
                    sector_result
                    .to_dict()
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

            sector_name = (
                clean_text(
                    sector_data.get(
                        "sector"
                    )
                )
            )

            if not sector_name:
                continue

            sector_stocks = (
                top_stocks_by_sector
                .get(
                    sector_name,
                    [],
                )
            )

            sector_data[
                "rank"
            ] = rank

            sector_data[
                "top_stocks"
            ] = (
                sector_stocks
            )

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
    # CANDIDATE DICTS
    # ========================================================

    def _candidate_dicts(
        self,
        ranked_stocks: Iterable[
            RankedStock
        ],
    ) -> list[
        dict[str, Any]
    ]:

        output: list[
            dict[str, Any]
        ] = []

        seen_symbols: set[
            str
        ] = set()

        for stock in (
            ranked_stocks
        ):

            data = (
                self
                ._ranked_stock_to_dict(
                    stock
                )
            )

            symbol = (
                normalize_symbol(
                    data.get(
                        "symbol"
                    )
                )
            )

            if not symbol:
                continue

            if (
                symbol
                in seen_symbols
            ):

                continue

            seen_symbols.add(
                symbol
            )

            data[
                "symbol"
            ] = symbol

            output.append(
                data
            )

            if (
                len(
                    output
                )
                >= Config
                .MAX_SCANNER_UNIVERSE
            ):

                break

        return output


    # ========================================================
    # BUILD CANDIDATE UNIVERSE
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

            Top 10 NSE sectors
                    ×
            Top 10 technically ranked stocks

        Maximum:
            100 candidate stocks.

        No fundamentals.
        """

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        normalized_token = (
            self._validate_token(
                access_token
            )
        )

        # ====================================================
        # STEP 0
        # DAILY ROLLOVER
        # ====================================================

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
                    "failed | mode=%s | "
                    "error=%s"
                ),
                normalized_mode,
                exception,
            )


        # ====================================================
        # STEP 1
        # DYNAMIC NSE SECTOR UNIVERSE
        # ====================================================

        stocks = (
            self
            .universe_service
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

            raise (
                ScannerOrchestratorError(
                    (
                        "Dynamic NSE sector "
                        "universe is empty."
                    )
                )
            )

        logger.info(
            (
                "NSE sector universe loaded | "
                "mode=%s | stocks=%s"
            ),
            normalized_mode,
            len(
                stocks
            ),
        )


        # ====================================================
        # STEP 2
        # TECHNICAL METRICS
        # ====================================================

        metrics_by_symbol = (
            self
            .metrics_service
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

        if not isinstance(
            metrics_by_symbol,
            dict,
        ):

            raise (
                ScannerOrchestratorError(
                    (
                        "Technical metrics "
                        "response is invalid."
                    )
                )
            )

        if not metrics_by_symbol:

            raise (
                ScannerOrchestratorError(
                    (
                        "No verified technical "
                        "metrics were produced."
                    )
                )
            )

        logger.info(
            (
                "Verified technical metrics ready | "
                "mode=%s | metrics=%s"
            ),
            normalized_mode,
            len(
                metrics_by_symbol
            ),
        )


        # ====================================================
        # STEP 3
        # TOP 10 SECTORS
        # ====================================================

        top_sector_results = (
            self
            .sector_scanner
            .get_top_sectors(
                stocks=(
                    stocks
                ),
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
                limit=(
                    Config
                    .TOP_SECTORS_COUNT
                ),
                mode=(
                    normalized_mode
                ),
            )
        )

        if not top_sector_results:

            raise (
                ScannerOrchestratorError(
                    (
                        "No technically ranked "
                        "NSE sectors were found."
                    )
                )
            )


        # ====================================================
        # SECTOR NAMES
        # ====================================================

        top_sector_names: list[
            str
        ] = []

        seen_sector_names: set[
            str
        ] = set()

        for result in (
            top_sector_results
        ):

            sector_name = (
                self
                ._sector_name(
                    result
                )
            )

            if not sector_name:
                continue

            key = (
                sector_name
                .casefold()
            )

            if key in (
                seen_sector_names
            ):

                continue

            seen_sector_names.add(
                key
            )

            top_sector_names.append(
                sector_name
            )

            if (
                len(
                    top_sector_names
                )
                >= Config
                .TOP_SECTORS_COUNT
            ):

                break

        if not top_sector_names:

            raise (
                ScannerOrchestratorError(
                    (
                        "Top-sector ranking "
                        "returned no valid "
                        "sector names."
                    )
                )
            )


        # ====================================================
        # STEP 4
        # TOP 10 STOCKS / SECTOR
        # ====================================================

        top_stocks_by_sector = (
            self
            ._build_top_stocks_by_sector(
                top_sector_names=(
                    top_sector_names
                ),
                stocks=(
                    stocks
                ),
                metrics_by_symbol=(
                    metrics_by_symbol
                ),
                mode=(
                    normalized_mode
                ),
            )
        )


        # ====================================================
        # STEP 5
        # FLAT MAX-100 UNIVERSE
        # ====================================================

        ranked_candidate_stocks = (
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
                mode=(
                    normalized_mode
                ),
            )
        )

        if not ranked_candidate_stocks:

            raise (
                ScannerOrchestratorError(
                    (
                        "No technically ranked "
                        "stocks were produced "
                        "from Top NSE sectors."
                    )
                )
            )

        ranked_candidate_stocks = (
            ranked_candidate_stocks[
                :Config
                .MAX_SCANNER_UNIVERSE
            ]
        )


        # ====================================================
        # CANDIDATE DICTS
        # ====================================================

        candidate_dicts = (
            self
            ._candidate_dicts(
                ranked_candidate_stocks
            )
        )

        if not candidate_dicts:

            raise (
                ScannerOrchestratorError(
                    (
                        "Candidate universe "
                        "contains no valid "
                        "stock symbols."
                    )
                )
            )


        # ====================================================
        # STEP 6
        # DASHBOARD SECTOR DATA
        # ====================================================

        enriched_top_sectors = (
            self
            ._attach_top_stocks_to_sectors(
                top_sector_results,
                top_stocks_by_sector,
            )
        )


        # ====================================================
        # STEP 7
        # SAVE CURRENT-DAY CANDIDATES
        # ====================================================

        saved_candidates = (
            save_current_day_candidates(
                candidate_dicts,
                mode=(
                    normalized_mode
                ),
            )
        )

        # Some implementations may return None.
        if not isinstance(
            saved_candidates,
            list,
        ):

            saved_candidates = (
                candidate_dicts
            )


        # ====================================================
        # FINAL LOG
        # ====================================================

        logger.info(
            (
                "Candidate universe completed | "
                "mode=%s | sectors=%s | "
                "metrics=%s | candidates=%s"
            ),
            normalized_mode,
            len(
                enriched_top_sectors
            ),
            len(
                metrics_by_symbol
            ),
            len(
                saved_candidates
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
                        saved_candidates
                    )
                ),
            ),
        )


        # ====================================================
        # RETURN
        # ====================================================

        return {
            "success": True,

            "status": (
                "candidates_ready"
            ),

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

            "metrics_count": (
                len(
                    metrics_by_symbol
                )
            ),

            "candidate_count": (
                len(
                    saved_candidates
                )
            ),

            "maximum_candidate_count": (
                Config
                .MAX_SCANNER_UNIVERSE
            ),

            "candidates": (
                saved_candidates
            ),

            "technical_only": True,

            "fixed_nifty500": False,

            "verified": True,

            "updated_at": (
                utc_now()
                .isoformat()
            ),
        }


    # ========================================================
    # BUILD COMMON UNIVERSE
    # ========================================================

    def build_common_universe(
        self,
        *,
        mode: str,
    ) -> list[
        dict[str, Any]
    ]:
        """
        Previous Day candidates
                ∩
        Current Day candidates

        Only common stocks continue
        to final STRONG BUY scan.
        """

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        try:

            common_stocks = (
                build_and_save_common_stocks(
                    mode=(
                        normalized_mode
                    )
                )
            )

        except Exception as exception:

            log_exception(
                logger,
                (
                    "Common-stock universe "
                    "generation failed"
                ),
                exception=(
                    exception
                ),
                component=(
                    "scanner_orchestrator"
                ),
                error_code=(
                    "COMMON_UNIVERSE_FAILED"
                ),
                mode=(
                    normalized_mode
                ),
            )

            raise (
                ScannerOrchestratorError(
                    (
                        "Unable to build "
                        "previous/current "
                        "common-stock universe."
                    )
                )
            ) from exception


        if not isinstance(
            common_stocks,
            list,
        ):

            return []


        output: list[
            dict[str, Any]
        ] = []

        seen_symbols: set[
            str
        ] = set()

        for stock in (
            common_stocks
        ):

            if not isinstance(
                stock,
                dict,
            ):
                continue

            symbol = (
                normalize_symbol(
                    stock.get(
                        "symbol"
                    )
                )
            )

            if not symbol:
                continue

            if symbol in (
                seen_symbols
            ):

                continue

            seen_symbols.add(
                symbol
            )

            row = dict(
                stock
            )

            row[
                "symbol"
            ] = symbol

            output.append(
                row
            )

        return output


    # ========================================================
    # FINAL STRONG BUY SCAN
    # ========================================================

    def scan_common_stocks(
        self,
        access_token: str,
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
    ) -> list[
        dict[str, Any]
    ]:
        """
        Run final full technical scanner.

        Input:
            Previous/current common stocks.

        Output:
            STRONG BUY only.

        Ranking does not create the signal.
        """

        normalized_token = (
            self._validate_token(
                access_token
            )
        )

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

        if not isinstance(
            common_stocks,
            list,
        ):

            common_stocks = []

        if not common_stocks:

            logger.info(
                (
                    "No common stocks "
                    "available | mode=%s"
                ),
                normalized_mode,
            )

            return []


        # ====================================================
        # FULL TECHNICAL SCAN
        # ====================================================

        results = (
            self
            .market_data_service
            .scan_stocks(
                normalized_token,
                common_stocks,
                mode=(
                    normalized_mode
                ),
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
            )
        )

        if not isinstance(
            results,
            list,
        ):

            return []


        # ====================================================
        # HARD STRONG BUY FILTER
        # ====================================================

        strong_buy_results: list[
            dict[str, Any]
        ] = []

        seen_symbols: set[
            str
        ] = set()

        for item in results:

            if not isinstance(
                item,
                dict,
            ):
                continue

            symbol = (
                normalize_symbol(
                    item.get(
                        "symbol"
                    )
                )
            )

            if not symbol:
                continue

            if symbol in (
                seen_symbols
            ):

                continue

            signal = (
                clean_text(
                    item.get(
                        "signal"
                    )
                )
                .upper()
            )

            if (
                signal
                != "STRONG BUY"
            ):

                continue

            # Final scanner should have
            # multi-timeframe confirmation.
            if not bool(
                item.get(
                    "multi_timeframe_confirmed",
                    False,
                )
            ):

                continue

            current_price = (
                safe_float(
                    item.get(
                        "current_price"
                    )
                )
            )

            if (
                current_price is None
                or current_price <= 0
            ):

                continue

            row = dict(
                item
            )

            row[
                "symbol"
            ] = symbol

            row[
                "mode"
            ] = normalized_mode

            row[
                "verified"
            ] = True

            row[
                "technical_only"
            ] = True

            seen_symbols.add(
                symbol
            )

            strong_buy_results.append(
                row
            )


        # ====================================================
        # SORT STRONG BUY
        # ====================================================

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

                -self._number(
                    item.get(
                        "move_up_probability"
                    )
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


    # ========================================================
    # COMPLETE SCAN
    # ========================================================

    def run_scan(
        self,
        access_token: str,
        *,
        mode: str | None = None,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """
        Run complete Eagle Smart Scanner.

        STEP 1
            Dynamic sector universe.

        STEP 2
            Verified technical metrics.

        STEP 3
            Mode-aware Top 10 sectors.

        STEP 4
            Top 10 stocks / sector.

        STEP 5
            Maximum 100 candidates.

        STEP 6
            Previous/current common stocks.

        STEP 7
            Full multi-timeframe technical scan.

        STEP 8
            STRONG BUY only.
        """

        normalized_token = (
            self._validate_token(
                access_token
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
                # STEP 1-5
                # BUILD CANDIDATES
                # ============================================

                candidate_data = (
                    self
                    .build_candidate_universe(
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
                # STEP 6
                # COMMON STOCKS
                # ============================================

                common_stocks = (
                    self
                    .build_common_universe(
                        mode=(
                            normalized_mode
                        )
                    )
                )


                # ============================================
                # STEP 7-8
                # FINAL STRONG BUY
                # ============================================

                strong_buy_results = (
                    self
                    .scan_common_stocks(
                        normalized_token,
                        mode=(
                            normalized_mode
                        ),
                        benchmark_change_pct=(
                            benchmark_change_pct
                        ),
                    )
                )


                # ============================================
                # FINAL PAYLOAD
                # ============================================

                payload: dict[
                    str,
                    Any,
                ] = {
                    "success": True,

                    "status": (
                        "success"
                    ),

                    "mode": (
                        normalized_mode
                    ),

                    # ----------------------------------------
                    # SECTORS
                    # ----------------------------------------

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

                    # ----------------------------------------
                    # METRICS
                    # ----------------------------------------

                    "metrics_count": (
                        candidate_data.get(
                            "metrics_count",
                            0,
                        )
                    ),

                    # ----------------------------------------
                    # CANDIDATES
                    # ----------------------------------------

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

                    "candidates": (
                        candidate_data.get(
                            "candidates",
                            [],
                        )
                    ),

                    # ----------------------------------------
                    # COMMON STOCKS
                    # ----------------------------------------

                    "common_count": (
                        len(
                            common_stocks
                        )
                    ),

                    "common_stocks": (
                        common_stocks
                    ),

                    # ----------------------------------------
                    # FINAL SIGNALS
                    # ----------------------------------------

                    "strong_buy_count": (
                        len(
                            strong_buy_results
                        )
                    ),

                    "results": (
                        strong_buy_results
                    ),

                    # Compatibility aliases
                    "strong_buy_results": (
                        strong_buy_results
                    ),

                    "signals": (
                        strong_buy_results
                    ),

                    # ----------------------------------------
                    # SYSTEM FLAGS
                    # ----------------------------------------

                    "verified": True,

                    "technical_only": True,

                    "fundamental_analysis": False,

                    "fixed_nifty500": False,

                    "universe_type": (
                        "dynamic_nse_sector_universe"
                    ),

                    "top_sector_limit": (
                        Config
                        .TOP_SECTORS_COUNT
                    ),

                    "top_stocks_per_sector": (
                        Config
                        .TOP_STOCKS_PER_SECTOR
                    ),

                    "updated_at": (
                        utc_now()
                        .isoformat()
                    ),
                }


                # ============================================
                # LOG
                # ============================================

                logger.info(
                    (
                        "Eagle scan completed | "
                        "mode=%s | "
                        "sectors=%s | "
                        "metrics=%s | "
                        "candidates=%s | "
                        "common=%s | "
                        "strong_buy=%s"
                    ),
                    normalized_mode,
                    payload[
                        "sector_count"
                    ],
                    payload[
                        "metrics_count"
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


            except (
                ScannerOrchestratorError
            ):

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

                raise (
                    ScannerOrchestratorError(
                        (
                            "Eagle Smart Scanner "
                            "failed for "
                            f"{normalized_mode}: "
                            f"{exception}"
                        )
                    )
                ) from exception


    # ========================================================
    # SAVED COMMON STOCKS
    # ========================================================

    def get_saved_common_stocks(
        self,
        *,
        mode: str,
    ) -> list[
        dict[str, Any]
    ]:

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

        if not isinstance(
            common_stocks,
            list,
        ):

            return []

        return [
            dict(
                item
            )
            for item
            in common_stocks
            if isinstance(
                item,
                dict,
            )
        ]


    # ========================================================
    # TOP SECTOR PREVIEW
    # ========================================================

    def get_top_sector_preview(
        self,
        access_token: str,
        *,
        mode: str,
        benchmark_change_pct: float = 0.0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """
        Build only sector/stock ranking data.

        Does not require final STRONG BUY signal.

        Useful for dashboard sector cards.
        """

        return (
            self
            .build_candidate_universe(
                access_token,
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

        # ====================================================
        # UNIVERSE HEALTH
        # ====================================================

        try:

            universe_health = (
                self
                .universe_service
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


        # ====================================================
        # COMMON STOCKS
        # ====================================================

        try:

            common_stocks = (
                get_common_stocks(
                    mode=(
                        normalized_mode
                    )
                )
            )

            if not isinstance(
                common_stocks,
                list,
            ):

                common_stocks = []

        except Exception:

            common_stocks = []


        # ====================================================
        # MODES
        # ====================================================

        supported_modes = list(
            getattr(
                Config,
                "SUPPORTED_TRADING_MODES",
                (
                    Config.MODE_INTRADAY,
                    Config.MODE_SWING,
                ),
            )
        )


        # ====================================================
        # RETURN
        # ====================================================

        return {
            "service": (
                "Eagle Scanner Orchestrator"
            ),

            "status": (
                "ready"
            ),

            "mode": (
                normalized_mode
            ),

            "supported_modes": (
                supported_modes
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
                Config
                .TOP_SECTORS_COUNT
            ),

            "top_stocks_per_sector": (
                Config
                .TOP_STOCKS_PER_SECTOR
            ),

            "maximum_candidates": (
                Config
                .MAX_SCANNER_UNIVERSE
            ),

            "technical_only": True,

            "fundamental_analysis": False,

            "fixed_nifty500": False,

            "universe_type": (
                "dynamic_nse_sector_universe"
            ),

            "updated_at": (
                utc_now()
                .isoformat()
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


# ============================================================
# GET ORCHESTRATOR
# ============================================================


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
