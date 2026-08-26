from __future__ import annotations

"""
Eagle Smart Scanner - Scanner Orchestrator

Master technical scanning pipeline:

1. Scan/rank NSE sectors
2. Keep configured Top sectors
3. Rank configured Top stocks inside each selected sector
4. Run Pattern + Deep Technical fusion
5. Produce BUY / STRONG BUY final rows
6. Persist mode-specific results
7. Cache last completed scan in memory

No fundamentals.
No NIFTY500 scanning.
No random/fake market data.
"""

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from zoneinfo import ZoneInfo

from config import Config
from services.common_stock_engine import (
    CommonStockEngine,
    FinalStockSignal,
    get_common_stock_engine,
)
from services.sector_scanner import (
    SectorScanResult,
    SectorScanner,
    get_sector_scanner,
)
from services.stock_ranker import (
    RankedStock,
    StockRanker,
    get_stock_ranker,
)


class ScannerOrchestratorError(RuntimeError):
    """Master scanner pipeline error."""


@dataclass(frozen=True)
class ScannerRun:
    mode: str
    started_at: str
    completed_at: str
    sectors_scanned: int
    sectors_selected: int
    stocks_ranked: int
    stocks_deep_scanned: int
    buy_count: int
    strong_buy_count: int
    results: tuple[FinalStockSignal, ...]
    errors: tuple[str, ...]


class ScannerOrchestrator:
    """
    One master controller for the Eagle Smart Scanner.
    """

    def __init__(
        self,
        sector_scanner: SectorScanner | None = None,
        stock_ranker: StockRanker | None = None,
        common_engine: CommonStockEngine | None = None,
    ) -> None:
        self.sector_scanner = (
            sector_scanner
            or get_sector_scanner()
        )

        self.stock_ranker = (
            stock_ranker
            or get_stock_ranker()
        )

        self.common_engine = (
            common_engine
            or get_common_stock_engine()
        )

        self._scan_lock = threading.Lock()
        self._state_lock = threading.RLock()

        self._running_modes: set[str] = set()

        self._last_runs: dict[
            str,
            ScannerRun,
        ] = {}

        os.makedirs(
            Config.DATA_DIR,
            exist_ok=True,
        )

    # ========================================================
    # RUN ONE MODE
    # ========================================================

    def run(
        self,
        mode: str | None = None,
    ) -> ScannerRun:
        mode = Config.normalize_trading_mode(
            mode
        )

        with self._state_lock:
            if mode in self._running_modes:
                raise ScannerOrchestratorError(
                    f"{mode} scan is already running"
                )

            self._running_modes.add(mode)

        started = self._now_iso()

        errors: list[str] = []
        final_results: list[
            FinalStockSignal
        ] = []

        sectors_scanned = 0
        stocks_ranked = 0
        stocks_deep_scanned = 0

        try:
            # One process-wide scan at a time. This avoids FYERS rate bursts
            # when Intraday/BTST/Swing refresh windows overlap.
            with self._scan_lock:
                sectors = (
                    self._scan_sectors()
                )

                sectors_scanned = len(
                    sectors
                )

                selected_sectors = [
                    sector
                    for sector in sectors
                    if sector.eligible
                ][
                    : Config.TOP_SECTORS_COUNT
                ]

                for sector in selected_sectors:
                    try:
                        ranked = (
                            self._rank_sector(
                                sector
                            )
                        )
                    except Exception as exc:
                        errors.append(
                            f"{sector.sector_name}: stock ranking failed: {exc}"
                        )
                        continue

                    ranked = [
                        stock
                        for stock in ranked
                        if stock.eligible
                    ][
                        : Config.TOP_STOCKS_PER_SECTOR
                    ]

                    stocks_ranked += len(
                        ranked
                    )

                    for stock in ranked:
                        stocks_deep_scanned += 1

                        try:
                            result = (
                                self.common_engine
                                .evaluate(
                                    stock,
                                    sector,
                                    mode=mode,
                                )
                            )
                        except Exception as exc:
                            errors.append(
                                f"{stock.fyers_symbol}: deep scan failed: {exc}"
                            )
                            continue

                        if result is not None:
                            final_results.append(
                                result
                            )

                final_results = (
                    self._sort_results(
                        final_results
                    )
                )

                # Hard universe safety.
                final_results = final_results[
                    : Config.MAX_SCANNER_UNIVERSE
                ]

                completed = self._now_iso()

                run = ScannerRun(
                    mode=mode,
                    started_at=started,
                    completed_at=completed,
                    sectors_scanned=(
                        sectors_scanned
                    ),
                    sectors_selected=len(
                        selected_sectors
                    ),
                    stocks_ranked=stocks_ranked,
                    stocks_deep_scanned=(
                        stocks_deep_scanned
                    ),
                    buy_count=sum(
                        1
                        for item
                        in final_results
                        if item.signal == "BUY"
                    ),
                    strong_buy_count=sum(
                        1
                        for item
                        in final_results
                        if item.signal
                        == "STRONG BUY"
                    ),
                    results=tuple(
                        final_results
                    ),
                    errors=tuple(errors),
                )

                self._persist_run(run)

                with self._state_lock:
                    self._last_runs[
                        mode
                    ] = run

                return run

        finally:
            with self._state_lock:
                self._running_modes.discard(
                    mode
                )

    # ========================================================
    # RUN ALL MODES
    # ========================================================

    def run_all(
        self,
    ) -> dict[str, ScannerRun]:
        results: dict[
            str,
            ScannerRun,
        ] = {}

        for mode in (
            Config.SUPPORTED_TRADING_MODES
        ):
            try:
                results[mode] = self.run(
                    mode
                )
            except Exception:
                # Do not fabricate a successful run.
                continue

        return results

    # ========================================================
    # SECTOR SCAN ADAPTER
    # ========================================================

    def _scan_sectors(
        self,
    ) -> list[SectorScanResult]:
        """
        Supports the final sector scanner's standard method names.
        """
        scanner = self.sector_scanner

        for method_name in (
            "scan",
            "scan_sectors",
            "get_top_sectors",
        ):
            method = getattr(
                scanner,
                method_name,
                None,
            )

            if callable(method):
                result = method()

                if isinstance(
                    result,
                    list,
                ):
                    return self._sort_sectors(
                        result
                    )

                if isinstance(
                    result,
                    tuple,
                ):
                    return self._sort_sectors(
                        list(result)
                    )

        raise ScannerOrchestratorError(
            "SectorScanner has no supported scan method"
        )

    # ========================================================
    # STOCK RANKER ADAPTER
    # ========================================================

    def _rank_sector(
        self,
        sector: SectorScanResult,
    ) -> list[RankedStock]:
        ranker = self.stock_ranker

        for method_name in (
            "rank_sector",
            "rank_stocks",
            "rank",
        ):
            method = getattr(
                ranker,
                method_name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                lambda: method(
                    sector.sector_key
                ),
                lambda: method(
                    sector
                ),
                lambda: method(
                    sector_key=(
                        sector.sector_key
                    )
                ),
                lambda: method(
                    sector=sector
                ),
            )

            last_error: Exception | None = None

            for attempt in attempts:
                try:
                    result = attempt()
                except TypeError as exc:
                    last_error = exc
                    continue

                if isinstance(
                    result,
                    tuple,
                ):
                    result = list(result)

                if isinstance(
                    result,
                    list,
                ):
                    return sorted(
                        result,
                        key=lambda item: (
                            item.score,
                            -item.rank,
                        ),
                        reverse=True,
                    )

            if last_error:
                continue

        raise ScannerOrchestratorError(
            f"Unable to rank stocks for {sector.sector_key}"
        )

    # ========================================================
    # SORTING
    # ========================================================

    @staticmethod
    def _sort_sectors(
        sectors: list[
            SectorScanResult
        ],
    ) -> list[SectorScanResult]:
        return sorted(
            sectors,
            key=lambda item: (
                1
                if item.eligible
                else 0,
                item.score,
                -item.rank,
            ),
            reverse=True,
        )

    @staticmethod
    def _sort_results(
        results: list[
            FinalStockSignal
        ],
    ) -> list[FinalStockSignal]:
        return sorted(
            results,
            key=lambda item: (
                1
                if item.signal
                == "STRONG BUY"
                else 0,
                item.final_confidence,
                item.technical_score,
                item.stock_rank_score,
                item.sector_score,
                -item.stock_rank,
            ),
            reverse=True,
        )

    # ========================================================
    # PERSISTENCE
    # ========================================================

    def _persist_run(
        self,
        run: ScannerRun,
    ) -> None:
        path = Config.get_scan_results_file(
            run.mode
        )

        directory = os.path.dirname(
            path
        )

        if directory:
            os.makedirs(
                directory,
                exist_ok=True,
            )

        payload = {
            "app": Config.APP_NAME,
            "version": Config.APP_VERSION,
            "mode": run.mode,
            "started_at": run.started_at,
            "completed_at": (
                run.completed_at
            ),
            "sectors_scanned": (
                run.sectors_scanned
            ),
            "sectors_selected": (
                run.sectors_selected
            ),
            "stocks_ranked": (
                run.stocks_ranked
            ),
            "stocks_deep_scanned": (
                run.stocks_deep_scanned
            ),
            "buy_count": run.buy_count,
            "strong_buy_count": (
                run.strong_buy_count
            ),
            "errors": list(
                run.errors
            ),
            "results": [
                asdict(item)
                for item in run.results
            ],
        }

        temp_path = (
            f"{path}.tmp"
        )

        with open(
            temp_path,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

        os.replace(
            temp_path,
            path,
        )

    # ========================================================
    # LOAD PERSISTED RESULTS
    # ========================================================

    def load_persisted(
        self,
        mode: str | None = None,
    ) -> dict[str, Any] | None:
        mode = Config.normalize_trading_mode(
            mode
        )

        path = Config.get_scan_results_file(
            mode
        )

        if not os.path.exists(
            path
        ):
            return None

        try:
            with open(
                path,
                "r",
                encoding="utf-8",
            ) as handle:
                data = json.load(
                    handle
                )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return None

        if not isinstance(
            data,
            dict,
        ):
            return None

        return data

    # ========================================================
    # STATE
    # ========================================================

    def is_running(
        self,
        mode: str | None = None,
    ) -> bool:
        mode = Config.normalize_trading_mode(
            mode
        )

        with self._state_lock:
            return (
                mode
                in self._running_modes
            )

    def get_last_run(
        self,
        mode: str | None = None,
    ) -> ScannerRun | None:
        mode = Config.normalize_trading_mode(
            mode
        )

        with self._state_lock:
            return self._last_runs.get(
                mode
            )

    def get_last_results(
        self,
        mode: str | None = None,
    ) -> list[FinalStockSignal]:
        run = self.get_last_run(
            mode
        )

        if run is None:
            return []

        return list(
            run.results
        )

    def status(
        self,
    ) -> dict[str, Any]:
        with self._state_lock:
            running = sorted(
                self._running_modes
            )

            last_runs = {
                mode: {
                    "completed_at": (
                        run.completed_at
                    ),
                    "buy_count": (
                        run.buy_count
                    ),
                    "strong_buy_count": (
                        run.strong_buy_count
                    ),
                    "stocks_deep_scanned": (
                        run.stocks_deep_scanned
                    ),
                    "error_count": len(
                        run.errors
                    ),
                }
                for mode, run
                in self._last_runs.items()
            }

        return {
            "app": Config.APP_NAME,
            "version": Config.APP_VERSION,
            "running_modes": running,
            "last_runs": last_runs,
        }

    # ========================================================
    # TIME
    # ========================================================

    @staticmethod
    def _now_iso(
    ) -> str:
        return datetime.now(
            ZoneInfo(
                Config.MARKET_TIMEZONE
            )
        ).isoformat(
            timespec="seconds"
        )


# ============================================================
# SINGLETON
# ============================================================

_default_orchestrator: (
    ScannerOrchestrator | None
) = None

_default_orchestrator_lock = (
    threading.Lock()
)


def get_scanner_orchestrator(
) -> ScannerOrchestrator:
    global _default_orchestrator

    if (
        _default_orchestrator
        is not None
    ):
        return _default_orchestrator

    with _default_orchestrator_lock:
        if (
            _default_orchestrator
            is None
        ):
            _default_orchestrator = (
                ScannerOrchestrator()
            )

    return _default_orchestrator


def run_eagle_scan(
    mode: str | None = None,
) -> ScannerRun:
    return (
        get_scanner_orchestrator()
        .run(mode)
    )


def run_all_eagle_scans(
) -> dict[str, ScannerRun]:
    return (
        get_scanner_orchestrator()
        .run_all()
    )
