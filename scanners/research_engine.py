from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd

from data.nifty500 import find_stock
from data.sector_map import get_stock_sector
from scanners.fundamental_scanner import (
    FundamentalScanner,
    FundamentalScannerError,
    get_fundamental_scanner,
)
from scanners.pattern_scanner import (
    PatternScanner,
    PatternScannerError,
    get_pattern_scanner,
)
from scanners.probability_engine import (
    ProbabilityEngine,
    ProbabilityEngineError,
    get_probability_engine,
)
from scanners.sector_scanner import (
    SectorScanner,
    SectorScannerError,
    get_sector_scanner,
)
from scanners.technical_scanner import (
    TechnicalScanner,
    TechnicalScannerError,
    get_technical_scanner,
)
from services.fundamental_service import (
    FundamentalDataError,
    FundamentalService,
    get_fundamental_service,
)
from services.market_data_service import (
    MarketDataError,
    MarketDataService,
    get_market_data_service,
)
from utils.helpers import (
    build_stock_result,
    calculate_expected_return,
    calculate_risk_reward,
    clean_text,
    get_holding_period,
    is_buy_signal,
    normalize_score,
    normalize_signal,
    normalize_symbol,
    normalize_timeframe,
    round_price,
    safe_float,
    sort_scan_results,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_exception,
)
from utils.validators import (
    validate_scan_result,
    validate_trade_levels,
)


logger = get_logger("scanners.research_engine")


class ResearchEngineError(RuntimeError):
    """Base exception for research-engine failures."""


class ResearchDataUnavailableError(ResearchEngineError):
    """Raised when verified data required for research is unavailable."""


class ResearchSignalRejectedError(ResearchEngineError):
    """Raised when a stock does not qualify for BUY or STRONG BUY."""


@dataclass
class TradeLevels:
    current_price: float
    entry_price: float
    stop_loss: float
    target_price: float
    risk_reward: float
    expected_return: float
    atr: float
    support: float | None
    resistance: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_price": round(self.current_price, 2),
            "entry_price": round(self.entry_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "target_price": round(self.target_price, 2),
            "risk_reward": round(self.risk_reward, 2),
            "expected_return": round(
                self.expected_return,
                2,
            ),
            "atr": round(self.atr, 2),
            "support": (
                round(self.support, 2)
                if self.support is not None
                else None
            ),
            "resistance": (
                round(self.resistance, 2)
                if self.resistance is not None
                else None
            ),
        }


@dataclass
class ResearchResult:
    symbol: str
    stock_name: str
    sector: str
    timeframe: str
    signal: str
    move_up_probability: float
    overall_score: float
    current_price: float | None
    entry_price: float | None
    stop_loss: float | None
    target_price: float | None
    holding_period: str
    risk_reward: float | None
    expected_return: float | None
    technical: dict[str, Any] = field(
        default_factory=dict
    )
    fundamental: dict[str, Any] = field(
        default_factory=dict
    )
    pattern: dict[str, Any] = field(
        default_factory=dict
    )
    sector_analysis: dict[str, Any] = field(
        default_factory=dict
    )
    probability: dict[str, Any] = field(
        default_factory=dict
    )
    rejection_reasons: list[str] = field(
        default_factory=list
    )
    validation_errors: list[str] = field(
        default_factory=list
    )
    verified: bool = False
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "stock_name": self.stock_name,
            "sector": self.sector,
            "timeframe": self.timeframe,
            "signal": self.signal,
            "move_up_probability": round(
                self.move_up_probability,
                2,
            ),
            "overall_score": round(
                self.overall_score,
                2,
            ),
            "current_price": self.current_price,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target_price": self.target_price,
            "holding_period": self.holding_period,
            "risk_reward": self.risk_reward,
            "expected_return": self.expected_return,
            "technical": self.technical,
            "fundamental": self.fundamental,
            "pattern": self.pattern,
            "sector_analysis": self.sector_analysis,
            "probability": self.probability,
            "rejection_reasons": list(
                self.rejection_reasons
            ),
            "validation_errors": list(
                self.validation_errors
            ),
            "verified": self.verified,
            "generated_at": self.generated_at,
        }


class ResearchEngine:
    """
    Central stock-research engine for Eagle Smart Scanner.

    It combines:
    - Verified FYERS market data
    - Top-10 technical filters
    - Top-10 fundamental filters
    - Top-10 chart patterns
    - Sector strength
    - Multi-timeframe probability calculation
    - Entry, stop-loss and target generation
    - Final BUY / STRONG BUY validation

    The engine never converts missing data into a BUY signal.
    """

    TARGET_RISK_MULTIPLIER = {
        "15_30_days": 2.0,
        "3_month": 2.3,
        "6_month": 2.6,
        "1_year": 3.0,
        "3_year": 3.5,
    }

    ATR_STOP_MULTIPLIER = {
        "15_30_days": 1.5,
        "3_month": 1.8,
        "6_month": 2.0,
        "1_year": 2.3,
        "3_year": 2.7,
    }

    ENTRY_BUFFER_PERCENT = {
        "15_30_days": 0.40,
        "3_month": 0.60,
        "6_month": 0.80,
        "1_year": 1.00,
        "3_year": 1.25,
    }

    MAX_ENTRY_EXTENSION_PERCENT = {
        "15_30_days": 4.0,
        "3_month": 6.0,
        "6_month": 8.0,
        "1_year": 10.0,
        "3_year": 12.0,
    }

    def __init__(
        self,
        *,
        market_data_service: MarketDataService | None = None,
        fundamental_service: FundamentalService | None = None,
        technical_scanner: TechnicalScanner | None = None,
        fundamental_scanner: FundamentalScanner | None = None,
        pattern_scanner: PatternScanner | None = None,
        sector_scanner: SectorScanner | None = None,
        probability_engine: ProbabilityEngine | None = None,
    ) -> None:
        self.market_data_service = (
            market_data_service
            or get_market_data_service()
        )

        self.fundamental_service = (
            fundamental_service
            or get_fundamental_service()
        )

        self.technical_scanner = (
            technical_scanner
            or get_technical_scanner()
        )

        self.fundamental_scanner = (
            fundamental_scanner
            or get_fundamental_scanner()
        )

        self.pattern_scanner = (
            pattern_scanner
            or get_pattern_scanner()
        )

        self.sector_scanner = (
            sector_scanner
            or get_sector_scanner()
        )

        self.probability_engine = (
            probability_engine
            or get_probability_engine()
        )

        self._scan_lock = threading.RLock()

    # ==========================================================
    # STOCK INFORMATION
    # ==========================================================

    def _stock_information(
        self,
        symbol: str,
    ) -> tuple[str, str]:
        stock = find_stock(symbol)

        if stock is not None:
            return (
                stock.company_name,
                get_stock_sector(stock.symbol),
            )

        normalized_symbol = normalize_symbol(
            symbol
        )

        return (
            normalized_symbol,
            get_stock_sector(
                normalized_symbol
            ),
        )

    # ==========================================================
    # ATR AND TRADE LEVELS
    # ==========================================================

    @staticmethod
    def _build_price_dataframe(
        candles: Iterable[dict[str, Any]],
    ) -> pd.DataFrame:
        rows: list[dict[str, float]] = []

        for candle in candles:
            if not isinstance(candle, dict):
                continue

            open_price = safe_float(
                candle.get("open")
            )
            high_price = safe_float(
                candle.get("high")
            )
            low_price = safe_float(
                candle.get("low")
            )
            close_price = safe_float(
                candle.get("close")
            )

            if any(
                value is None
                for value in (
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                )
            ):
                continue

            rows.append(
                {
                    "open": float(open_price),
                    "high": float(high_price),
                    "low": float(low_price),
                    "close": float(close_price),
                }
            )

        dataframe = pd.DataFrame(rows)

        if len(dataframe) < 30:
            raise ResearchDataUnavailableError(
                "Insufficient verified candles for trade levels."
            )

        return dataframe.reset_index(
            drop=True
        )

    @staticmethod
    def _calculate_atr(
        dataframe: pd.DataFrame,
        period: int = 14,
    ) -> float:
        previous_close = (
            dataframe["close"].shift(1)
        )

        true_range = pd.concat(
            [
                dataframe["high"]
                - dataframe["low"],
                (
                    dataframe["high"]
                    - previous_close
                ).abs(),
                (
                    dataframe["low"]
                    - previous_close
                ).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr_series = true_range.ewm(
            alpha=1 / period,
            adjust=False,
            min_periods=period,
        ).mean()

        atr = safe_float(
            atr_series.iloc[-1]
        )

        if atr is None or atr <= 0:
            raise ResearchDataUnavailableError(
                "Valid ATR could not be calculated."
            )

        return atr

    @staticmethod
    def _recent_support(
        dataframe: pd.DataFrame,
        lookback: int = 20,
    ) -> float | None:
        recent = dataframe.tail(
            min(lookback, len(dataframe))
        )

        support = safe_float(
            recent["low"].min()
        )

        if support is None or support <= 0:
            return None

        return support

    @staticmethod
    def _recent_resistance(
        dataframe: pd.DataFrame,
        lookback: int = 20,
    ) -> float | None:
        if len(dataframe) < 2:
            return None

        recent = dataframe.iloc[:-1].tail(
            min(lookback, len(dataframe) - 1)
        )

        resistance = safe_float(
            recent["high"].max()
        )

        if (
            resistance is None
            or resistance <= 0
        ):
            return None

        return resistance

    def _calculate_trade_levels(
        self,
        *,
        current_price: float,
        candles: Iterable[dict[str, Any]],
        timeframe: str,
        technical_result: dict[str, Any],
        pattern_result: dict[str, Any],
    ) -> TradeLevels:
        dataframe = self._build_price_dataframe(
            candles
        )

        atr = self._calculate_atr(
            dataframe
        )

        technical_support = safe_float(
            technical_result.get("support")
        )

        technical_resistance = safe_float(
            technical_result.get(
                "resistance"
            )
        )

        strongest_pattern = None

        pattern_items = pattern_result.get(
            "patterns"
        )

        if isinstance(pattern_items, list):
            confirmed_patterns = [
                item
                for item in pattern_items
                if (
                    isinstance(item, dict)
                    and item.get("confirmed")
                )
            ]

            if confirmed_patterns:
                strongest_pattern = max(
                    confirmed_patterns,
                    key=lambda item: (
                        safe_float(
                            item.get("score"),
                            default=0.0,
                        )
                        or 0.0
                    ),
                )

        pattern_breakout = (
            safe_float(
                strongest_pattern.get(
                    "breakout_price"
                )
            )
            if isinstance(
                strongest_pattern,
                dict,
            )
            else None
        )

        pattern_support = (
            safe_float(
                strongest_pattern.get(
                    "support"
                )
            )
            if isinstance(
                strongest_pattern,
                dict,
            )
            else None
        )

        recent_support = (
            self._recent_support(
                dataframe
            )
        )

        recent_resistance = (
            self._recent_resistance(
                dataframe
            )
        )

        support_candidates = [
            value
            for value in (
                technical_support,
                pattern_support,
                recent_support,
            )
            if (
                value is not None
                and value > 0
                and value < current_price
            )
        ]

        resistance_candidates = [
            value
            for value in (
                pattern_breakout,
                technical_resistance,
                recent_resistance,
            )
            if (
                value is not None
                and value > 0
            )
        ]

        support = (
            max(support_candidates)
            if support_candidates
            else None
        )

        resistance = (
            max(resistance_candidates)
            if resistance_candidates
            else None
        )

        entry_buffer = (
            current_price
            * self.ENTRY_BUFFER_PERCENT[
                timeframe
            ]
            / 100
        )

        if (
            resistance is not None
            and current_price
            >= resistance
        ):
            entry_price = max(
                current_price,
                resistance + entry_buffer,
            )
        else:
            entry_price = (
                current_price
                + entry_buffer
            )

        maximum_entry = (
            current_price
            * (
                1
                + self.MAX_ENTRY_EXTENSION_PERCENT[
                    timeframe
                ]
                / 100
            )
        )

        entry_price = min(
            entry_price,
            maximum_entry,
        )

        atr_stop = (
            entry_price
            - atr
            * self.ATR_STOP_MULTIPLIER[
                timeframe
            ]
        )

        if support is not None:
            support_stop = (
                support
                - atr * 0.25
            )

            stop_loss = max(
                0.01,
                min(
                    atr_stop,
                    support_stop,
                ),
            )
        else:
            stop_loss = max(
                0.01,
                atr_stop,
            )

        risk = entry_price - stop_loss

        if risk <= 0:
            raise ResearchDataUnavailableError(
                "A valid trade risk could not be calculated."
            )

        target_price = (
            entry_price
            + risk
            * self.TARGET_RISK_MULTIPLIER[
                timeframe
            ]
        )

        risk_reward = calculate_risk_reward(
            entry_price,
            stop_loss,
            target_price,
        )

        expected_return = (
            calculate_expected_return(
                entry_price,
                target_price,
            )
        )

        if (
            risk_reward is None
            or expected_return is None
        ):
            raise ResearchDataUnavailableError(
                "Trade levels failed risk validation."
            )

        trade_validation = (
            validate_trade_levels(
                current_price=current_price,
                entry_price=entry_price,
                stop_loss=stop_loss,
                target_price=target_price,
                timeframe=timeframe,
            )
        )

        if not trade_validation.is_valid:
            raise ResearchSignalRejectedError(
                "; ".join(
                    trade_validation.errors
                )
            )

        return TradeLevels(
            current_price=current_price,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            risk_reward=risk_reward,
            expected_return=expected_return,
            atr=atr,
            support=support,
            resistance=resistance,
        )

    # ==========================================================
    # REJECTION RESULT
    # ==========================================================

    def _rejected_result(
        self,
        *,
        symbol: str,
        stock_name: str,
        sector: str,
        timeframe: str,
        reasons: list[str],
        technical: dict[str, Any] | None = None,
        fundamental: dict[str, Any] | None = None,
        pattern: dict[str, Any] | None = None,
        sector_analysis: dict[str, Any] | None = None,
        probability: dict[str, Any] | None = None,
        current_price: float | None = None,
    ) -> dict[str, Any]:
        result = ResearchResult(
            symbol=symbol,
            stock_name=stock_name,
            sector=sector,
            timeframe=timeframe,
            signal="NO TRADE",
            move_up_probability=normalize_score(
                (
                    probability or {}
                ).get(
                    "move_up_probability"
                )
            ),
            overall_score=normalize_score(
                (
                    probability or {}
                ).get("overall_score")
            ),
            current_price=round_price(
                current_price
            ),
            entry_price=None,
            stop_loss=None,
            target_price=None,
            holding_period=get_holding_period(
                timeframe
            ),
            risk_reward=None,
            expected_return=None,
            technical=technical or {},
            fundamental=fundamental or {},
            pattern=pattern or {},
            sector_analysis=(
                sector_analysis or {}
            ),
            probability=probability or {},
            rejection_reasons=list(
                dict.fromkeys(
                    [
                        clean_text(reason)
                        for reason in reasons
                        if clean_text(reason)
                    ]
                )
            ),
            validation_errors=[],
            verified=False,
            generated_at=utc_now().isoformat(),
        )

        return result.to_dict()

    # ==========================================================
    # COMPLETE STOCK RESEARCH
    # ==========================================================

    def research_stock(
        self,
        *,
        access_token: str,
        symbol: str,
        timeframe: str = "3_month",
        benchmark_candles: (
            Iterable[dict[str, Any]]
            | None
        ) = None,
        sector_candles: (
            Iterable[dict[str, Any]]
            | None
        ) = None,
        force_refresh: bool = False,
        include_no_trade: bool = True,
    ) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(
            symbol
        )

        normalized_timeframe = (
            normalize_timeframe(
                timeframe
            )
        )

        if not normalized_symbol:
            raise ValueError(
                "A valid stock symbol is required."
            )

        stock_name, sector = (
            self._stock_information(
                normalized_symbol
            )
        )

        technical_result: dict[
            str,
            Any,
        ] = {}

        fundamental_result: dict[
            str,
            Any,
        ] = {}

        pattern_result: dict[
            str,
            Any,
        ] = {}

        sector_result: dict[
            str,
            Any,
        ] = {}

        probability_result: dict[
            str,
            Any,
        ] = {}

        rejection_reasons: list[str] = []

        current_price: float | None = None

        with self._scan_lock:
            try:
                market_data = (
                    self.market_data_service
                    .get_stock_market_data(
                        access_token,
                        normalized_symbol,
                        timeframe=(
                            normalized_timeframe
                        ),
                        force_refresh=(
                            force_refresh
                        ),
                    )
                )

                candles = market_data.get(
                    "candles"
                )

                quote = market_data.get(
                    "quote"
                )

                if not isinstance(
                    candles,
                    list,
                ) or not candles:
                    raise (
                        ResearchDataUnavailableError(
                            (
                                "Verified historical "
                                "candles are unavailable."
                            )
                        )
                    )

                if not isinstance(
                    quote,
                    dict,
                ):
                    raise (
                        ResearchDataUnavailableError(
                            (
                                "Verified live quote "
                                "is unavailable."
                            )
                        )
                    )

                current_price = safe_float(
                    quote.get(
                        "current_price"
                    )
                )

                if (
                    current_price is None
                    or current_price <= 0
                ):
                    raise (
                        ResearchDataUnavailableError(
                            (
                                "Current market price "
                                "is invalid."
                            )
                        )
                    )

                technical_result = (
                    self.technical_scanner.scan(
                        normalized_symbol,
                        candles,
                        timeframe=(
                            normalized_timeframe
                        ),
                        benchmark_candles=(
                            benchmark_candles
                        ),
                    )
                )

                pattern_result = (
                    self.pattern_scanner.scan(
                        normalized_symbol,
                        candles,
                        timeframe=(
                            normalized_timeframe
                        ),
                    )
                )

                try:
                    fundamentals = (
                        self.fundamental_service
                        .get_fundamentals(
                            normalized_symbol,
                            timeframe=(
                                normalized_timeframe
                            ),
                            force_refresh=(
                                force_refresh
                            ),
                        )
                    )

                    fundamental_result = (
                        self.fundamental_scanner
                        .scan(
                            normalized_symbol,
                            fundamentals,
                            timeframe=(
                                normalized_timeframe
                            ),
                        )
                    )

                except FundamentalDataError as exception:
                    rejection_reasons.append(
                        str(exception)
                    )

                    fundamental_result = {}

                if (
                    sector_candles is not None
                    and benchmark_candles
                    is not None
                ):
                    try:
                        sector_result = (
                            self.sector_scanner.scan(
                                symbol=(
                                    normalized_symbol
                                ),
                                sector=sector,
                                stock_candles=(
                                    candles
                                ),
                                sector_candles=(
                                    sector_candles
                                ),
                                nifty_candles=(
                                    benchmark_candles
                                ),
                                timeframe=(
                                    normalized_timeframe
                                ),
                            )
                        )

                    except SectorScannerError as exception:
                        rejection_reasons.append(
                            str(exception)
                        )

                        sector_result = {}

                else:
                    rejection_reasons.append(
                        (
                            "Verified sector benchmark "
                            "history is unavailable."
                        )
                    )

                probability_result = (
                    self.probability_engine
                    .calculate(
                        timeframe=(
                            normalized_timeframe
                        ),
                        technical_result=(
                            technical_result
                        ),
                        fundamental_result=(
                            fundamental_result
                        ),
                        pattern_result=(
                            pattern_result
                        ),
                        sector_result=(
                            sector_result
                        ),
                    )
                )

                probability_rejections = (
                    probability_result.get(
                        "rejection_reasons"
                    )
                )

                if isinstance(
                    probability_rejections,
                    list,
                ):
                    rejection_reasons.extend(
                        str(reason)
                        for reason in (
                            probability_rejections
                        )
                        if clean_text(reason)
                    )

                signal = normalize_signal(
                    probability_result.get(
                        "signal"
                    )
                )

                if not is_buy_signal(signal):
                    if include_no_trade:
                        return (
                            self._rejected_result(
                                symbol=(
                                    normalized_symbol
                                ),
                                stock_name=(
                                    stock_name
                                ),
                                sector=sector,
                                timeframe=(
                                    normalized_timeframe
                                ),
                                reasons=(
                                    rejection_reasons
                                    or [
                                        (
                                            "Stock did not "
                                            "qualify for BUY."
                                        )
                                    ]
                                ),
                                technical=(
                                    technical_result
                                ),
                                fundamental=(
                                    fundamental_result
                                ),
                                pattern=(
                                    pattern_result
                                ),
                                sector_analysis=(
                                    sector_result
                                ),
                                probability=(
                                    probability_result
                                ),
                                current_price=(
                                    current_price
                                ),
                            )
                        )

                    raise (
                        ResearchSignalRejectedError(
                            (
                                "Stock did not qualify "
                                "for BUY."
                            )
                        )
                    )

                trade_levels = (
                    self._calculate_trade_levels(
                        current_price=(
                            current_price
                        ),
                        candles=candles,
                        timeframe=(
                            normalized_timeframe
                        ),
                        technical_result=(
                            technical_result
                        ),
                        pattern_result=(
                            pattern_result
                        ),
                    )
                )

                details = {
                    "technical": (
                        technical_result
                    ),
                    "fundamental": (
                        fundamental_result
                    ),
                    "pattern": (
                        pattern_result
                    ),
                    "sector_analysis": (
                        sector_result
                    ),
                    "probability": (
                        probability_result
                    ),
                    "trade_levels": (
                        trade_levels.to_dict()
                    ),
                    "data_source": {
                        "market_data": "FYERS",
                        "fundamental_data": (
                            "Financial Modeling Prep"
                        ),
                    },
                }

                final_result = build_stock_result(
                    company_name=stock_name,
                    sector=sector,
                    current_price=(
                        trade_levels.current_price
                    ),
                    entry_price=(
                        trade_levels.entry_price
                    ),
                    stop_loss=(
                        trade_levels.stop_loss
                    ),
                    target_price=(
                        trade_levels.target_price
                    ),
                    move_up_probability=(
                        probability_result.get(
                            "move_up_probability"
                        )
                    ),
                    timeframe=(
                        normalized_timeframe
                    ),
                    signal=signal,
                    overall_score=(
                        probability_result.get(
                            "overall_score"
                        )
                    ),
                    symbol=normalized_symbol,
                    updated_at=utc_now(),
                    details=details,
                )

                final_result[
                    "technical"
                ] = technical_result

                final_result[
                    "fundamental"
                ] = fundamental_result

                final_result[
                    "pattern"
                ] = pattern_result

                final_result[
                    "sector_analysis"
                ] = sector_result

                final_result[
                    "probability"
                ] = probability_result

                final_result[
                    "verified"
                ] = True

                final_result[
                    "generated_at"
                ] = utc_now().isoformat()

                validation = validate_scan_result(
                    final_result,
                    require_buy_signal=True,
                    require_fresh=True,
                )

                if not validation.is_valid:
                    if include_no_trade:
                        return (
                            self._rejected_result(
                                symbol=(
                                    normalized_symbol
                                ),
                                stock_name=(
                                    stock_name
                                ),
                                sector=sector,
                                timeframe=(
                                    normalized_timeframe
                                ),
                                reasons=(
                                    validation.errors
                                ),
                                technical=(
                                    technical_result
                                ),
                                fundamental=(
                                    fundamental_result
                                ),
                                pattern=(
                                    pattern_result
                                ),
                                sector_analysis=(
                                    sector_result
                                ),
                                probability=(
                                    probability_result
                                ),
                                current_price=(
                                    current_price
                                ),
                            )
                        )

                    raise (
                        ResearchSignalRejectedError(
                            "; ".join(
                                validation.errors
                            )
                        )
                    )

                logger.info(
                    (
                        "Research completed for %s "
                        "with signal=%s."
                    ),
                    normalized_symbol,
                    signal,
                    extra=build_log_extra(
                        component=(
                            "research_engine"
                        ),
                        symbol=(
                            normalized_symbol
                        ),
                        timeframe=(
                            normalized_timeframe
                        ),
                        event=(
                            "research_completed"
                        ),
                        status="success",
                        signal=signal,
                        probability=(
                            probability_result.get(
                                "move_up_probability"
                            )
                        ),
                    ),
                )

                return validation.cleaned_data

            except (
                MarketDataError,
                TechnicalScannerError,
                PatternScannerError,
                ProbabilityEngineError,
                ResearchEngineError,
            ) as exception:
                if include_no_trade:
                    return self._rejected_result(
                        symbol=normalized_symbol,
                        stock_name=stock_name,
                        sector=sector,
                        timeframe=(
                            normalized_timeframe
                        ),
                        reasons=[
                            str(exception)
                        ],
                        technical=(
                            technical_result
                        ),
                        fundamental=(
                            fundamental_result
                        ),
                        pattern=(
                            pattern_result
                        ),
                        sector_analysis=(
                            sector_result
                        ),
                        probability=(
                            probability_result
                        ),
                        current_price=(
                            current_price
                        ),
                    )

                raise

            except Exception as exception:
                log_exception(
                    logger,
                    "Stock research failed",
                    exception=exception,
                    symbol=normalized_symbol,
                    timeframe=(
                        normalized_timeframe
                    ),
                    component=(
                        "research_engine"
                    ),
                    error_code=(
                        "RESEARCH_FAILED"
                    ),
                )

                if include_no_trade:
                    return self._rejected_result(
                        symbol=normalized_symbol,
                        stock_name=stock_name,
                        sector=sector,
                        timeframe=(
                            normalized_timeframe
                        ),
                        reasons=[
                            (
                                f"{type(exception).__name__}: "
                                f"{str(exception) or 'Verified stock research could not be completed.'}"
                            )
                        ],
                        technical=(
                            technical_result
                        ),
                        fundamental=(
                            fundamental_result
                        ),
                        pattern=(
                            pattern_result
                        ),
                        sector_analysis=(
                            sector_result
                        ),
                        probability=(
                            probability_result
                        ),
                        current_price=(
                            current_price
                        ),
                    )

                raise ResearchEngineError(
                    (
                        "Research failed for "
                        f"{normalized_symbol}."
                    )
                ) from exception

    # ==========================================================
    # BULK RESEARCH
    # ==========================================================

    def research_stocks(
        self,
        *,
        access_token: str,
        symbols: Iterable[str],
        timeframe: str = "3_month",
        benchmark_candles: (
            Iterable[dict[str, Any]]
            | None
        ) = None,
        sector_candles_map: (
            dict[str, Iterable[
                dict[str, Any]
            ]]
            | None
        ) = None,
        force_refresh: bool = False,
        include_no_trade: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized_timeframe = (
            normalize_timeframe(
                timeframe
            )
        )

        results: list[dict[str, Any]] = []

        processed_symbols: set[str] = set()

        for raw_symbol in symbols:
            symbol = normalize_symbol(
                raw_symbol
            )

            if (
                not symbol
                or symbol in processed_symbols
            ):
                continue

            processed_symbols.add(symbol)

            _, sector = self._stock_information(
                symbol
            )

            sector_candles = None

            if isinstance(
                sector_candles_map,
                dict,
            ):
                sector_candles = (
                    sector_candles_map.get(
                        sector
                    )
                )

            result = self.research_stock(
                access_token=access_token,
                symbol=symbol,
                timeframe=(
                    normalized_timeframe
                ),
                benchmark_candles=(
                    benchmark_candles
                ),
                sector_candles=(
                    sector_candles
                ),
                force_refresh=(
                    force_refresh
                ),
                include_no_trade=True,
            )

            if (
                include_no_trade
                or is_buy_signal(
                    result.get("signal")
                )
            ):
                results.append(result)

            if (
                limit is not None
                and len(results)
                >= max(1, int(limit))
            ):
                break

        if include_no_trade:
            return results

        return sort_scan_results(
            [
                result
                for result in results
                if is_buy_signal(
                    result.get("signal")
                )
            ]
        )


_global_research_engine: (
    ResearchEngine | None
) = None

_global_research_lock = (
    threading.Lock()
)


def get_research_engine() -> ResearchEngine:
    global _global_research_engine

    if _global_research_engine is not None:
        return _global_research_engine

    with _global_research_lock:
        if _global_research_engine is None:
            _global_research_engine = (
                ResearchEngine()
            )

    return _global_research_engine
