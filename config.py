from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # =========================================================
    # APP SETTINGS
    # =========================================================
    APP_NAME: str = "Eagle Smart Scanner"
    APP_VERSION: str = "3.0.0"
    SECRET_KEY: str = os.getenv(
        "SECRET_KEY",
        "change-this-secret-key",
    )

    # =========================================================
    # MARKET SETTINGS
    # =========================================================
    MARKET_TIMEZONE: str = "Asia/Kolkata"

    MARKET_OPEN_HOUR: int = 9
    MARKET_OPEN_MINUTE: int = 15

    MARKET_CLOSE_HOUR: int = 15
    MARKET_CLOSE_MINUTE: int = 30

    # =========================================================
    # SCANNER UNIVERSE
    # =========================================================
    TOP_SECTORS_COUNT: int = 10
    TOP_STOCKS_PER_SECTOR: int = 10

    # Maximum:
    # 10 sectors × 10 stocks = 100 stocks
    MAX_SCANNER_UNIVERSE: int = (
        TOP_SECTORS_COUNT
        * TOP_STOCKS_PER_SECTOR
    )

    # =========================================================
    # TRADING MODES
    # =========================================================
    MODE_INTRADAY: str = "intraday"
    MODE_SWING: str = "swing"

    DEFAULT_TRADING_MODE: str = MODE_SWING

    SUPPORTED_TRADING_MODES: tuple[str, ...] = (
        MODE_INTRADAY,
        MODE_SWING,
    )

    # =========================================================
    # INTRADAY TIMEFRAMES
    # =========================================================
    INTRADAY_PRIMARY_RESOLUTION: str = "5"
    INTRADAY_CONFIRMATION_RESOLUTION: str = "15"

    # Daily candle can be used as higher timeframe trend filter
    INTRADAY_HIGHER_TIMEFRAME_RESOLUTION: str = "D"

    INTRADAY_HISTORY_CANDLES: int = 300

    # =========================================================
    # SWING TIMEFRAMES
    # =========================================================
    SWING_PRIMARY_RESOLUTION: str = "D"
    SWING_CONFIRMATION_RESOLUTION: str = "W"

    SWING_HISTORY_CANDLES: int = 320

    SWING_MIN_HOLDING_DAYS: int = 15
    SWING_MAX_HOLDING_DAYS: int = 30

    # =========================================================
    # EMA SETTINGS
    # =========================================================
    EMA_FAST: int = 20
    EMA_MEDIUM: int = 50
    EMA_LONG: int = 200

    # =========================================================
    # RSI SETTINGS
    # =========================================================
    RSI_PERIOD: int = 14

    INTRADAY_RSI_MIN: float = 55.0
    INTRADAY_RSI_MAX: float = 75.0

    SWING_RSI_MIN: float = 55.0
    SWING_RSI_MAX: float = 72.0

    # =========================================================
    # MACD SETTINGS
    # =========================================================
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9

    # =========================================================
    # SUPERTREND SETTINGS
    # =========================================================
    SUPERTREND_PERIOD: int = 10
    SUPERTREND_MULTIPLIER: float = 3.0

    # =========================================================
    # ATR SETTINGS
    # =========================================================
    ATR_PERIOD: int = 14

    INTRADAY_STOP_LOSS_ATR_MULTIPLIER: float = 1.2
    INTRADAY_TARGET_ATR_MULTIPLIER: float = 2.4

    SWING_STOP_LOSS_ATR_MULTIPLIER: float = 1.5
    SWING_TARGET_ATR_MULTIPLIER: float = 3.0

    # =========================================================
    # VOLUME SETTINGS
    # =========================================================
    VOLUME_AVG_PERIOD: int = 20

    INTRADAY_MIN_VOLUME_RATIO: float = 1.30
    SWING_MIN_VOLUME_RATIO: float = 1.20

    STRONG_VOLUME_RATIO: float = 1.50

    # =========================================================
    # VWAP SETTINGS
    # =========================================================
    ENABLE_VWAP: bool = True

    # VWAP has stronger importance for intraday
    INTRADAY_REQUIRE_ABOVE_VWAP: bool = True

    # Swing does not require VWAP as mandatory
    SWING_REQUIRE_ABOVE_VWAP: bool = False

    # =========================================================
    # PRICE ACTION
    # =========================================================
    ENABLE_PRICE_ACTION: bool = True

    REQUIRE_HIGHER_HIGH: bool = False
    REQUIRE_HIGHER_LOW: bool = False

    PRICE_ACTION_LOOKBACK: int = 20

    # =========================================================
    # BREAKOUT SETTINGS
    # =========================================================
    ENABLE_BREAKOUT_ANALYSIS: bool = True

    INTRADAY_BREAKOUT_LOOKBACK: int = 20
    SWING_BREAKOUT_LOOKBACK: int = 50

    BREAKOUT_BUFFER_PERCENT: float = 0.10

    # =========================================================
    # RELATIVE STRENGTH
    # =========================================================
    ENABLE_RELATIVE_STRENGTH: bool = True

    RELATIVE_STRENGTH_LOOKBACK: int = 20

    MIN_RELATIVE_STRENGTH_PCT: float = 0.0

    # =========================================================
    # CHART PATTERNS
    # =========================================================
    ENABLE_CHART_PATTERNS: bool = True

    CHART_PATTERN_LOOKBACK: int = 60

    CHART_PATTERNS: tuple[str, ...] = (
        "ascending_triangle",
        "symmetrical_triangle",
        "falling_wedge",
        "bull_flag",
        "cup_and_handle",
        "double_bottom",
        "inverse_head_and_shoulders",
        "rectangle_breakout",
        "channel_breakout",
        "rounding_bottom",
    )

    BULLISH_CHART_PATTERNS: tuple[str, ...] = (
        "ascending_triangle",
        "falling_wedge",
        "bull_flag",
        "cup_and_handle",
        "double_bottom",
        "inverse_head_and_shoulders",
        "rectangle_breakout",
        "channel_breakout",
        "rounding_bottom",
    )

    # =========================================================
    # CANDLESTICK PATTERNS
    # =========================================================
    ENABLE_CANDLESTICK_PATTERNS: bool = True

    CANDLESTICK_PATTERNS: tuple[str, ...] = (
        "bullish_engulfing",
        "hammer",
        "morning_star",
        "piercing_pattern",
        "bullish_harami",
        "bullish_marubozu",
        "inverted_hammer",
        "three_white_soldiers",
        "tweezer_bottom",
        "doji_bullish_confirmation",
    )

    STRONG_BULLISH_CANDLE_PATTERNS: tuple[str, ...] = (
        "bullish_engulfing",
        "morning_star",
        "three_white_soldiers",
        "bullish_marubozu",
    )

    # =========================================================
    # TECHNICAL SCORE
    # =========================================================
    STRONG_BUY_MIN_SCORE: float = 80.0

    INTRADAY_MIN_CONFIRMATIONS: int = 7
    SWING_MIN_CONFIRMATIONS: int = 7

    # =========================================================
    # SCORE WEIGHTS - INTRADAY
    # Total = 100
    # =========================================================
    INTRADAY_WEIGHT_TREND: float = 15.0
    INTRADAY_WEIGHT_RSI: float = 8.0
    INTRADAY_WEIGHT_MACD: float = 10.0
    INTRADAY_WEIGHT_SUPERTREND: float = 10.0
    INTRADAY_WEIGHT_VWAP: float = 12.0
    INTRADAY_WEIGHT_VOLUME: float = 12.0
    INTRADAY_WEIGHT_BREAKOUT: float = 12.0
    INTRADAY_WEIGHT_PRICE_ACTION: float = 7.0
    INTRADAY_WEIGHT_RELATIVE_STRENGTH: float = 5.0
    INTRADAY_WEIGHT_PATTERNS: float = 9.0

    # =========================================================
    # SCORE WEIGHTS - SWING
    # Total = 100
    # =========================================================
    SWING_WEIGHT_TREND: float = 20.0
    SWING_WEIGHT_RSI: float = 8.0
    SWING_WEIGHT_MACD: float = 10.0
    SWING_WEIGHT_SUPERTREND: float = 8.0
    SWING_WEIGHT_VOLUME: float = 10.0
    SWING_WEIGHT_BREAKOUT: float = 12.0
    SWING_WEIGHT_PRICE_ACTION: float = 10.0
    SWING_WEIGHT_RELATIVE_STRENGTH: float = 8.0
    SWING_WEIGHT_CHART_PATTERN: float = 9.0
    SWING_WEIGHT_CANDLE_PATTERN: float = 5.0

    # =========================================================
    # MANDATORY STRONG BUY RULES
    # =========================================================
    REQUIRE_BULLISH_EMA_STRUCTURE: bool = True
    REQUIRE_SUPERTREND_BUY: bool = True
    REQUIRE_VALID_RSI: bool = True
    REQUIRE_POSITIVE_RISK_REWARD: bool = True

    # Intraday-specific mandatory checks
    INTRADAY_REQUIRE_MACD_BULLISH: bool = True
    INTRADAY_REQUIRE_VOLUME_CONFIRMATION: bool = True

    # Swing-specific mandatory checks
    SWING_REQUIRE_PRICE_ABOVE_EMA20: bool = True
    SWING_REQUIRE_PRICE_ABOVE_EMA50: bool = True

    # =========================================================
    # RISK MANAGEMENT
    # =========================================================
    MIN_RISK_REWARD: float = 2.0

    MAX_STOP_LOSS_PERCENT_INTRADAY: float = 2.5
    MAX_STOP_LOSS_PERCENT_SWING: float = 8.0

    # =========================================================
    # ENTRY SETTINGS
    # =========================================================
    ENTRY_BUFFER_PERCENT_INTRADAY: float = 0.05
    ENTRY_BUFFER_PERCENT_SWING: float = 0.10

    # =========================================================
    # DATA VALIDATION
    # =========================================================
    MIN_REQUIRED_CANDLES_INTRADAY: int = 220
    MIN_REQUIRED_CANDLES_SWING: int = 220

    ALLOW_FAKE_DATA: bool = False
    ALLOW_ZERO_PRICE: bool = False

    # =========================================================
    # AUTO REFRESH
    # =========================================================
    LIVE_PRICE_REFRESH_SECONDS: int = 10

    INTRADAY_TECHNICAL_REFRESH_SECONDS: int = 60
    SWING_TECHNICAL_REFRESH_SECONDS: int = 300

    SECTOR_SCAN_REFRESH_SECONDS: int = 900

    # =========================================================
    # CACHE / STORAGE
    # =========================================================
    DATA_DIR: str = os.getenv(
        "DATA_DIR",
        "runtime_data",
    )

    PREVIOUS_DAY_FILE: str = os.path.join(
        DATA_DIR,
        "previous_day_candidates.json",
    )

    CURRENT_DAY_FILE: str = os.path.join(
        DATA_DIR,
        "current_day_candidates.json",
    )

    COMMON_STOCKS_FILE: str = os.path.join(
        DATA_DIR,
        "common_stocks.json",
    )

    SCAN_RESULTS_FILE: str = os.path.join(
        DATA_DIR,
        "scan_results.json",
    )

    # =========================================================
    # FYERS
    # =========================================================
    FYERS_CLIENT_ID: str = os.getenv(
        "FYERS_CLIENT_ID",
        "",
    )

    FYERS_SECRET_KEY: str = os.getenv(
        "FYERS_SECRET_KEY",
        "",
    )

    FYERS_REDIRECT_URI: str = os.getenv(
        "FYERS_REDIRECT_URI",
        "",
    )

    FYERS_ACCESS_TOKEN: str = os.getenv(
        "FYERS_ACCESS_TOKEN",
        "",
    )

    # =========================================================
    # HELPER METHODS
    # =========================================================
    @classmethod
    def fyers_configured(cls) -> bool:
        return bool(
            cls.FYERS_CLIENT_ID
            and cls.FYERS_ACCESS_TOKEN
        )

    @classmethod
    def normalize_trading_mode(
        cls,
        mode: str | None,
    ) -> str:
        value = str(
            mode or cls.DEFAULT_TRADING_MODE
        ).strip().lower()

        if value not in cls.SUPPORTED_TRADING_MODES:
            return cls.DEFAULT_TRADING_MODE

        return value

    @classmethod
    def get_primary_resolution(
        cls,
        mode: str,
    ) -> str:
        mode = cls.normalize_trading_mode(mode)

        if mode == cls.MODE_INTRADAY:
            return cls.INTRADAY_PRIMARY_RESOLUTION

        return cls.SWING_PRIMARY_RESOLUTION

    @classmethod
    def get_confirmation_resolution(
        cls,
        mode: str,
    ) -> str:
        mode = cls.normalize_trading_mode(mode)

        if mode == cls.MODE_INTRADAY:
            return cls.INTRADAY_CONFIRMATION_RESOLUTION

        return cls.SWING_CONFIRMATION_RESOLUTION

    @classmethod
    def get_min_confirmations(
        cls,
        mode: str,
    ) -> int:
        mode = cls.normalize_trading_mode(mode)

        if mode == cls.MODE_INTRADAY:
            return cls.INTRADAY_MIN_CONFIRMATIONS

        return cls.SWING_MIN_CONFIRMATIONS

    @classmethod
    def get_min_volume_ratio(
        cls,
        mode: str,
    ) -> float:
        mode = cls.normalize_trading_mode(mode)

        if mode == cls.MODE_INTRADAY:
            return cls.INTRADAY_MIN_VOLUME_RATIO

        return cls.SWING_MIN_VOLUME_RATIO

    @classmethod
    def get_stop_loss_atr_multiplier(
        cls,
        mode: str,
    ) -> float:
        mode = cls.normalize_trading_mode(mode)

        if mode == cls.MODE_INTRADAY:
            return cls.INTRADAY_STOP_LOSS_ATR_MULTIPLIER

        return cls.SWING_STOP_LOSS_ATR_MULTIPLIER

    @classmethod
    def get_target_atr_multiplier(
        cls,
        mode: str,
    ) -> float:
        mode = cls.normalize_trading_mode(mode)

        if mode == cls.MODE_INTRADAY:
            return cls.INTRADAY_TARGET_ATR_MULTIPLIER

        return cls.SWING_TARGET_ATR_MULTIPLIER
