from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:

    # =========================================================
    # APP SETTINGS
    # =========================================================

    APP_NAME: str = "Eagle Smart Scanner"

    APP_VERSION: str = "4.0.0"

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
    #
    # Final universe:
    #
    # Top 10 NSE sectors
    #        ×
    # Top 10 stocks per sector
    #
    # Maximum = 100 stocks
    # =========================================================

    TOP_SECTORS_COUNT: int = 10

    TOP_STOCKS_PER_SECTOR: int = 10

    MAX_SCANNER_UNIVERSE: int = (
        TOP_SECTORS_COUNT
        * TOP_STOCKS_PER_SECTOR
    )


    # =========================================================
    # TRADING MODES
    # =========================================================

    MODE_INTRADAY: str = "intraday"

    MODE_BTST: str = "btst"

    MODE_SWING: str = "swing"

    DEFAULT_TRADING_MODE: str = MODE_INTRADAY

    SUPPORTED_TRADING_MODES: tuple[
        str,
        ...
    ] = (
        MODE_INTRADAY,
        MODE_BTST,
        MODE_SWING,
    )


    # =========================================================
    # INTRADAY TIMEFRAMES
    # =========================================================
    #
    # Primary       = 5 minute
    # Confirmation  = 15 minute
    # Higher        = Daily
    # =========================================================

    INTRADAY_PRIMARY_RESOLUTION: str = "5"

    INTRADAY_CONFIRMATION_RESOLUTION: str = "15"

    INTRADAY_HIGHER_TIMEFRAME_RESOLUTION: str = "D"

    INTRADAY_HISTORY_CANDLES: int = 300


    # =========================================================
    # BTST TIMEFRAMES
    # =========================================================
    #
    # Buy Today Sell Tomorrow:
    #
    # Primary       = 15 minute
    # Confirmation  = 60 minute
    # Higher        = Daily
    # =========================================================

    BTST_PRIMARY_RESOLUTION: str = "15"

    BTST_CONFIRMATION_RESOLUTION: str = "60"

    BTST_HIGHER_TIMEFRAME_RESOLUTION: str = "D"

    BTST_HISTORY_CANDLES: int = 300

    BTST_MIN_HOLDING_DAYS: int = 1

    BTST_MAX_HOLDING_DAYS: int = 3


    # =========================================================
    # SWING TIMEFRAMES
    # =========================================================
    #
    # Primary       = Daily
    # Confirmation  = Weekly derived from Daily
    # Higher        = Weekly
    # =========================================================

    SWING_PRIMARY_RESOLUTION: str = "D"

    SWING_CONFIRMATION_RESOLUTION: str = (
        "weekly_from_daily"
    )

    SWING_HIGHER_TIMEFRAME_RESOLUTION: str = (
        "weekly_from_daily"
    )

    SWING_HISTORY_CANDLES: int = 320

    SWING_MIN_HOLDING_DAYS: int = 5

    SWING_MAX_HOLDING_DAYS: int = 30


    # =========================================================
    # EMA
    # =========================================================

    EMA_FAST: int = 20

    EMA_MEDIUM: int = 50

    EMA_LONG: int = 200


    # =========================================================
    # RSI
    # =========================================================

    RSI_PERIOD: int = 14

    INTRADAY_RSI_MIN: float = 55.0
    INTRADAY_RSI_MAX: float = 75.0

    BTST_RSI_MIN: float = 55.0
    BTST_RSI_MAX: float = 74.0

    SWING_RSI_MIN: float = 52.0
    SWING_RSI_MAX: float = 72.0


    # =========================================================
    # MACD
    # =========================================================

    MACD_FAST: int = 12

    MACD_SLOW: int = 26

    MACD_SIGNAL: int = 9


    # =========================================================
    # ADX
    # =========================================================

    ADX_PERIOD: int = 14

    INTRADAY_MIN_ADX: float = 18.0

    BTST_MIN_ADX: float = 20.0

    SWING_MIN_ADX: float = 20.0


    # =========================================================
    # SUPERTREND
    # =========================================================

    SUPERTREND_PERIOD: int = 10

    SUPERTREND_MULTIPLIER: float = 3.0


    # =========================================================
    # ATR
    # =========================================================

    ATR_PERIOD: int = 14

    INTRADAY_STOP_LOSS_ATR_MULTIPLIER: float = 1.2

    INTRADAY_TARGET_ATR_MULTIPLIER: float = 2.4

    BTST_STOP_LOSS_ATR_MULTIPLIER: float = 1.3

    BTST_TARGET_ATR_MULTIPLIER: float = 2.6

    SWING_STOP_LOSS_ATR_MULTIPLIER: float = 1.5

    SWING_TARGET_ATR_MULTIPLIER: float = 3.0


    # =========================================================
    # VOLUME
    # =========================================================

    VOLUME_AVG_PERIOD: int = 20

    INTRADAY_MIN_VOLUME_RATIO: float = 1.30

    BTST_MIN_VOLUME_RATIO: float = 1.25

    SWING_MIN_VOLUME_RATIO: float = 1.20

    STRONG_VOLUME_RATIO: float = 1.50


    # =========================================================
    # VWAP
    # =========================================================

    ENABLE_VWAP: bool = True

    INTRADAY_REQUIRE_ABOVE_VWAP: bool = True

    BTST_REQUIRE_ABOVE_VWAP: bool = True

    SWING_REQUIRE_ABOVE_VWAP: bool = False


    # =========================================================
    # PRICE ACTION
    # =========================================================

    ENABLE_PRICE_ACTION: bool = True

    REQUIRE_HIGHER_HIGH: bool = False

    REQUIRE_HIGHER_LOW: bool = False

    PRICE_ACTION_LOOKBACK: int = 20


    # =========================================================
    # BREAKOUT
    # =========================================================

    ENABLE_BREAKOUT_ANALYSIS: bool = True

    INTRADAY_BREAKOUT_LOOKBACK: int = 20

    BTST_BREAKOUT_LOOKBACK: int = 30

    SWING_BREAKOUT_LOOKBACK: int = 50

    BREAKOUT_BUFFER_PERCENT: float = 0.10


    # =========================================================
    # BTST CLOSING STRENGTH
    # =========================================================
    #
    # Stock ideally closes in upper part
    # of its day's range.
    # =========================================================

    BTST_MIN_CLOSE_POSITION_PERCENT: float = 70.0

    BTST_MAX_DISTANCE_FROM_DAY_HIGH_PERCENT: float = 2.0


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

    CHART_PATTERNS: tuple[
        str,
        ...
    ] = (
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

    BULLISH_CHART_PATTERNS: tuple[
        str,
        ...
    ] = (
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

    CANDLESTICK_PATTERNS: tuple[
        str,
        ...
    ] = (
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

    STRONG_BULLISH_CANDLE_PATTERNS: tuple[
        str,
        ...
    ] = (
        "bullish_engulfing",
        "morning_star",
        "three_white_soldiers",
        "bullish_marubozu",
    )


    # =========================================================
    # BUY / STRONG BUY
    # =========================================================

    BUY_MIN_SCORE: float = 70.0

    STRONG_BUY_MIN_SCORE: float = 80.0

    INTRADAY_MIN_CONFIRMATIONS: int = 7

    BTST_MIN_CONFIRMATIONS: int = 7

    SWING_MIN_CONFIRMATIONS: int = 7


    # =========================================================
    # INTRADAY WEIGHTS
    # TOTAL = 100
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
    # BTST WEIGHTS
    # TOTAL = 100
    # =========================================================

    BTST_WEIGHT_TREND: float = 16.0

    BTST_WEIGHT_RSI: float = 7.0

    BTST_WEIGHT_MACD: float = 10.0

    BTST_WEIGHT_SUPERTREND: float = 8.0

    BTST_WEIGHT_VWAP: float = 5.0

    BTST_WEIGHT_VOLUME: float = 12.0

    BTST_WEIGHT_BREAKOUT: float = 12.0

    BTST_WEIGHT_PRICE_ACTION: float = 8.0

    BTST_WEIGHT_RELATIVE_STRENGTH: float = 7.0

    BTST_WEIGHT_PATTERNS: float = 8.0

    BTST_WEIGHT_CLOSING_STRENGTH: float = 7.0


    # =========================================================
    # SWING WEIGHTS
    # TOTAL = 100
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
    # MANDATORY RULES
    # =========================================================

    REQUIRE_BULLISH_EMA_STRUCTURE: bool = True

    REQUIRE_SUPERTREND_BUY: bool = True

    REQUIRE_VALID_RSI: bool = True

    REQUIRE_POSITIVE_RISK_REWARD: bool = True


    # =========================================================
    # INTRADAY MANDATORY RULES
    # =========================================================

    INTRADAY_REQUIRE_MACD_BULLISH: bool = True

    INTRADAY_REQUIRE_VOLUME_CONFIRMATION: bool = True

    INTRADAY_REQUIRE_ABOVE_VWAP: bool = True


    # =========================================================
    # BTST MANDATORY RULES
    # =========================================================

    BTST_REQUIRE_MACD_BULLISH: bool = True

    BTST_REQUIRE_VOLUME_CONFIRMATION: bool = True

    BTST_REQUIRE_PRICE_ABOVE_EMA20: bool = True

    BTST_REQUIRE_PRICE_ABOVE_EMA50: bool = True

    BTST_REQUIRE_DAILY_BULLISH_CONFIRMATION: bool = True


    # =========================================================
    # SWING MANDATORY RULES
    # =========================================================

    SWING_REQUIRE_PRICE_ABOVE_EMA20: bool = True

    SWING_REQUIRE_PRICE_ABOVE_EMA50: bool = True


    # =========================================================
    # RISK MANAGEMENT
    # =========================================================

    MIN_RISK_REWARD: float = 2.0

    MAX_STOP_LOSS_PERCENT_INTRADAY: float = 2.5

    MAX_STOP_LOSS_PERCENT_BTST: float = 4.0

    MAX_STOP_LOSS_PERCENT_SWING: float = 8.0


    # =========================================================
    # ENTRY BUFFER
    # =========================================================

    ENTRY_BUFFER_PERCENT_INTRADAY: float = 0.05

    ENTRY_BUFFER_PERCENT_BTST: float = 0.08

    ENTRY_BUFFER_PERCENT_SWING: float = 0.10


    # =========================================================
    # DATA VALIDATION
    # =========================================================

    MIN_REQUIRED_CANDLES_INTRADAY: int = 220

    MIN_REQUIRED_CANDLES_BTST: int = 160

    MIN_REQUIRED_CANDLES_SWING: int = 220

    ALLOW_FAKE_DATA: bool = False

    ALLOW_ZERO_PRICE: bool = False


    # =========================================================
    # AUTO REFRESH
    # =========================================================

    LIVE_PRICE_REFRESH_SECONDS: int = 10

    INTRADAY_TECHNICAL_REFRESH_SECONDS: int = 60

    BTST_TECHNICAL_REFRESH_SECONDS: int = 180

    SWING_TECHNICAL_REFRESH_SECONDS: int = 300

    SECTOR_SCAN_REFRESH_SECONDS: int = 900


    # =========================================================
    # DATA DIRECTORY
    # =========================================================

    DATA_DIR: str = os.getenv(
        "DATA_DIR",
        "runtime_data",
    )


    # =========================================================
    # INTRADAY STORAGE
    # =========================================================

    INTRADAY_PREVIOUS_DAY_FILE: str = os.path.join(
        DATA_DIR,
        "intraday_previous_day_candidates.json",
    )

    INTRADAY_CURRENT_DAY_FILE: str = os.path.join(
        DATA_DIR,
        "intraday_current_day_candidates.json",
    )

    INTRADAY_COMMON_STOCKS_FILE: str = os.path.join(
        DATA_DIR,
        "intraday_common_stocks.json",
    )

    INTRADAY_SCAN_RESULTS_FILE: str = os.path.join(
        DATA_DIR,
        "intraday_scan_results.json",
    )


    # =========================================================
    # BTST STORAGE
    # =========================================================

    BTST_PREVIOUS_DAY_FILE: str = os.path.join(
        DATA_DIR,
        "btst_previous_day_candidates.json",
    )

    BTST_CURRENT_DAY_FILE: str = os.path.join(
        DATA_DIR,
        "btst_current_day_candidates.json",
    )

    BTST_COMMON_STOCKS_FILE: str = os.path.join(
        DATA_DIR,
        "btst_common_stocks.json",
    )

    BTST_SCAN_RESULTS_FILE: str = os.path.join(
        DATA_DIR,
        "btst_scan_results.json",
    )


    # =========================================================
    # SWING STORAGE
    # =========================================================

    SWING_PREVIOUS_DAY_FILE: str = os.path.join(
        DATA_DIR,
        "swing_previous_day_candidates.json",
    )

    SWING_CURRENT_DAY_FILE: str = os.path.join(
        DATA_DIR,
        "swing_current_day_candidates.json",
    )

    SWING_COMMON_STOCKS_FILE: str = os.path.join(
        DATA_DIR,
        "swing_common_stocks.json",
    )

    SWING_SCAN_RESULTS_FILE: str = os.path.join(
        DATA_DIR,
        "swing_scan_results.json",
    )


    # =========================================================
    # LEGACY STORAGE ALIASES
    # =========================================================
    #
    # Older modules may still import these.
    # Keep them until all modules are migrated.
    # =========================================================

    PREVIOUS_DAY_FILE: str = (
        SWING_PREVIOUS_DAY_FILE
    )

    CURRENT_DAY_FILE: str = (
        SWING_CURRENT_DAY_FILE
    )

    COMMON_STOCKS_FILE: str = (
        SWING_COMMON_STOCKS_FILE
    )

    SCAN_RESULTS_FILE: str = (
        SWING_SCAN_RESULTS_FILE
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
    # FYERS CONFIG CHECK
    # =========================================================

    @classmethod
    def fyers_configured(
        cls,
    ) -> bool:

        return bool(
            cls.FYERS_CLIENT_ID
            and cls.FYERS_SECRET_KEY
            and cls.FYERS_REDIRECT_URI
        )


    # =========================================================
    # NORMALIZE MODE
    # =========================================================

    @classmethod
    def normalize_trading_mode(
        cls,
        mode: str | None,
    ) -> str:

        value = str(
            mode
            or cls.DEFAULT_TRADING_MODE
        ).strip().lower()

        aliases = {
            "day": cls.MODE_INTRADAY,
            "daytrade": cls.MODE_INTRADAY,
            "day_trade": cls.MODE_INTRADAY,
            "intraday": cls.MODE_INTRADAY,

            "btst": cls.MODE_BTST,
            "buy_today_sell_tomorrow": (
                cls.MODE_BTST
            ),
            "buy-today-sell-tomorrow": (
                cls.MODE_BTST
            ),

            "swing": cls.MODE_SWING,
            "positional": cls.MODE_SWING,
        }

        normalized = aliases.get(
            value,
            value,
        )

        if (
            normalized
            not in cls.SUPPORTED_TRADING_MODES
        ):
            return cls.DEFAULT_TRADING_MODE

        return normalized


    # =========================================================
    # PRIMARY RESOLUTION
    # =========================================================

    @classmethod
    def get_primary_resolution(
        cls,
        mode: str,
    ) -> str:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.INTRADAY_PRIMARY_RESOLUTION
            )

        if mode == cls.MODE_BTST:
            return (
                cls.BTST_PRIMARY_RESOLUTION
            )

        return (
            cls.SWING_PRIMARY_RESOLUTION
        )


    # =========================================================
    # CONFIRMATION RESOLUTION
    # =========================================================

    @classmethod
    def get_confirmation_resolution(
        cls,
        mode: str,
    ) -> str:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.INTRADAY_CONFIRMATION_RESOLUTION
            )

        if mode == cls.MODE_BTST:
            return (
                cls.BTST_CONFIRMATION_RESOLUTION
            )

        return (
            cls.SWING_CONFIRMATION_RESOLUTION
        )


    # =========================================================
    # HIGHER TIMEFRAME RESOLUTION
    # =========================================================

    @classmethod
    def get_higher_timeframe_resolution(
        cls,
        mode: str,
    ) -> str:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls
                .INTRADAY_HIGHER_TIMEFRAME_RESOLUTION
            )

        if mode == cls.MODE_BTST:
            return (
                cls
                .BTST_HIGHER_TIMEFRAME_RESOLUTION
            )

        return (
            cls
            .SWING_HIGHER_TIMEFRAME_RESOLUTION
        )


    # =========================================================
    # MINIMUM CONFIRMATIONS
    # =========================================================

    @classmethod
    def get_min_confirmations(
        cls,
        mode: str,
    ) -> int:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.INTRADAY_MIN_CONFIRMATIONS
            )

        if mode == cls.MODE_BTST:
            return (
                cls.BTST_MIN_CONFIRMATIONS
            )

        return (
            cls.SWING_MIN_CONFIRMATIONS
        )


    # =========================================================
    # RSI RANGE
    # =========================================================

    @classmethod
    def get_rsi_range(
        cls,
        mode: str,
    ) -> tuple[
        float,
        float,
    ]:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.INTRADAY_RSI_MIN,
                cls.INTRADAY_RSI_MAX,
            )

        if mode == cls.MODE_BTST:
            return (
                cls.BTST_RSI_MIN,
                cls.BTST_RSI_MAX,
            )

        return (
            cls.SWING_RSI_MIN,
            cls.SWING_RSI_MAX,
        )


    # =========================================================
    # MINIMUM ADX
    # =========================================================

    @classmethod
    def get_min_adx(
        cls,
        mode: str,
    ) -> float:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return cls.INTRADAY_MIN_ADX

        if mode == cls.MODE_BTST:
            return cls.BTST_MIN_ADX

        return cls.SWING_MIN_ADX


    # =========================================================
    # MINIMUM VOLUME RATIO
    # =========================================================

    @classmethod
    def get_min_volume_ratio(
        cls,
        mode: str,
    ) -> float:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.INTRADAY_MIN_VOLUME_RATIO
            )

        if mode == cls.MODE_BTST:
            return (
                cls.BTST_MIN_VOLUME_RATIO
            )

        return (
            cls.SWING_MIN_VOLUME_RATIO
        )


    # =========================================================
    # BREAKOUT LOOKBACK
    # =========================================================

    @classmethod
    def get_breakout_lookback(
        cls,
        mode: str,
    ) -> int:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.INTRADAY_BREAKOUT_LOOKBACK
            )

        if mode == cls.MODE_BTST:
            return (
                cls.BTST_BREAKOUT_LOOKBACK
            )

        return (
            cls.SWING_BREAKOUT_LOOKBACK
        )


    # =========================================================
    # STOP LOSS ATR MULTIPLIER
    # =========================================================

    @classmethod
    def get_stop_loss_atr_multiplier(
        cls,
        mode: str,
    ) -> float:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls
                .INTRADAY_STOP_LOSS_ATR_MULTIPLIER
            )

        if mode == cls.MODE_BTST:
            return (
                cls
                .BTST_STOP_LOSS_ATR_MULTIPLIER
            )

        return (
            cls
            .SWING_STOP_LOSS_ATR_MULTIPLIER
        )


    # =========================================================
    # TARGET ATR MULTIPLIER
    # =========================================================

    @classmethod
    def get_target_atr_multiplier(
        cls,
        mode: str,
    ) -> float:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls
                .INTRADAY_TARGET_ATR_MULTIPLIER
            )

        if mode == cls.MODE_BTST:
            return (
                cls
                .BTST_TARGET_ATR_MULTIPLIER
            )

        return (
            cls
            .SWING_TARGET_ATR_MULTIPLIER
        )


    # =========================================================
    # MAX STOP LOSS %
    # =========================================================

    @classmethod
    def get_max_stop_loss_percent(
        cls,
        mode: str,
    ) -> float:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.MAX_STOP_LOSS_PERCENT_INTRADAY
            )

        if mode == cls.MODE_BTST:
            return (
                cls.MAX_STOP_LOSS_PERCENT_BTST
            )

        return (
            cls.MAX_STOP_LOSS_PERCENT_SWING
        )


    # =========================================================
    # ENTRY BUFFER
    # =========================================================

    @classmethod
    def get_entry_buffer_percent(
        cls,
        mode: str,
    ) -> float:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.ENTRY_BUFFER_PERCENT_INTRADAY
            )

        if mode == cls.MODE_BTST:
            return (
                cls.ENTRY_BUFFER_PERCENT_BTST
            )

        return (
            cls.ENTRY_BUFFER_PERCENT_SWING
        )


    # =========================================================
    # MINIMUM REQUIRED CANDLES
    # =========================================================

    @classmethod
    def get_min_required_candles(
        cls,
        mode: str,
    ) -> int:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.MIN_REQUIRED_CANDLES_INTRADAY
            )

        if mode == cls.MODE_BTST:
            return (
                cls.MIN_REQUIRED_CANDLES_BTST
            )

        return (
            cls.MIN_REQUIRED_CANDLES_SWING
        )


    # =========================================================
    # TECHNICAL REFRESH
    # =========================================================

    @classmethod
    def get_technical_refresh_seconds(
        cls,
        mode: str,
    ) -> int:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls
                .INTRADAY_TECHNICAL_REFRESH_SECONDS
            )

        if mode == cls.MODE_BTST:
            return (
                cls
                .BTST_TECHNICAL_REFRESH_SECONDS
            )

        return (
            cls
            .SWING_TECHNICAL_REFRESH_SECONDS
        )


    # =========================================================
    # MODE-SPECIFIC STORAGE HELPERS
    # =========================================================

    @classmethod
    def get_previous_day_file(
        cls,
        mode: str,
    ) -> str:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.INTRADAY_PREVIOUS_DAY_FILE
            )

        if mode == cls.MODE_BTST:
            return (
                cls.BTST_PREVIOUS_DAY_FILE
            )

        return (
            cls.SWING_PREVIOUS_DAY_FILE
        )


    @classmethod
    def get_current_day_file(
        cls,
        mode: str,
    ) -> str:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.INTRADAY_CURRENT_DAY_FILE
            )

        if mode == cls.MODE_BTST:
            return (
                cls.BTST_CURRENT_DAY_FILE
            )

        return (
            cls.SWING_CURRENT_DAY_FILE
        )


    @classmethod
    def get_common_stocks_file(
        cls,
        mode: str,
    ) -> str:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.INTRADAY_COMMON_STOCKS_FILE
            )

        if mode == cls.MODE_BTST:
            return (
                cls.BTST_COMMON_STOCKS_FILE
            )

        return (
            cls.SWING_COMMON_STOCKS_FILE
        )


    @classmethod
    def get_scan_results_file(
        cls,
        mode: str,
    ) -> str:

        mode = (
            cls.normalize_trading_mode(
                mode
            )
        )

        if mode == cls.MODE_INTRADAY:
            return (
                cls.INTRADAY_SCAN_RESULTS_FILE
            )

        if mode == cls.MODE_BTST:
            return (
                cls.BTST_SCAN_RESULTS_FILE
            )

        return (
            cls.SWING_SCAN_RESULTS_FILE
        )
