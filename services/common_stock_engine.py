from __future__ import annotations

"""
Eagle Smart Scanner - Common Stock Engine

Final stock-level fusion engine.

Combines:
- Strong sector context
- Ranked stock context
- PatternScanner
- TechnicalScanner

Produces:
- BUY / STRONG BUY only
- Current Price
- Entry
- Stop Loss
- Target
- Risk/Reward
- Technical score
- Sector score
- Stock pre-rank score
- Final confidence/probability
- Mode
- Reasons

No fundamentals.
No NIFTY500 dependency.
No fake/random data.
"""

import threading
from dataclasses import asdict, dataclass
from typing import Any

from config import Config
from scanners.pattern_scanner import (
    PatternScanResult,
    PatternScanner,
    get_pattern_scanner,
)
from scanners.technical_scanner import (
    TechnicalScanResult,
    TechnicalScanner,
    get_technical_scanner,
)
from services.market_data_service import (
    MarketDataService,
    get_market_data_service,
)
from services.sector_scanner import SectorScanResult
from services.stock_ranker import RankedStock


class CommonStockEngineError(RuntimeError):
    """Final stock fusion engine error."""


@dataclass(frozen=True)
class FinalStockSignal:
    sector_rank: int
    sector_key: str
    sector_name: str
    sector_score: float
    sector_strength: str

    stock_rank: int
    stock_rank_score: float

    symbol: str
    fyers_symbol: str
    company_name: str
    industry: str

    mode: str
    signal: str

    current_price: float
    entry_price: float
    stop_loss: float
    target: float
    risk_reward: float
    stop_loss_percent: float

    technical_score: float
    pattern_score: float
    final_confidence: float
    move_up_probability: float

    confirmations: int
    minimum_confirmations: int

    chart_pattern: str
    candle_pattern: str

    reasons: tuple[str, ...]


class CommonStockEngine:
    """
    Combines all technical layers into final scanner rows.
    """

    def __init__(
        self,
        market_data: MarketDataService | None = None,
        technical_scanner: TechnicalScanner | None = None,
        pattern_scanner: PatternScanner | None = None,
    ) -> None:
        self.market_data = (
            market_data
            or get_market_data_service()
        )

        self.technical_scanner = (
            technical_scanner
            or get_technical_scanner()
        )

        self.pattern_scanner = (
            pattern_scanner
            or get_pattern_scanner()
        )

        self._lock = threading.RLock()

        self._last_results: dict[
            tuple[str, str],
            FinalStockSignal,
        ] = {}

    # ========================================================
    # MAIN
    # ========================================================

    def evaluate(
        self,
        stock: RankedStock,
        sector: SectorScanResult,
        *,
        mode: str | None = None,
    ) -> FinalStockSignal | None:
        mode = Config.normalize_trading_mode(mode)

        # Sector and stock must still belong to the same universe branch.
        if (
            stock.sector_key
            != sector.sector_key
        ):
            raise CommonStockEngineError(
                "Stock/sector mismatch"
            )

        if not sector.eligible:
            return None

        if not stock.eligible:
            return None

        # ----------------------------------------------------
        # PRIMARY FRAME FOR PATTERN SCAN
        # ----------------------------------------------------
        primary_df = (
            self.market_data
            .get_primary_dataframe(
                stock.fyers_symbol,
                mode,
            )
        )

        pattern_result = (
            self.pattern_scanner
            .scan(
                primary_df,
                mode=mode,
            )
        )

        # ----------------------------------------------------
        # DEEP TECHNICAL SCAN WITH PATTERN CONFIRMATION
        # ----------------------------------------------------
        technical = (
            self.technical_scanner
            .scan(
                stock.fyers_symbol,
                mode=mode,
                pattern_confirmation=(
                    pattern_result.confirmation
                ),
            )
        )

        if not technical.eligible:
            return None

        if (
            Config.SHOW_ONLY_BUY_SIGNALS
            and technical.signal
            not in {
                "BUY",
                "STRONG BUY",
            }
        ):
            return None

        final_confidence = (
            self._calculate_final_confidence(
                sector=sector,
                stock=stock,
                technical=technical,
                pattern=pattern_result,
            )
        )

        move_up_probability = (
            self._confidence_to_probability(
                final_confidence
            )
        )

        reasons = (
            self._build_reasons(
                sector=sector,
                stock=stock,
                technical=technical,
                pattern=pattern_result,
                final_confidence=(
                    final_confidence
                ),
            )
        )

        final_signal = self._final_signal(
            technical=technical,
            final_confidence=(
                final_confidence
            ),
        )

        result = FinalStockSignal(
            sector_rank=sector.rank,
            sector_key=sector.sector_key,
            sector_name=sector.sector_name,
            sector_score=round(
                sector.score,
                2,
            ),
            sector_strength=(
                sector.strength
            ),
            stock_rank=stock.rank,
            stock_rank_score=round(
                stock.score,
                2,
            ),
            symbol=stock.symbol,
            fyers_symbol=(
                stock.fyers_symbol
            ),
            company_name=(
                stock.company_name
            ),
            industry=stock.industry,
            mode=mode,
            signal=final_signal,
            current_price=(
                technical.current_price
            ),
            entry_price=(
                technical.entry_price
            ),
            stop_loss=(
                technical.stop_loss
            ),
            target=technical.target,
            risk_reward=(
                technical.risk_reward
            ),
            stop_loss_percent=(
                technical.stop_loss_percent
            ),
            technical_score=(
                technical.score
            ),
            pattern_score=round(
                pattern_result.total_pattern_score,
                2,
            ),
            final_confidence=round(
                final_confidence,
                2,
            ),
            move_up_probability=round(
                move_up_probability,
                2,
            ),
            confirmations=(
                technical.confirmations
            ),
            minimum_confirmations=(
                technical.minimum_confirmations
            ),
            chart_pattern=(
                pattern_result
                .best_chart_pattern
            ),
            candle_pattern=(
                pattern_result
                .best_candle_pattern
            ),
            reasons=tuple(reasons),
        )

        with self._lock:
            self._last_results[
                (
                    stock.fyers_symbol,
                    mode,
                )
            ] = result

        return result

    # ========================================================
    # BATCH
    # ========================================================

    def evaluate_sector_stocks(
        self,
        stocks: list[RankedStock],
        sector: SectorScanResult,
        *,
        mode: str | None = None,
    ) -> list[FinalStockSignal]:
        results: list[
            FinalStockSignal
        ] = []

        for stock in stocks:
            try:
                result = self.evaluate(
                    stock,
                    sector,
                    mode=mode,
                )
            except Exception:
                continue

            if result is not None:
                results.append(result)

        results.sort(
            key=lambda item: (
                1
                if item.signal
                == "STRONG BUY"
                else 0,
                item.final_confidence,
                item.technical_score,
                item.stock_rank_score,
                item.sector_score,
            ),
            reverse=True,
        )

        return results

    # ========================================================
    # CONFIDENCE
    # ========================================================

    @staticmethod
    def _calculate_final_confidence(
        *,
        sector: SectorScanResult,
        stock: RankedStock,
        technical: TechnicalScanResult,
        pattern: PatternScanResult,
    ) -> float:
        """
        Final 0-100 confidence.

        Technical analysis carries the highest weight.
        """
        score = (
            technical.score * 0.60
            + stock.score * 0.15
            + sector.score * 0.15
            + pattern.total_pattern_score
            * 0.10
        )

        # Confirmation quality bonus.
        if (
            technical.confirmations
            >= (
                technical.minimum_confirmations
                + 3
            )
        ):
            score += 3.0

        # Strong chart+candle agreement bonus.
        if (
            pattern.chart_pattern_bullish
            and pattern.candle_pattern_bullish
        ):
            score += 2.0

        # Strong sector alignment bonus.
        if (
            sector.score
            >= Config.STRONG_SECTOR_SCORE
        ):
            score += 2.0

        return min(
            max(
                score,
                0.0,
            ),
            100.0,
        )

    @staticmethod
    def _confidence_to_probability(
        confidence: float,
    ) -> float:
        """
        Conservative display transformation.

        This is NOT a statistically calibrated future-return probability.
        It is the scanner's technical confidence expressed on a %
        scale for the dashboard.
        """
        value = max(
            0.0,
            min(
                float(confidence),
                100.0,
            ),
        )

        # Compress extremes to avoid implying certainty.
        return (
            50.0
            + (
                value - 50.0
            ) * 0.80
        )

    # ========================================================
    # FINAL SIGNAL
    # ========================================================

    @staticmethod
    def _final_signal(
        *,
        technical: TechnicalScanResult,
        final_confidence: float,
    ) -> str:
        if not technical.eligible:
            return ""

        if (
            technical.signal
            == "STRONG BUY"
            and final_confidence
            >= Config.STRONG_BUY_MIN_SCORE
        ):
            return "STRONG BUY"

        return "BUY"

    # ========================================================
    # REASONS
    # ========================================================

    @staticmethod
    def _build_reasons(
        *,
        sector: SectorScanResult,
        stock: RankedStock,
        technical: TechnicalScanResult,
        pattern: PatternScanResult,
        final_confidence: float,
    ) -> list[str]:
        reasons: list[str] = []

        reasons.append(
            f"{sector.sector_name} sector score "
            f"{sector.score:.1f}"
        )

        reasons.append(
            f"Stock pre-rank score "
            f"{stock.score:.1f}"
        )

        reasons.append(
            f"Technical score "
            f"{technical.score:.1f}"
        )

        reasons.append(
            f"{technical.confirmations} technical confirmations"
        )

        if (
            pattern.best_chart_pattern
        ):
            reasons.append(
                f"Chart pattern: "
                f"{pattern.best_chart_pattern}"
            )

        if (
            pattern.best_candle_pattern
        ):
            reasons.append(
                f"Candlestick: "
                f"{pattern.best_candle_pattern}"
            )

        reasons.append(
            f"Risk/Reward "
            f"{technical.risk_reward:.2f}"
        )

        reasons.append(
            f"Final confidence "
            f"{final_confidence:.1f}"
        )

        return reasons

    # ========================================================
    # LAST RESULTS
    # ========================================================

    def get_last_result(
        self,
        symbol: str,
        *,
        mode: str | None = None,
    ) -> FinalStockSignal | None:
        normalized_mode = (
            Config.normalize_trading_mode(
                mode
            )
        )

        fyers_symbol = (
            self.technical_scanner
            ._normalize_fyers_symbol(
                symbol
            )
        )

        with self._lock:
            return (
                self._last_results.get(
                    (
                        fyers_symbol,
                        normalized_mode,
                    )
                )
            )

    def get_last_results(
        self,
    ) -> list[FinalStockSignal]:
        with self._lock:
            values = list(
                self._last_results.values()
            )

        values.sort(
            key=lambda item: (
                1
                if item.signal
                == "STRONG BUY"
                else 0,
                item.final_confidence,
            ),
            reverse=True,
        )

        return values

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def evaluate_as_dict(
        self,
        stock: RankedStock,
        sector: SectorScanResult,
        *,
        mode: str | None = None,
    ) -> dict[str, Any] | None:
        result = self.evaluate(
            stock,
            sector,
            mode=mode,
        )

        if result is None:
            return None

        return asdict(result)


# ============================================================
# SINGLETON
# ============================================================

_default_common_stock_engine: (
    CommonStockEngine | None
) = None

_default_common_stock_engine_lock = (
    threading.Lock()
)


def get_common_stock_engine(
) -> CommonStockEngine:
    global _default_common_stock_engine

    if (
        _default_common_stock_engine
        is not None
    ):
        return (
            _default_common_stock_engine
        )

    with (
        _default_common_stock_engine_lock
    ):
        if (
            _default_common_stock_engine
            is None
        ):
            _default_common_stock_engine = (
                CommonStockEngine()
            )

    return (
        _default_common_stock_engine
    )


# ============================================================
# MODULE HELPERS
# ============================================================

def evaluate_ranked_stock(
    stock: RankedStock,
    sector: SectorScanResult,
    *,
    mode: str | None = None,
) -> FinalStockSignal | None:
    return (
        get_common_stock_engine()
        .evaluate(
            stock,
            sector,
            mode=mode,
        )
    )
