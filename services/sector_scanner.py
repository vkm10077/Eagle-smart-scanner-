from __future__ import annotations

"""
Eagle Smart Scanner - Sector Scanner

Purpose
-------
Rank candidate NSE sectors dynamically using pure technical strength.

Inputs
------
- Live sector/index snapshot
- Historical daily candles
- NIFTY 50 benchmark-relative strength

Outputs
-------
- Ranked sector list
- Top N sectors for downstream stock ranking
- Sector score, strength label, reasons and technical details

Rules
-----
- No fundamental analysis
- No hard-coded "winning" sector
- No fake/random fallback
- Sector must satisfy configured mandatory conditions
"""

import threading
from dataclasses import asdict, dataclass
from typing import Any

from config import Config
from services.index_service import (
    IndexService,
    IndexTechnicalSnapshot,
    get_index_service,
)


class SectorScannerError(RuntimeError):
    """Sector scanner error."""


@dataclass(frozen=True)
class SectorScanResult:
    rank: int
    sector_key: str
    sector_name: str
    fyers_symbol: str

    ltp: float
    change_percent: float
    return_5d: float
    return_20d: float
    rsi14: float
    relative_strength_20d: float

    ema20: float
    ema50: float
    ema200: float

    above_ema20: bool
    above_ema50: bool
    above_ema200: bool
    bullish_ema_structure: bool

    distance_from_20d_high_pct: float
    distance_from_52w_high_pct: float

    score: float
    strength: str
    eligible: bool
    reasons: tuple[str, ...]


class SectorScanner:
    """
    Pure technical sector ranking engine.
    """

    def __init__(
        self,
        index_service: IndexService | None = None,
    ) -> None:
        self.index_service = (
            index_service
            or get_index_service()
        )

        self._lock = threading.RLock()
        self._last_results: list[
            SectorScanResult
        ] = []

    # ========================================================
    # MAIN SCAN
    # ========================================================

    def scan(
        self,
        *,
        top_n: int | None = None,
    ) -> list[SectorScanResult]:
        snapshots = (
            self.index_service
            .get_all_sector_technical_snapshots()
        )

        scored: list[
            SectorScanResult
        ] = []

        for snapshot in snapshots:
            result = self._evaluate_sector(
                snapshot
            )

            scored.append(result)

        # Eligible first, then score, live change, 20D RS.
        scored.sort(
            key=lambda item: (
                1 if item.eligible else 0,
                item.score,
                item.change_percent,
                item.relative_strength_20d,
                item.return_20d,
            ),
            reverse=True,
        )

        ranked: list[
            SectorScanResult
        ] = []

        for idx, item in enumerate(
            scored,
            start=1,
        ):
            ranked.append(
                SectorScanResult(
                    rank=idx,
                    sector_key=item.sector_key,
                    sector_name=item.sector_name,
                    fyers_symbol=item.fyers_symbol,
                    ltp=item.ltp,
                    change_percent=(
                        item.change_percent
                    ),
                    return_5d=item.return_5d,
                    return_20d=item.return_20d,
                    rsi14=item.rsi14,
                    relative_strength_20d=(
                        item.relative_strength_20d
                    ),
                    ema20=item.ema20,
                    ema50=item.ema50,
                    ema200=item.ema200,
                    above_ema20=item.above_ema20,
                    above_ema50=item.above_ema50,
                    above_ema200=item.above_ema200,
                    bullish_ema_structure=(
                        item.bullish_ema_structure
                    ),
                    distance_from_20d_high_pct=(
                        item.distance_from_20d_high_pct
                    ),
                    distance_from_52w_high_pct=(
                        item.distance_from_52w_high_pct
                    ),
                    score=item.score,
                    strength=item.strength,
                    eligible=item.eligible,
                    reasons=item.reasons,
                )
            )

        with self._lock:
            self._last_results = list(
                ranked
            )

        limit = int(
            top_n
            if top_n is not None
            else Config.TOP_SECTORS_COUNT
        )

        if limit <= 0:
            return []

        # Only eligible sectors enter the Eagle stock universe.
        eligible = [
            item
            for item in ranked
            if item.eligible
        ]

        return eligible[:limit]

    def scan_all(
        self,
    ) -> list[SectorScanResult]:
        """
        Return all ranked sectors, including ineligible sectors.
        Useful for dashboard diagnostics.
        """
        self.scan(
            top_n=Config.TOP_SECTORS_COUNT
        )

        with self._lock:
            return list(
                self._last_results
            )

    # ========================================================
    # EVALUATION
    # ========================================================

    def _evaluate_sector(
        self,
        snapshot: IndexTechnicalSnapshot,
    ) -> SectorScanResult:
        score = 0.0
        reasons: list[str] = []

        # ----------------------------------------------------
        # 1. LIVE / CURRENT-DAY STRENGTH - 15
        # ----------------------------------------------------
        if snapshot.change_percent > 1.0:
            score += 15.0
            reasons.append(
                "Strong positive live change"
            )
        elif snapshot.change_percent > 0.5:
            score += 12.0
            reasons.append(
                "Positive live momentum"
            )
        elif snapshot.change_percent > 0:
            score += 8.0
            reasons.append(
                "Sector is positive"
            )
        elif snapshot.change_percent == 0:
            score += 3.0
        else:
            reasons.append(
                "Sector is negative today"
            )

        # ----------------------------------------------------
        # 2. EMA TREND STRUCTURE - 25
        # ----------------------------------------------------
        if snapshot.bullish_ema_structure:
            score += 25.0
            reasons.append(
                "Bullish EMA20 > EMA50 > EMA200 structure"
            )
        else:
            if snapshot.above_ema20:
                score += 7.0

            if snapshot.above_ema50:
                score += 7.0

            if snapshot.above_ema200:
                score += 6.0

        # ----------------------------------------------------
        # 3. 5-DAY / 20-DAY MOMENTUM - 15
        # ----------------------------------------------------
        momentum_score = 0.0

        if snapshot.return_5d > 0:
            momentum_score += 6.0

        if snapshot.return_5d >= 2.0:
            momentum_score += 2.0

        if snapshot.return_20d > 0:
            momentum_score += 5.0

        if snapshot.return_20d >= 4.0:
            momentum_score += 2.0

        score += min(
            momentum_score,
            15.0,
        )

        if momentum_score >= 10.0:
            reasons.append(
                "Strong multi-day momentum"
            )

        # ----------------------------------------------------
        # 4. RELATIVE STRENGTH VS NIFTY 50 - 20
        # ----------------------------------------------------
        rs = snapshot.relative_strength_20d

        if rs >= 5.0:
            score += 20.0
            reasons.append(
                "Strongly outperforming NIFTY 50"
            )
        elif rs >= 2.0:
            score += 16.0
            reasons.append(
                "Outperforming NIFTY 50"
            )
        elif rs > Config.MIN_RELATIVE_STRENGTH_PCT:
            score += 12.0
            reasons.append(
                "Positive relative strength"
            )
        elif rs == 0:
            score += 5.0
        else:
            reasons.append(
                "Underperforming NIFTY 50"
            )

        # ----------------------------------------------------
        # 5. RSI QUALITY - 10
        # ----------------------------------------------------
        rsi = snapshot.rsi14

        if 55.0 <= rsi <= 70.0:
            score += 10.0
            reasons.append(
                "Healthy bullish RSI"
            )
        elif 50.0 <= rsi < 55.0:
            score += 7.0
        elif 70.0 < rsi <= 75.0:
            score += 6.0
        elif rsi > 75.0:
            score += 2.0
            reasons.append(
                "RSI is overextended"
            )

        # ----------------------------------------------------
        # 6. POSITION NEAR 20-DAY HIGH - 10
        # ----------------------------------------------------
        d20 = (
            snapshot
            .distance_from_20d_high_pct
        )

        if d20 <= 1.0:
            score += 10.0
            reasons.append(
                "Trading near 20-day high"
            )
        elif d20 <= 3.0:
            score += 7.0
        elif d20 <= 5.0:
            score += 4.0

        # ----------------------------------------------------
        # 7. 52-WEEK POSITION - 5
        # ----------------------------------------------------
        d52 = (
            snapshot
            .distance_from_52w_high_pct
        )

        if d52 <= 5.0:
            score += 5.0
        elif d52 <= 10.0:
            score += 3.0
        elif d52 <= 20.0:
            score += 1.0

        score = round(
            min(
                max(score, 0.0),
                100.0,
            ),
            2,
        )

        # ----------------------------------------------------
        # MANDATORY ELIGIBILITY
        # ----------------------------------------------------
        eligible = True

        if (
            Config.REQUIRE_SECTOR_POSITIVE
            and snapshot.change_percent
            < Config.MIN_SECTOR_CHANGE_PCT
        ):
            eligible = False
            reasons.append(
                "Failed positive sector rule"
            )

        if (
            Config.REQUIRE_SECTOR_BULLISH_TREND
            and not snapshot.bullish_ema_structure
        ):
            eligible = False
            reasons.append(
                "Failed bullish sector trend rule"
            )

        if (
            Config.REQUIRE_SECTOR_RELATIVE_STRENGTH
            and snapshot.relative_strength_20d
            <= Config.MIN_RELATIVE_STRENGTH_PCT
        ):
            eligible = False
            reasons.append(
                "Failed sector relative-strength rule"
            )

        if score < Config.MIN_SECTOR_SCORE:
            eligible = False
            reasons.append(
                "Sector score below minimum"
            )

        strength = self._strength_label(
            score=score,
            eligible=eligible,
        )

        return SectorScanResult(
            rank=0,
            sector_key=snapshot.key,
            sector_name=snapshot.name,
            fyers_symbol=snapshot.fyers_symbol,
            ltp=snapshot.ltp,
            change_percent=(
                snapshot.change_percent
            ),
            return_5d=snapshot.return_5d,
            return_20d=snapshot.return_20d,
            rsi14=snapshot.rsi14,
            relative_strength_20d=(
                snapshot.relative_strength_20d
            ),
            ema20=snapshot.ema20,
            ema50=snapshot.ema50,
            ema200=snapshot.ema200,
            above_ema20=(
                snapshot.above_ema20
            ),
            above_ema50=(
                snapshot.above_ema50
            ),
            above_ema200=(
                snapshot.above_ema200
            ),
            bullish_ema_structure=(
                snapshot.bullish_ema_structure
            ),
            distance_from_20d_high_pct=(
                snapshot.distance_from_20d_high_pct
            ),
            distance_from_52w_high_pct=(
                snapshot.distance_from_52w_high_pct
            ),
            score=score,
            strength=strength,
            eligible=eligible,
            reasons=tuple(reasons),
        )

    # ========================================================
    # LABELS
    # ========================================================

    @staticmethod
    def _strength_label(
        *,
        score: float,
        eligible: bool,
    ) -> str:
        if not eligible:
            return "WEAK"

        if score >= Config.STRONG_SECTOR_SCORE:
            return "STRONG"

        return "BULLISH"

    # ========================================================
    # LAST RESULTS
    # ========================================================

    def get_last_results(
        self,
        *,
        eligible_only: bool = False,
    ) -> list[SectorScanResult]:
        with self._lock:
            results = list(
                self._last_results
            )

        if eligible_only:
            return [
                item
                for item in results
                if item.eligible
            ]

        return results

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def scan_as_dicts(
        self,
        *,
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        return [
            asdict(item)
            for item in self.scan(
                top_n=top_n,
            )
        ]

    def scan_all_as_dicts(
        self,
    ) -> list[dict[str, Any]]:
        return [
            asdict(item)
            for item in self.scan_all()
        ]


# ============================================================
# SINGLETON
# ============================================================

_default_sector_scanner: (
    SectorScanner | None
) = None

_default_sector_scanner_lock = (
    threading.Lock()
)


def get_sector_scanner(
) -> SectorScanner:
    global _default_sector_scanner

    if _default_sector_scanner is not None:
        return _default_sector_scanner

    with _default_sector_scanner_lock:
        if _default_sector_scanner is None:
            _default_sector_scanner = (
                SectorScanner()
            )

    return _default_sector_scanner


# ============================================================
# BACKWARD-COMPATIBLE HELPERS
# ============================================================

def scan_top_sectors(
    top_n: int | None = None,
) -> list[SectorScanResult]:
    return (
        get_sector_scanner()
        .scan(
            top_n=top_n,
        )
    )


def scan_all_sectors(
) -> list[SectorScanResult]:
    return (
        get_sector_scanner()
        .scan_all()
    )
