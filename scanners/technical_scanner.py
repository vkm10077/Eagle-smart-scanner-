from __future__ import annotations

"""
Eagle Smart Scanner - Technical Scanner

Deep technical scanner for Intraday / BTST / Swing.

Responsibilities
----------------
- Fetch mode-specific primary / confirmation / higher-timeframe real FYERS data
- Calculate standardized technical metrics
- Apply mandatory mode-specific gates
- Calculate weighted 0-100 technical score
- Count confirmations
- Calculate Entry / Stop Loss / Target / Risk-Reward
- Return technical BUY / STRONG BUY eligibility

Important
---------
Pattern scoring is intentionally supplied as optional inputs so that the
dedicated pattern_scanner.py can be integrated without duplicating pattern
logic here.

No fundamentals.
No NIFTY500 dependency.
No fake/random fallback data.
"""

import math
import threading
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from config import Config
from services.market_data_service import (
    MarketDataService,
    get_market_data_service,
)
from services.technical_metrics_service import (
    TechnicalMetrics,
    TechnicalMetricsService,
    get_technical_metrics_service,
)


class TechnicalScannerError(RuntimeError):
    """Technical scanner error."""


@dataclass(frozen=True)
class PatternConfirmation:
    chart_pattern_bullish: bool = False
    chart_pattern_score: float = 0.0
    chart_pattern_name: str = ""

    candle_pattern_bullish: bool = False
    candle_pattern_score: float = 0.0
    candle_pattern_name: str = ""


@dataclass(frozen=True)
class TechnicalScanResult:
    symbol: str
    fyers_symbol: str
    mode: str

    current_price: float
    entry_price: float
    stop_loss: float
    target: float
    risk_reward: float
    stop_loss_percent: float

    score: float
    confirmations: int
    minimum_confirmations: int

    signal: str
    eligible: bool

    primary_resolution: str
    confirmation_resolution: str
    higher_resolution: str

    primary: TechnicalMetrics
    confirmation: TechnicalMetrics
    higher: TechnicalMetrics

    chart_pattern_bullish: bool
    chart_pattern_name: str
    candle_pattern_bullish: bool
    candle_pattern_name: str

    mandatory_passed: bool
    failed_rules: tuple[str, ...]
    confirmations_detail: tuple[str, ...]
    reasons: tuple[str, ...]


class TechnicalScanner:
    """
    Final pure-technical decision engine before pattern/orchestrator integration.
    """

    def __init__(
        self,
        market_data: MarketDataService | None = None,
        metrics_service: TechnicalMetricsService | None = None,
    ) -> None:
        self.market_data = market_data or get_market_data_service()
        self.metrics_service = (
            metrics_service
            or get_technical_metrics_service()
        )

        self._lock = threading.RLock()
        self._last_results: dict[
            tuple[str, str],
            TechnicalScanResult,
        ] = {}

    # ========================================================
    # PUBLIC SCAN
    # ========================================================

    def scan(
        self,
        symbol: str,
        *,
        mode: str | None = None,
        benchmark_symbol: str = "NSE:NIFTY50-INDEX",
        pattern_confirmation: PatternConfirmation | None = None,
    ) -> TechnicalScanResult:
        mode = Config.normalize_trading_mode(mode)
        pattern = pattern_confirmation or PatternConfirmation()

        fyers_symbol = self._normalize_fyers_symbol(symbol)

        primary_resolution = Config.get_primary_resolution(mode)
        confirmation_resolution = Config.get_confirmation_resolution(mode)
        higher_resolution = Config.get_higher_timeframe_resolution(mode)

        primary_df = self._get_mode_dataframe(
            fyers_symbol,
            mode=mode,
            role="primary",
            resolution=primary_resolution,
        )

        confirmation_df = self._get_mode_dataframe(
            fyers_symbol,
            mode=mode,
            role="confirmation",
            resolution=confirmation_resolution,
        )

        higher_df = self._get_mode_dataframe(
            fyers_symbol,
            mode=mode,
            role="higher",
            resolution=higher_resolution,
        )

        benchmark_primary = self._get_benchmark_dataframe(
            benchmark_symbol,
            mode=mode,
            role="primary",
            resolution=primary_resolution,
        )

        benchmark_confirmation = self._get_benchmark_dataframe(
            benchmark_symbol,
            mode=mode,
            role="confirmation",
            resolution=confirmation_resolution,
        )

        benchmark_higher = self._get_benchmark_dataframe(
            benchmark_symbol,
            mode=mode,
            role="higher",
            resolution=higher_resolution,
        )

        primary = self.metrics_service.calculate(
            primary_df,
            mode=mode,
            benchmark_df=benchmark_primary,
        )

        confirmation = self.metrics_service.calculate(
            confirmation_df,
            mode=mode,
            benchmark_df=benchmark_confirmation,
        )

        higher = self.metrics_service.calculate(
            higher_df,
            mode=mode,
            benchmark_df=benchmark_higher,
        )

        live_quote = self.market_data.get_quote(
            fyers_symbol,
            prefer_websocket=True,
        )

        current_price = float(live_quote.ltp)

        if current_price <= 0:
            raise TechnicalScannerError(
                f"Invalid live price for {fyers_symbol}"
            )

        entry, stop_loss, target, rr, sl_pct = (
            self._calculate_trade_levels(
                current_price=current_price,
                metrics=primary,
                mode=mode,
            )
        )

        confirmations_detail = self._collect_confirmations(
            primary=primary,
            confirmation=confirmation,
            higher=higher,
            mode=mode,
            pattern=pattern,
        )

        confirmations = len(confirmations_detail)

        failed_rules = self._mandatory_failures(
            primary=primary,
            confirmation=confirmation,
            higher=higher,
            mode=mode,
            risk_reward=rr,
            stop_loss_percent=sl_pct,
        )

        mandatory_passed = not failed_rules

        score, score_reasons = self._calculate_score(
            primary=primary,
            confirmation=confirmation,
            higher=higher,
            mode=mode,
            pattern=pattern,
        )

        minimum_confirmations = Config.get_min_confirmations(mode)

        eligible = (
            mandatory_passed
            and confirmations >= minimum_confirmations
            and score >= Config.BUY_MIN_SCORE
            and rr >= Config.MIN_RISK_REWARD
        )

        signal = ""

        if eligible:
            if (
                score >= Config.STRONG_BUY_MIN_SCORE
                and confirmations >= minimum_confirmations
            ):
                signal = "STRONG BUY"
            else:
                signal = "BUY"

        reasons = list(score_reasons)

        if signal:
            reasons.append(
                f"{signal}: technical score {score:.2f}, "
                f"{confirmations} confirmations"
            )
        else:
            reasons.append(
                "No BUY signal: final technical conditions not satisfied"
            )

        result = TechnicalScanResult(
            symbol=self._plain_symbol(fyers_symbol),
            fyers_symbol=fyers_symbol,
            mode=mode,
            current_price=round(current_price, 2),
            entry_price=round(entry, 2),
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_reward=round(rr, 2),
            stop_loss_percent=round(sl_pct, 2),
            score=round(score, 2),
            confirmations=confirmations,
            minimum_confirmations=minimum_confirmations,
            signal=signal,
            eligible=eligible,
            primary_resolution=primary_resolution,
            confirmation_resolution=confirmation_resolution,
            higher_resolution=higher_resolution,
            primary=primary,
            confirmation=confirmation,
            higher=higher,
            chart_pattern_bullish=pattern.chart_pattern_bullish,
            chart_pattern_name=pattern.chart_pattern_name,
            candle_pattern_bullish=pattern.candle_pattern_bullish,
            candle_pattern_name=pattern.candle_pattern_name,
            mandatory_passed=mandatory_passed,
            failed_rules=tuple(failed_rules),
            confirmations_detail=tuple(confirmations_detail),
            reasons=tuple(reasons),
        )

        with self._lock:
            self._last_results[
                (fyers_symbol, mode)
            ] = result

        return result

    # ========================================================
    # DATA
    # ========================================================

    def _get_mode_dataframe(
        self,
        symbol: str,
        *,
        mode: str,
        role: str,
        resolution: str,
    ) -> pd.DataFrame:
        if resolution == "weekly_from_daily":
            daily = self.market_data.get_dataframe(
                symbol=symbol,
                resolution="D",
                candle_count=max(
                    Config.SWING_HISTORY_CANDLES,
                    320,
                ),
                min_required=Config.MIN_REQUIRED_CANDLES_SWING,
            )
            return self._weekly_from_daily(daily)

        candle_count = self._history_candles(mode)

        # EMA200 requires enough bars on every calculated timeframe.
        min_required = max(
            Config.EMA_LONG + 5,
            Config.get_min_required_candles(mode),
        )

        return self.market_data.get_dataframe(
            symbol=symbol,
            resolution=resolution,
            candle_count=candle_count,
            min_required=min_required,
        )

    def _get_benchmark_dataframe(
        self,
        symbol: str,
        *,
        mode: str,
        role: str,
        resolution: str,
    ) -> pd.DataFrame:
        return self._get_mode_dataframe(
            symbol,
            mode=mode,
            role=role,
            resolution=resolution,
        )

    @staticmethod
    def _history_candles(mode: str) -> int:
        if mode == Config.MODE_INTRADAY:
            return max(
                Config.INTRADAY_HISTORY_CANDLES,
                Config.EMA_LONG + 20,
            )

        if mode == Config.MODE_BTST:
            return max(
                Config.BTST_HISTORY_CANDLES,
                Config.EMA_LONG + 20,
            )

        return max(
            Config.SWING_HISTORY_CANDLES,
            Config.EMA_LONG + 20,
        )

    @staticmethod
    def _weekly_from_daily(
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        data = df.copy()

        if "datetime" not in data.columns:
            raise TechnicalScannerError(
                "Weekly derivation requires datetime column"
            )

        data["datetime"] = pd.to_datetime(
            data["datetime"]
        )

        data = data.set_index("datetime")

        weekly = data.resample(
            "W-FRI"
        ).agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        ).dropna()

        weekly = weekly.reset_index()

        if len(weekly) < Config.EMA_LONG + 5:
            raise TechnicalScannerError(
                f"Insufficient weekly candles: {len(weekly)}"
            )

        return weekly

    # ========================================================
    # MANDATORY RULES
    # ========================================================

    def _mandatory_failures(
        self,
        *,
        primary: TechnicalMetrics,
        confirmation: TechnicalMetrics,
        higher: TechnicalMetrics,
        mode: str,
        risk_reward: float,
        stop_loss_percent: float,
    ) -> list[str]:
        failed: list[str] = []

        if (
            Config.REQUIRE_BULLISH_EMA_STRUCTURE
            and not primary.bullish_ema_structure
        ):
            failed.append("Primary bullish EMA structure failed")

        if (
            Config.REQUIRE_SUPERTREND_BUY
            and not primary.supertrend_buy
        ):
            failed.append("Primary Supertrend BUY failed")

        rsi_min, rsi_max = Config.get_rsi_range(mode)

        if (
            Config.REQUIRE_VALID_RSI
            and not (rsi_min <= primary.rsi <= rsi_max)
        ):
            failed.append(
                f"RSI outside {rsi_min:.0f}-{rsi_max:.0f}"
            )

        if primary.adx < Config.get_min_adx(mode):
            failed.append("ADX below minimum")

        if (
            Config.REQUIRE_POSITIVE_RISK_REWARD
            and risk_reward < Config.MIN_RISK_REWARD
        ):
            failed.append("Risk-reward below minimum")

        if (
            stop_loss_percent
            > Config.get_max_stop_loss_percent(mode)
        ):
            failed.append("Stop-loss exceeds mode maximum")

        if mode == Config.MODE_INTRADAY:
            if (
                Config.INTRADAY_REQUIRE_MACD_BULLISH
                and not primary.macd_bullish
            ):
                failed.append("Intraday MACD bullish failed")

            if (
                Config.INTRADAY_REQUIRE_VOLUME_CONFIRMATION
                and primary.volume_ratio
                < Config.get_min_volume_ratio(mode)
            ):
                failed.append("Intraday volume confirmation failed")

            if (
                Config.INTRADAY_REQUIRE_ABOVE_VWAP
                and not primary.above_vwap
            ):
                failed.append("Intraday price below VWAP")

        elif mode == Config.MODE_BTST:
            if (
                Config.BTST_REQUIRE_MACD_BULLISH
                and not primary.macd_bullish
            ):
                failed.append("BTST MACD bullish failed")

            if (
                Config.BTST_REQUIRE_VOLUME_CONFIRMATION
                and primary.volume_ratio
                < Config.get_min_volume_ratio(mode)
            ):
                failed.append("BTST volume confirmation failed")

            if (
                Config.BTST_REQUIRE_PRICE_ABOVE_EMA20
                and primary.price <= primary.ema20
            ):
                failed.append("BTST price below EMA20")

            if (
                Config.BTST_REQUIRE_PRICE_ABOVE_EMA50
                and primary.price <= primary.ema50
            ):
                failed.append("BTST price below EMA50")

            if (
                Config.BTST_REQUIRE_ABOVE_VWAP
                and not primary.above_vwap
            ):
                failed.append("BTST price below VWAP")

            if (
                Config.BTST_REQUIRE_DAILY_BULLISH_CONFIRMATION
                and not higher.bullish_ema_structure
            ):
                failed.append("BTST daily bullish confirmation failed")

        else:
            if (
                Config.SWING_REQUIRE_PRICE_ABOVE_EMA20
                and primary.price <= primary.ema20
            ):
                failed.append("Swing price below EMA20")

            if (
                Config.SWING_REQUIRE_PRICE_ABOVE_EMA50
                and primary.price <= primary.ema50
            ):
                failed.append("Swing price below EMA50")

        # Multi-timeframe confirmation is mandatory for all modes.
        if not confirmation.supertrend_buy:
            failed.append("Confirmation timeframe Supertrend failed")

        if not higher.supertrend_buy:
            failed.append("Higher timeframe Supertrend failed")

        if not confirmation.bullish_ema_structure:
            failed.append("Confirmation timeframe EMA trend failed")

        if not higher.bullish_ema_structure:
            failed.append("Higher timeframe EMA trend failed")

        return failed

    # ========================================================
    # CONFIRMATIONS
    # ========================================================

    def _collect_confirmations(
        self,
        *,
        primary: TechnicalMetrics,
        confirmation: TechnicalMetrics,
        higher: TechnicalMetrics,
        mode: str,
        pattern: PatternConfirmation,
    ) -> list[str]:
        confirmations: list[str] = []

        rsi_min, rsi_max = Config.get_rsi_range(mode)

        checks = [
            (
                primary.bullish_ema_structure,
                "Bullish EMA structure",
            ),
            (
                rsi_min <= primary.rsi <= rsi_max,
                "RSI bullish range",
            ),
            (
                primary.macd_bullish,
                "MACD bullish",
            ),
            (
                primary.supertrend_buy,
                "Supertrend BUY",
            ),
            (
                primary.adx >= Config.get_min_adx(mode)
                and primary.plus_di > primary.minus_di,
                "ADX/+DI trend strength",
            ),
            (
                primary.volume_ratio
                >= Config.get_min_volume_ratio(mode),
                "Volume confirmation",
            ),
            (
                primary.breakout_confirmed,
                "Breakout confirmed",
            ),
            (
                primary.bullish_price_action,
                "Bullish price action",
            ),
            (
                primary.relative_strength_percent
                > Config.MIN_RELATIVE_STRENGTH_PCT,
                "Positive relative strength",
            ),
            (
                confirmation.bullish_ema_structure
                and confirmation.supertrend_buy,
                "Confirmation timeframe bullish",
            ),
            (
                higher.bullish_ema_structure
                and higher.supertrend_buy,
                "Higher timeframe bullish",
            ),
            (
                pattern.chart_pattern_bullish,
                "Bullish chart pattern",
            ),
            (
                pattern.candle_pattern_bullish,
                "Bullish candlestick pattern",
            ),
        ]

        if mode in {
            Config.MODE_INTRADAY,
            Config.MODE_BTST,
        }:
            checks.append(
                (
                    primary.above_vwap,
                    "Price above VWAP",
                )
            )

        for passed, label in checks:
            if passed:
                confirmations.append(label)

        return confirmations

    # ========================================================
    # WEIGHTED SCORE
    # ========================================================

    def _calculate_score(
        self,
        *,
        primary: TechnicalMetrics,
        confirmation: TechnicalMetrics,
        higher: TechnicalMetrics,
        mode: str,
        pattern: PatternConfirmation,
    ) -> tuple[float, list[str]]:
        if mode == Config.MODE_INTRADAY:
            weights = {
                "trend": Config.INTRADAY_WEIGHT_TREND,
                "rsi": Config.INTRADAY_WEIGHT_RSI,
                "macd": Config.INTRADAY_WEIGHT_MACD,
                "supertrend": Config.INTRADAY_WEIGHT_SUPERTREND,
                "vwap": Config.INTRADAY_WEIGHT_VWAP,
                "volume": Config.INTRADAY_WEIGHT_VOLUME,
                "breakout": Config.INTRADAY_WEIGHT_BREAKOUT,
                "price_action": Config.INTRADAY_WEIGHT_PRICE_ACTION,
                "relative_strength": Config.INTRADAY_WEIGHT_RELATIVE_STRENGTH,
                "patterns": Config.INTRADAY_WEIGHT_PATTERNS,
            }
        elif mode == Config.MODE_BTST:
            weights = {
                "trend": Config.BTST_WEIGHT_TREND,
                "rsi": Config.BTST_WEIGHT_RSI,
                "macd": Config.BTST_WEIGHT_MACD,
                "supertrend": Config.BTST_WEIGHT_SUPERTREND,
                "vwap": Config.BTST_WEIGHT_VWAP,
                "volume": Config.BTST_WEIGHT_VOLUME,
                "breakout": Config.BTST_WEIGHT_BREAKOUT,
                "price_action": Config.BTST_WEIGHT_PRICE_ACTION,
                "relative_strength": Config.BTST_WEIGHT_RELATIVE_STRENGTH,
                "patterns": Config.BTST_WEIGHT_PATTERNS,
                "closing_strength": Config.BTST_WEIGHT_CLOSING_STRENGTH,
            }
        else:
            weights = {
                "trend": Config.SWING_WEIGHT_TREND,
                "rsi": Config.SWING_WEIGHT_RSI,
                "macd": Config.SWING_WEIGHT_MACD,
                "supertrend": Config.SWING_WEIGHT_SUPERTREND,
                "volume": Config.SWING_WEIGHT_VOLUME,
                "breakout": Config.SWING_WEIGHT_BREAKOUT,
                "price_action": Config.SWING_WEIGHT_PRICE_ACTION,
                "relative_strength": Config.SWING_WEIGHT_RELATIVE_STRENGTH,
                "chart_pattern": Config.SWING_WEIGHT_CHART_PATTERN,
                "candle_pattern": Config.SWING_WEIGHT_CANDLE_PATTERN,
            }

        score = 0.0
        reasons: list[str] = []

        def add(condition: bool, key: str, reason: str) -> None:
            nonlocal score
            if condition:
                score += float(weights.get(key, 0.0))
                reasons.append(reason)

        rsi_min, rsi_max = Config.get_rsi_range(mode)

        add(
            primary.bullish_ema_structure,
            "trend",
            "Bullish EMA trend",
        )
        add(
            rsi_min <= primary.rsi <= rsi_max,
            "rsi",
            "RSI in bullish range",
        )
        add(
            primary.macd_bullish,
            "macd",
            "MACD bullish",
        )
        add(
            primary.supertrend_buy,
            "supertrend",
            "Supertrend BUY",
        )
        add(
            primary.volume_ratio >= Config.get_min_volume_ratio(mode),
            "volume",
            "Volume confirmed",
        )
        add(
            primary.breakout_confirmed,
            "breakout",
            "Breakout confirmed",
        )
        add(
            primary.bullish_price_action,
            "price_action",
            "Bullish price action",
        )
        add(
            primary.relative_strength_percent
            > Config.MIN_RELATIVE_STRENGTH_PCT,
            "relative_strength",
            "Positive relative strength",
        )

        if "vwap" in weights:
            add(
                primary.above_vwap,
                "vwap",
                "Price above VWAP",
            )

        if mode == Config.MODE_INTRADAY:
            pattern_ok = (
                pattern.chart_pattern_bullish
                or pattern.candle_pattern_bullish
            )
            add(
                pattern_ok,
                "patterns",
                "Bullish pattern confirmation",
            )

        elif mode == Config.MODE_BTST:
            pattern_ok = (
                pattern.chart_pattern_bullish
                or pattern.candle_pattern_bullish
            )
            add(
                pattern_ok,
                "patterns",
                "Bullish pattern confirmation",
            )

            # Primary BTST candles are 15-minute. Last candle's close
            # position acts as intraday closing-strength proxy.
            close_strength = self._btst_closing_strength(primary)
            add(
                close_strength,
                "closing_strength",
                "BTST closing strength",
            )

        else:
            add(
                pattern.chart_pattern_bullish,
                "chart_pattern",
                "Bullish chart pattern",
            )
            add(
                pattern.candle_pattern_bullish,
                "candle_pattern",
                "Bullish candlestick pattern",
            )

        # MTF confirmation is a gate, not an extra score weight.
        if (
            confirmation.bullish_ema_structure
            and confirmation.supertrend_buy
            and higher.bullish_ema_structure
            and higher.supertrend_buy
        ):
            reasons.append("Multi-timeframe bullish confirmation")

        return (
            round(min(max(score, 0.0), 100.0), 2),
            reasons,
        )

    @staticmethod
    def _btst_closing_strength(
        primary: TechnicalMetrics,
    ) -> bool:
        # TechnicalMetrics does not expose current candle H/L separately.
        # Use breakout/near-high + positive trend as the stable proxy here.
        return (
            primary.supertrend_buy
            and primary.price > primary.ema20
            and primary.distance_from_recent_high_percent
            <= Config.BTST_MAX_DISTANCE_FROM_DAY_HIGH_PERCENT
        )

    # ========================================================
    # ENTRY / SL / TARGET
    # ========================================================

    def _calculate_trade_levels(
        self,
        *,
        current_price: float,
        metrics: TechnicalMetrics,
        mode: str,
    ) -> tuple[float, float, float, float, float]:
        entry_buffer = (
            Config.get_entry_buffer_percent(mode)
            / 100.0
        )

        entry = current_price * (
            1.0 + entry_buffer
        )

        atr = float(metrics.atr)

        if atr <= 0 or not math.isfinite(atr):
            raise TechnicalScannerError(
                "ATR unavailable; trade levels cannot be generated"
            )

        sl_atr = (
            Config.get_stop_loss_atr_multiplier(mode)
        )

        target_atr = (
            Config.get_target_atr_multiplier(mode)
        )

        raw_stop = entry - (atr * sl_atr)

        # Technical support guard: do not put bullish stop above entry.
        support_candidates = [
            value
            for value in (
                metrics.supertrend,
                metrics.ema20,
            )
            if 0 < value < entry
        ]

        if support_candidates:
            technical_support = max(support_candidates)

            # Keep a small ATR breathing room below support.
            support_stop = technical_support - (0.15 * atr)

            # Use the tighter valid stop only when it remains below entry.
            if 0 < support_stop < entry:
                raw_stop = max(
                    raw_stop,
                    support_stop,
                )

        max_sl_pct = (
            Config.get_max_stop_loss_percent(mode)
            / 100.0
        )

        maximum_allowed_stop = (
            entry * (1.0 - max_sl_pct)
        )

        stop_loss = max(
            raw_stop,
            maximum_allowed_stop,
        )

        risk = entry - stop_loss

        if risk <= 0:
            raise TechnicalScannerError(
                "Invalid stop-loss/risk calculation"
            )

        atr_target = entry + (
            atr * target_atr
        )

        rr_target = entry + (
            risk * Config.MIN_RISK_REWARD
        )

        target = max(
            atr_target,
            rr_target,
        )

        reward = target - entry

        risk_reward = (
            reward / risk
            if risk > 0
            else 0.0
        )

        sl_pct = (
            (risk / entry) * 100.0
            if entry > 0
            else 0.0
        )

        return (
            entry,
            stop_loss,
            target,
            risk_reward,
            sl_pct,
        )

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _normalize_fyers_symbol(
        symbol: str,
    ) -> str:
        value = str(symbol or "").strip().upper()

        if not value:
            raise TechnicalScannerError("Empty symbol")

        if ":" in value:
            return value

        if value.endswith("-EQ"):
            return f"NSE:{value}"

        return f"NSE:{value}-EQ"

    @staticmethod
    def _plain_symbol(
        fyers_symbol: str,
    ) -> str:
        value = fyers_symbol.upper()

        if ":" in value:
            value = value.split(":", 1)[1]

        if value.endswith("-EQ"):
            value = value[:-3]

        return value

    # ========================================================
    # LAST RESULT / SERIALIZATION
    # ========================================================

    def get_last_result(
        self,
        symbol: str,
        mode: str | None = None,
    ) -> TechnicalScanResult | None:
        fyers_symbol = self._normalize_fyers_symbol(symbol)
        normalized_mode = Config.normalize_trading_mode(mode)

        with self._lock:
            return self._last_results.get(
                (fyers_symbol, normalized_mode)
            )

    def scan_as_dict(
        self,
        symbol: str,
        *,
        mode: str | None = None,
        benchmark_symbol: str = "NSE:NIFTY50-INDEX",
        pattern_confirmation: PatternConfirmation | None = None,
    ) -> dict[str, Any]:
        return asdict(
            self.scan(
                symbol,
                mode=mode,
                benchmark_symbol=benchmark_symbol,
                pattern_confirmation=pattern_confirmation,
            )
        )


_default_technical_scanner: TechnicalScanner | None = None
_default_technical_scanner_lock = threading.Lock()


def get_technical_scanner() -> TechnicalScanner:
    global _default_technical_scanner

    if _default_technical_scanner is not None:
        return _default_technical_scanner

    with _default_technical_scanner_lock:
        if _default_technical_scanner is None:
            _default_technical_scanner = TechnicalScanner()

    return _default_technical_scanner


def scan_stock_technical(
    symbol: str,
    *,
    mode: str | None = None,
    benchmark_symbol: str = "NSE:NIFTY50-INDEX",
    pattern_confirmation: PatternConfirmation | None = None,
) -> TechnicalScanResult:
    return get_technical_scanner().scan(
        symbol,
        mode=mode,
        benchmark_symbol=benchmark_symbol,
        pattern_confirmation=pattern_confirmation,
    )
