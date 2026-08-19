from __future__ import annotations

import threading
from typing import Any, Iterable

from config import Config

from services.common_stock_engine import (
    build_and_save_common_stocks,
    get_common_stocks,
    get_previous_day_candidates,
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
    Raised when Eagle Smart Scanner pipeline
    cannot be completed safely.
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
    Maximum 100 Unique Candidates
                ↓
    Save Current-Day Candidates
                ↓
    Previous Day ∩ Current Day
                ↓
    Common Stocks
                ↓
    Full Technical Scan
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

    - No fixed NIFTY 500.
    - No fundamental filter.
    - No fake market data.
    - Candidate ranking itself does not create STRONG BUY.
    - Final signal comes from technical_scanner.py.
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
    # TOKEN
    # ========================================================

    @staticmethod
    def _validate_token(
        access_token: str,
    ) -> str:

        token = clean_text(
            access_token
        )

        if not token:

            raise (
                ScannerOrchestratorError(
                    (
                        "FYERS access token "
                        "is required."
                    )
                )
            )

        return token


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
    # RANKED STOCK -> DICT
    # ========================================================

    @staticmethod
    def _ranked_stock_to_dict(
        stock: Any,
        *,
        mode: str,
    ) -> dict[str, Any]:

        if hasattr(
            stock,
            "to_dict",
        ):

            raw = stock.to_dict()

        elif isinstance(
            stock,
            dict,
        ):

            raw = dict(
                stock
            )

        else:

            raw = {}

        symbol = normalize_symbol(
            raw.get(
                "symbol"
            )
        )

        return {
            "symbol": (
                symbol
            ),

            "company_name": (
                clean_text(
                    raw.get(
                        "company_name"
                    )
                )
                or symbol
            ),

            "sector": (
                clean_text(
                    raw.get(
                        "sector"
                    )
                )
            ),

            "mode": (
                mode
            ),

            "score": (
                safe_float(
                    raw.get(
                        "score"
                    ),
                    default=0.0,
                )
                or 0.0
            ),

            "momentum_score": (
                safe_float(
                    raw.get(
                        "momentum_score"
                    ),
                    default=0.0,
                )
                or 0.0
            ),

            "trend_score": (
                safe_float(
                    raw.get(
                        "trend_score"
                    ),
                    default=0.0,
                )
                or 0.0
            ),

            "volume_score": (
                safe_float(
                    raw.get(
                        "volume_score"
                    ),
                    default=0.0,
                )
                or 0.0
            ),

            "rsi_score": (
                safe_float(
                    raw.get(
                        "rsi_score"
                    ),
                    default=0.0,
                )
                or 0.0
            ),

            "relative_strength_score": (
                safe_float(
                    raw.get(
                        "relative_strength_score"
                    ),
                    default=0.0,
                )
                or 0.0
            ),

            "macd_score": (
                safe_float(
                    raw.get(
                        "macd_score"
                    ),
                    default=0.0,
                )
                or 0.0
            ),

            "supertrend_score": (
                safe_float(
                    raw.get(
                        "supertrend_score"
                    ),
                    default=0.0,
                )
                or 0.0
            ),

            "vwap_score": (
                safe_float(
                    raw.get(
                        "vwap_score"
                    ),
                    default=0.0,
                )
                or 0.0
            ),

            "breakout_score": (
                safe_float(
                    raw.get(
                        "breakout_score"
                    ),
                    default=0.0,
                )
                or 0.0
            ),

            "multi_timeframe_score": (
                safe_float(
                    raw.get(
                        "multi_timeframe_score"
                    ),
                    default=0.0,
                )
                or 0.0
            ),

            "strong_buy": bool(
                raw.get(
                    "strong_buy",
                    False,
                )
            ),

            "signal": (
                clean_text(
                    raw.get(
                        "signal"
                    )
                )
                or "RANKED"
            ),
        }


    # ========================================================
    # TOP STOCK RANKER COMPATIBILITY
    # ========================================================

    def _get_top_stocks_for_sector(
        self,
        *,
        sector: str,
        stocks: list[Any],
        metrics_by_symbol: dict[
            str,
            dict[str, Any],
        ],
        mode: str,
    ) -> list[Any]:
        """
        Supports both newer and older stock_ranker.py
        function signatures.

        New:
            mode=...

        Older:
            no mode argument
        """

        try:

            return list(
                get_top_stocks_for_sector(
                    sector=(
                        sector
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
                        mode
                    ),
                )
            )

        except TypeError as exception:

            if (
                "mode"
                not in str(
                    exception
                )
            ):

                raise

            logger.warning(
                (
                    "stock_ranker does not "
                    "accept mode parameter; "
                    "using compatibility call."
                )
            )

            return list(
                get_top_stocks_for_sector(
                    sector=(
                        sector
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
                )
            )


    # ========================================================
    # FLAT CANDIDATE RANKER COMPATIBILITY
    # ========================================================

    def _build_flat_candidate_universe(
        self,
        *,
        top_sector_names: list[str],
        stocks: list[Any],
        metrics_by_symbol: dict[
            str,
            dict[str, Any],
        ],
        mode: str,
    ) -> list[Any]:

        try:

            output = (
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
                        mode
                    ),
                )
            )

        except TypeError as exception:

            if (
                "mode"
                not in str(
                    exception
                )
            ):

                raise

            logger.warning(
                (
                    "build_top_sector_stock_universe "
                    "does not accept mode; "
                    "using compatibility call."
                )
            )

            output = (
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

        return list(
            output
            or []
        )


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

        output: dict[
            str,
            list[
                dict[str, Any]
            ],
        ] = {}

        for sector in (
            top_sector_names
        ):

            sector_name = (
                clean_text(
                    sector
                )
            )

            if not sector_name:

                continue

            try:

                ranked_stocks = (
                    self
                    ._get_top_stocks_for_sector(
                        sector=(
                            sector_name
                        ),
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

            except Exception as exception:

                logger.warning(
                    (
                        "Top stocks failed "
                        "for sector=%s | "
                        "mode=%s | error=%s"
                    ),
                    sector_name,
                    mode,
                    exception,
                )

                output[
                    sector_name
                ] = []

                continue

            rows: list[
                dict[str, Any]
            ] = []

            seen: set[
                str
            ] = set()

            for (
                position,
                ranked_stock,
            ) in enumerate(
                ranked_stocks,
                start=1,
            ):

                data = (
                    self
                    ._ranked_stock_to_dict(
                        ranked_stock,
                        mode=(
                            mode
                        ),
                    )
                )

                symbol = normalize_symbol(
                    data.get(
                        "symbol"
                    )
                )

                if not symbol:

                    continue

                if symbol in seen:

                    continue

                seen.add(
                    symbol
                )

                metrics = (
                    metrics_by_symbol
                    .get(
                        symbol,
                        {},
                    )
                )

                if not isinstance(
                    metrics,
                    dict,
                ):

                    metrics = {}

                data[
                    "rank"
                ] = position

                data[
                    "symbol"
                ] = symbol

                data[
                    "current_price"
                ] = round(
                    self._number(
                        metrics.get(
                            "current_price"
                        )
                    ),
                    2,
                )

                data[
                    "rsi"
                ] = round(
                    self._number(
                        metrics.get(
                            "rsi"
                        )
                    ),
                    2,
                )

                data[
                    "volume_ratio"
                ] = round(
                    self._number(
                        metrics.get(
                            "volume_ratio"
                        )
                    ),
                    2,
                )

                data[
                    "change_1d_pct"
                ] = round(
                    self._number(
                        metrics.get(
                            "change_1d_pct"
                        )
                    ),
                    2,
                )

                data[
                    "change_5d_pct"
                ] = round(
                    self._number(
                        metrics.get(
                            "change_5d_pct"
                        )
                    ),
                    2,
                )

                data[
                    "change_20d_pct"
                ] = round(
                    self._number(
                        metrics.get(
                            "change_20d_pct"
                        )
                    ),
                    2,
                )

                data[
                    "relative_strength_pct"
                ] = round(
                    self._number(
                        metrics.get(
                            "relative_strength_pct"
                        )
                    ),
                    2,
                )

                data[
                    "verified"
                ] = bool(
                    metrics.get(
                        "verified",
                        False,
                    )
                )

                rows.append(
                    data
                )

                if (
                    len(
                        rows
                    )
                    >= Config
                    .TOP_STOCKS_PER_SECTOR
                ):

                    break

            output[
                sector_name
            ] = rows

        return output


    # ========================================================
    # ATTACH STOCKS TO SECTOR
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
            result,
        ) in enumerate(
            sector_results,
            start=1,
        ):

            if hasattr(
                result,
                "to_dict",
            ):

                sector_data = (
                    result.to_dict()
                )

            elif isinstance(
                result,
                dict,
            ):

                sector_data = dict(
                    result
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
        ranked_stocks: Iterable[Any],
        *,
        mode: str,
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
                    stock,
                    mode=(
                        mode
                    ),
                )
            )

            symbol = normalize_symbol(
                data.get(
                    "symbol"
                )
            )

            if not symbol:

                continue

            if symbol in seen_symbols:

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

        # ====================================================
        # STEP 0
        # DAY ROLLOVER
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
                    "Candidate rollover "
                    "warning | mode=%s | %s"
                ),
                normalized_mode,
                exception,
            )


        # ====================================================
        # STEP 1
        # NSE SECTOR UNIVERSE
        # ====================================================

        stocks = list(
            self
            .universe_service
            .get_all_stocks(
                force_refresh=(
                    force_refresh
                )
            )
            or []
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
                "Sector universe ready | "
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
                "Metrics ready | "
                "mode=%s | valid=%s"
            ),
            normalized_mode,
            len(
                metrics_by_symbol
            ),
        )


        # ====================================================
        # STEP 3
        # TOP SECTORS
        # ====================================================

        try:

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

        except TypeError as exception:

            if (
                "mode"
                not in str(
                    exception
                )
            ):

                raise

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
                )
            )

        top_sector_results = list(
            top_sector_results
            or []
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

        for sector_result in (
            top_sector_results
        ):

            sector_name = (
                self
                ._sector_name(
                    sector_result
                )
            )

            if not sector_name:

                continue

            sector_key = (
                sector_name
                .casefold()
            )

            if sector_key in (
                seen_sector_names
            ):

                continue

            seen_sector_names.add(
                sector_key
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
                        "Sector ranking returned "
                        "no valid sector names."
                    )
                )
            )


        # ====================================================
        # STEP 4
        # TOP STOCKS BY SECTOR
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
        # MAX 100 UNIQUE CANDIDATES
        # ====================================================

        ranked_candidates = (
            self
            ._build_flat_candidate_universe(
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

        if not ranked_candidates:

            # Fallback:
            # Build candidate universe directly
            # from already ranked sector lists.

            ranked_candidates = []

            seen: set[
                str
            ] = set()

            for sector_name in (
                top_sector_names
            ):

                for item in (
                    top_stocks_by_sector
                    .get(
                        sector_name,
                        [],
                    )
                ):

                    symbol = (
                        normalize_symbol(
                            item.get(
                                "symbol"
                            )
                        )
                    )

                    if not symbol:

                        continue

                    if symbol in seen:

                        continue

                    seen.add(
                        symbol
                    )

                    ranked_candidates.append(
                        item
                    )

                    if (
                        len(
                            ranked_candidates
                        )
                        >= Config
                        .MAX_SCANNER_UNIVERSE
                    ):

                        break

                if (
                    len(
                        ranked_candidates
                    )
                    >= Config
                    .MAX_SCANNER_UNIVERSE
                ):

                    break


        candidate_dicts = (
            self
            ._candidate_dicts(
                ranked_candidates,
                mode=(
                    normalized_mode
                ),
            )
        )

        if not candidate_dicts:

            # ranked_candidates may already
            # be dictionaries from fallback.

            candidate_dicts = []

            seen: set[
                str
            ] = set()

            for sector_name in (
                top_sector_names
            ):

                for item in (
                    top_stocks_by_sector
                    .get(
                        sector_name,
                        [],
                    )
                ):

                    symbol = (
                        normalize_symbol(
                            item.get(
                                "symbol"
                            )
                        )
                    )

                    if not symbol:

                        continue

                    if symbol in seen:

                        continue

                    seen.add(
                        symbol
                    )

                    row = dict(
                        item
                    )

                    row[
                        "symbol"
                    ] = symbol

                    row[
                        "mode"
                    ] = normalized_mode

                    candidate_dicts.append(
                        row
                    )

                    if (
                        len(
                            candidate_dicts
                        )
                        >= Config
                        .MAX_SCANNER_UNIVERSE
                    ):

                        break

                if (
                    len(
                        candidate_dicts
                    )
                    >= Config
                    .MAX_SCANNER_UNIVERSE
                ):

                    break


        if not candidate_dicts:

            raise (
                ScannerOrchestratorError(
                    (
                        "No valid candidate "
                        "stocks were produced."
                    )
                )
            )


        # ====================================================
        # DASHBOARD SECTOR CARDS
        # ====================================================

        enriched_top_sectors = (
            self
            ._attach_top_stocks_to_sectors(
                top_sector_results,
                top_stocks_by_sector,
            )
        )


        # ====================================================
        # SAVE CURRENT DAY
        # ====================================================

        saved_candidates = (
            save_current_day_candidates(
                candidate_dicts,
                mode=(
                    normalized_mode
                ),
            )
        )

        if not isinstance(
            saved_candidates,
            list,
        ):

            saved_candidates = (
                candidate_dicts
            )


        logger.info(
            (
                "Candidate universe complete | "
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

            "fundamental_analysis": False,

            "fixed_nifty500": False,

            "verified": True,

            "updated_at": (
                utc_now()
                .isoformat()
            ),
        }


    # ========================================================
    # COMMON UNIVERSE
    # ========================================================

    def build_common_universe(
        self,
        *,
        mode: str,
        current_candidates: (
            list[
                dict[str, Any]
            ]
            | None
        ) = None,
    ) -> dict[str, Any]:
        """
        Previous Day ∩ Current Day.

        IMPORTANT FIX:

        On a new installation / first trading day,
        previous-day file does not exist.

        In that case scanner must NOT fail.

        For:
            Intraday
            BTST
            Swing

        current candidates are allowed as bootstrap
        scan universe until a real previous-day file exists.
        """

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        current_candidates = [
            dict(
                item
            )
            for item
            in (
                current_candidates
                or []
            )
            if isinstance(
                item,
                dict,
            )
        ]


        # ====================================================
        # CHECK PREVIOUS DAY
        # ====================================================

        try:

            previous_candidates = (
                get_previous_day_candidates(
                    mode=(
                        normalized_mode
                    )
                )
            )

        except Exception:

            previous_candidates = []


        # ====================================================
        # FIRST-DAY / NO PREVIOUS-DAY BOOTSTRAP
        # ====================================================

        if not previous_candidates:

            logger.warning(
                (
                    "Previous-day candidates "
                    "not available | mode=%s | "
                    "using current-day candidates "
                    "as bootstrap scan universe."
                ),
                normalized_mode,
            )

            return {
                "stocks": (
                    current_candidates
                ),

                "source": (
                    "current_day_bootstrap"
                ),

                "previous_day_available": False,
            }


        # ====================================================
        # NORMAL COMMON-STOCK ENGINE
        # ====================================================

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
                    "Common stock generation "
                    "failed"
                ),
                exception=exception,
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

            # Do not crash entire scanner.
            # Use current candidates instead.

            return {
                "stocks": (
                    current_candidates
                ),

                "source": (
                    "current_day_fallback"
                ),

                "previous_day_available": True,
            }


        if not isinstance(
            common_stocks,
            list,
        ):

            common_stocks = []


        # ====================================================
        # NORMALIZE
        # ====================================================

        output: list[
            dict[str, Any]
        ] = []

        seen: set[
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

            if symbol in seen:

                continue

            seen.add(
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


        # ====================================================
        # IMPORTANT:
        # Zero intersection should NOT make whole scanner fail.
        # ====================================================

        if not output:

            logger.info(
                (
                    "Previous/current common "
                    "stock intersection is empty | "
                    "mode=%s"
                ),
                normalized_mode,
            )


        return {
            "stocks": (
                output
            ),

            "source": (
                "previous_current_common"
            ),

            "previous_day_available": True,
        }


    # ========================================================
    # FINAL SCAN
    # ========================================================

    def scan_stock_universe(
        self,
        access_token: str,
        *,
        stocks: list[
            dict[str, Any]
        ],
        mode: str,
        benchmark_change_pct: float = 0.0,
    ) -> list[
        dict[str, Any]
    ]:

        token = (
            self._validate_token(
                access_token
            )
        )

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        if not stocks:

            return []


        results = (
            self
            .market_data_service
            .scan_stocks(
                token,
                stocks,
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

        output: list[
            dict[str, Any]
        ] = []

        seen: set[
            str
        ] = set()

        for item in results:

            if not isinstance(
                item,
                dict,
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

            if signal != "STRONG BUY":

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

            if symbol in seen:

                continue

            # Strong Buy must be
            # multi-timeframe confirmed.

            if not bool(
                item.get(
                    "multi_timeframe_confirmed",
                    False,
                )
            ):

                continue

            current_price = safe_float(
                item.get(
                    "current_price"
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

            seen.add(
                symbol
            )

            output.append(
                row
            )


        output.sort(
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

        return output


    # ========================================================
    # LEGACY METHOD
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

        normalized_mode = (
            self._normalize_mode(
                mode
            )
        )

        stocks = (
            get_common_stocks(
                mode=(
                    normalized_mode
                )
            )
        )

        if not isinstance(
            stocks,
            list,
        ):

            stocks = []

        return (
            self
            .scan_stock_universe(
                access_token,
                stocks=stocks,
                mode=(
                    normalized_mode
                ),
                benchmark_change_pct=(
                    benchmark_change_pct
                ),
            )
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

        token = (
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
                # STEP 1
                # BUILD TOP-SECTOR CANDIDATES
                # ============================================

                candidate_data = (
                    self
                    .build_candidate_universe(
                        token,
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

                current_candidates = (
                    candidate_data.get(
                        "candidates",
                        [],
                    )
                )

                if not isinstance(
                    current_candidates,
                    list,
                ):

                    current_candidates = []


                # ============================================
                # STEP 2
                # BUILD COMMON / BOOTSTRAP UNIVERSE
                # ============================================

                common_data = (
                    self
                    .build_common_universe(
                        mode=(
                            normalized_mode
                        ),
                        current_candidates=(
                            current_candidates
                        ),
                    )
                )

                scan_universe = (
                    common_data.get(
                        "stocks",
                        [],
                    )
                )

                if not isinstance(
                    scan_universe,
                    list,
                ):

                    scan_universe = []


                # ============================================
                # STEP 3
                # FINAL STRONG BUY
                # ============================================

                strong_buy_results = (
                    self
                    .scan_stock_universe(
                        token,
                        stocks=(
                            scan_universe
                        ),
                        mode=(
                            normalized_mode
                        ),
                        benchmark_change_pct=(
                            benchmark_change_pct
                        ),
                    )
                )


                # ============================================
                # PAYLOAD
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
                        len(
                            current_candidates
                        )
                    ),

                    "maximum_candidate_count": (
                        Config
                        .MAX_SCANNER_UNIVERSE
                    ),

                    "candidates": (
                        current_candidates
                    ),

                    # ----------------------------------------
                    # COMMON / BOOTSTRAP
                    # ----------------------------------------

                    "common_count": (
                        len(
                            scan_universe
                        )
                    ),

                    "common_stocks": (
                        scan_universe
                    ),

                    "scan_universe_source": (
                        common_data.get(
                            "source"
                        )
                    ),

                    "previous_day_available": (
                        bool(
                            common_data.get(
                                "previous_day_available"
                            )
                        )
                    ),

                    # ----------------------------------------
                    # FINAL RESULTS
                    # ----------------------------------------

                    "strong_buy_count": (
                        len(
                            strong_buy_results
                        )
                    ),

                    "results": (
                        strong_buy_results
                    ),

                    "strong_buy_results": (
                        strong_buy_results
                    ),

                    "signals": (
                        strong_buy_results
                    ),

                    # ----------------------------------------
                    # FLAGS
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

                    "supported_modes": list(
                        Config
                        .SUPPORTED_TRADING_MODES
                    ),

                    "updated_at": (
                        utc_now()
                        .isoformat()
                    ),
                }


                logger.info(
                    (
                        "Eagle scan completed | "
                        "mode=%s | "
                        "sectors=%s | "
                        "metrics=%s | "
                        "candidates=%s | "
                        "scan_universe=%s | "
                        "source=%s | "
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
                        "scan_universe_source"
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
    # SAVED COMMON
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

        try:

            stocks = (
                get_common_stocks(
                    mode=(
                        normalized_mode
                    )
                )
            )

        except Exception:

            return []

        if not isinstance(
            stocks,
            list,
        ):

            return []

        return [
            dict(
                item
            )
            for item
            in stocks
            if isinstance(
                item,
                dict,
            )
        ]


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

                "error": (
                    str(
                        exception
                    )
                ),
            }


        try:

            common_stocks = (
                get_common_stocks(
                    mode=(
                        normalized_mode
                    )
                )
            )

        except Exception:

            common_stocks = []


        if not isinstance(
            common_stocks,
            list,
        ):

            common_stocks = []


        return {
            "service": (
                "Eagle Scanner Orchestrator"
            ),

            "status": "ready",

            "mode": (
                normalized_mode
            ),

            "supported_modes": list(
                Config
                .SUPPORTED_TRADING_MODES
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
