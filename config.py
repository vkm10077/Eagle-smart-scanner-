from __future__ import annotations

import os
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Config:
    """
    Eagle Smart Scanner - Central Configuration

    Final design:
    - Pure technical scanner
    - Top NSE sectors -> top stocks -> technical scan
    - Intraday / BTST / Swing
    - BUY / STRONG BUY only
    - No fake/fallback market data
    - FYERS REST + WebSocket
    """

    # =========================================================
    # APP
    # =========================================================
    APP_NAME: str = "Eagle Smart Scanner"
    APP_VERSION: str = "5.0.0"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-secret-key")

    DEBUG: bool = os.getenv("DEBUG", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }

    # =========================================================
    # MARKET
    # =========================================================
    MARKET_TIMEZONE: str = "Asia/Kolkata"

    MARKET_OPEN_HOUR: int = 9
    MARKET_OPEN_MINUTE: int = 15

    MARKET_CLOSE_HOUR: int = 15
    MARKET_CLOSE_MINUTE: int = 30

    PREOPEN_START_HOUR: int = 9
    PREOPEN_START_MINUTE: int = 0

    # =========================================================
    # FINAL SCANNER UNIVERSE
    # =========================================================
    # Top 10 NSE sectors x Top 10 stocks = max 100 stocks
    TOP_SECTORS_COUNT: int = 10
    TOP_STOCKS_PER_SECTOR: int = 10
    MAX_SCANNER_UNIVERSE: int = 100

    # Sector must itself be technically acceptable before its
    # stocks are allowed into the final scan.
    REQUIRE_SECTOR_POSITIVE: bool = True
    REQUIRE_SECTOR_BULLISH_TREND: bool = True
    REQUIRE_SECTOR_RELATIVE_STRENGTH: bool = True

    MIN_SECTOR_CHANGE_PCT: float = 0.0
    MIN_SECTOR_SCORE: float = 55.0
    STRONG_SECTOR_SCORE: float = 70.0

    # =========================================================
    # TRADING MODES
    # =========================================================
    MODE_INTRADAY: str = "intraday"
    MODE_BTST: str = "btst"
    MODE_SWING: str = "swing"

    DEFAULT_TRADING_MODE: str = MODE_INTRADAY

    SUPPORTED_TRADING_MODES: ClassVar[tuple[str, ...]] = (
        MODE_INTRADAY,
        MODE_BTST,
        MODE_SWING,
    )

    # =========================================================
    # TIMEFRAMES
    # =========================================================

    # INTRADAY
    INTRADAY_PRIMARY_RESOLUTION: str = "5"
    INTRADAY_CONFIRMATION_RESOLUTION: str = "15"
    INTRADAY_HIGHER_TIMEFRAME_RESOLUTION: str = "D"
    INTRADAY_HISTORY_CANDLES: int = 320

    # BTST
    BTST_PRIMARY_RESOLUTION: str = "15"
    BTST_CONFIRMATION_RESOLUTION: str = "60"
    BTST_HIGHER_TIMEFRAME_RESOLUTION: str = "D"
    BTST_HISTORY_CANDLES: int = 320
    BTST_MIN_HOLDING_DAYS: int = 1
    BTST_MAX_HOLDING_DAYS: int = 3

    # SWING
    SWING_PRIMARY_RESOLUTION: str = "D"
    SWING_CONFIRMATION_RESOLUTION: str = "weekly_from_daily"
    SWING_HIGHER_TIMEFRAME_RESOLUTION: str = "weekly_from_daily"
    SWING_HISTORY_CANDLES: int = 360
    SWING_MIN_HOLDING_DAYS: int = 5
    SWING_MAX_HOLDING_DAYS: int = 30

    # =========================================================
    # TECHNICAL INDICATORS
    # =========================================================

    # EMA
    EMA_FAST: int = 20
    EMA_MEDIUM: int = 50
    EMA_LONG: int = 200

    # RSI
    RSI_PERIOD: int = 14

    INTRADAY_RSI_MIN: float = 55.0
    INTRADAY_RSI_MAX: float = 75.0

    BTST_RSI_MIN: float = 55.0
    BTST_RSI_MAX: float = 74.0

    SWING_RSI_MIN: float = 52.0
    SWING_RSI_MAX: float = 72.0

    # MACD
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9

    # ADX
    ADX_PERIOD: int = 14
    INTRADAY_MIN_ADX: float = 18.0
    BTST_MIN_ADX: float = 20.0
    SWING_MIN_ADX: float = 20.0

    # SUPERTREND
    SUPERTREND_PERIOD: int = 10
    SUPERTREND_MULTIPLIER: float = 3.0

    # ATR
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
    PRICE_ACTION_LOOKBACK: int = 20

    REQUIRE_HIGHER_HIGH: bool = False
    REQUIRE_HIGHER_LOW: bool = False

    # =========================================================
    # BREAKOUT
    # =========================================================
    ENABLE_BREAKOUT_ANALYSIS: bool = True

    INTRADAY_BREAKOUT_LOOKBACK: int = 20
    BTST_BREAKOUT_LOOKBACK: int = 30
    SWING_BREAKOUT_LOOKBACK: int = 50

    BREAKOUT_BUFFER_PERCENT: float = 0.10

    # =========================================================
    # RELATIVE STRENGTH
    # =========================================================
    ENABLE_RELATIVE_STRENGTH: bool = True
    RELATIVE_STRENGTH_LOOKBACK: int = 20

    # Stock RS should beat comparison by at least this much.
    MIN_RELATIVE_STRENGTH_PCT: float = 0.0

    # =========================================================
    # BTST CLOSING STRENGTH
    # =========================================================
    BTST_MIN_CLOSE_POSITION_PERCENT: float = 70.0
    BTST_MAX_DISTANCE_FROM_DAY_HIGH_PERCENT: float = 2.0

    # =========================================================
    # CHART PATTERNS
    # =========================================================
    ENABLE_CHART_PATTERNS: bool = True
    CHART_PATTERN_LOOKBACK: int = 80

    CHART_PATTERNS: ClassVar[tuple[str, ...]] = (
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

    BULLISH_CHART_PATTERNS: ClassVar[tuple[str, ...]] = (
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

    STRONG_BULLISH_CHART_PATTERNS: ClassVar[tuple[str, ...]] = (
        "cup_and_handle",
        "inverse_head_and_shoulders",
        "double_bottom",
        "ascending_triangle",
        "bull_flag",
    )

    # =========================================================
    # CANDLESTICK PATTERNS
    # =========================================================
    ENABLE_CANDLESTICK_PATTERNS: bool = True

    CANDLESTICK_PATTERNS: ClassVar[tuple[str, ...]] = (
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

    STRONG_BULLISH_CANDLE_PATTERNS: ClassVar[tuple[str, ...]] = (
        "bullish_engulfing",
        "morning_star",
        "three_white_soldiers",
        "bullish_marubozu",
    )

    # =========================================================
    # BUY / STRONG BUY
    # =========================================================
    BUY_MIN_SCORE: float = 70.0
    STRONG_BUY_MIN_SCORE: float = 82.0

    INTRADAY_MIN_CONFIRMATIONS: int = 7
    BTST_MIN_CONFIRMATIONS: int = 7
    SWING_MIN_CONFIRMATIONS: int = 7

    SHOW_ONLY_BUY_SIGNALS: bool = True

    # =========================================================
    # SCORING WEIGHTS
    # =========================================================
    # Total for each mode = 100

    INTRADAY_WEIGHTS: ClassVar[dict[str, float]] = {
        "trend": 15.0,
        "rsi": 8.0,
        "macd": 10.0,
        "supertrend": 10.0,
        "vwap": 12.0,
        "volume": 12.0,
        "breakout": 12.0,
        "price_action": 7.0,
        "relative_strength": 5.0,
        "patterns": 9.0,
    }

    BTST_WEIGHTS: ClassVar[dict[str, float]] = {
        "trend": 16.0,
        "rsi": 7.0,
        "macd": 10.0,
        "supertrend": 8.0,
        "vwap": 5.0,
        "volume": 12.0,
        "breakout": 12.0,
        "price_action": 8.0,
        "relative_strength": 7.0,
        "patterns": 8.0,
        "closing_strength": 7.0,
    }

    SWING_WEIGHTS: ClassVar[dict[str, float]] = {
        "trend": 20.0,
        "rsi": 8.0,
        "macd": 10.0,
        "supertrend": 8.0,
        "volume": 10.0,
        "breakout": 12.0,
        "price_action": 10.0,
        "relative_strength": 8.0,
        "chart_pattern": 9.0,
        "candle_pattern": 5.0,
    }

    # =========================================================
    # HARD MANDATORY RULES
    # =========================================================
    REQUIRE_BULLISH_EMA_STRUCTURE: bool = True
    REQUIRE_SUPERTREND_BUY: bool = True
    REQUIRE_VALID_RSI: bool = True
    REQUIRE_MIN_ADX: bool = True
    REQUIRE_POSITIVE_RISK_REWARD: bool = True

    # INTRADAY
    INTRADAY_REQUIRE_MACD_BULLISH: bool = True
    INTRADAY_REQUIRE_VOLUME_CONFIRMATION: bool = True
    INTRADAY_REQUIRE_PRICE_ABOVE_EMA20: bool = True
    INTRADAY_REQUIRE_PRICE_ABOVE_EMA50: bool = True

    # BTST
    BTST_REQUIRE_MACD_BULLISH: bool = True
    BTST_REQUIRE_VOLUME_CONFIRMATION: bool = True
    BTST_REQUIRE_PRICE_ABOVE_EMA20: bool = True
    BTST_REQUIRE_PRICE_ABOVE_EMA50: bool = True
    BTST_REQUIRE_DAILY_BULLISH_CONFIRMATION: bool = True

    # SWING
    SWING_REQUIRE_PRICE_ABOVE_EMA20: bool = True
    SWING_REQUIRE_PRICE_ABOVE_EMA50: bool = True
    SWING_REQUIRE_PRICE_ABOVE_EMA200: bool = True

    # =========================================================
    # MULTI-TIMEFRAME CONFIRMATION
    # =========================================================
    ENABLE_MULTI_TIMEFRAME_CONFIRMATION: bool = True

    INTRADAY_REQUIRE_CONFIRMATION_TF_BULLISH: bool = True
    BTST_REQUIRE_CONFIRMATION_TF_BULLISH: bool = True
    SWING_REQUIRE_CONFIRMATION_TF_BULLISH: bool = True

    # =========================================================
    # RISK MANAGEMENT
    # =========================================================
    MIN_RISK_REWARD: float = 2.0

    MAX_STOP_LOSS_PERCENT_INTRADAY: float = 2.5
    MAX_STOP_LOSS_PERCENT_BTST: float = 4.0
    MAX_STOP_LOSS_PERCENT_SWING: float = 8.0

    ENTRY_BUFFER_PERCENT_INTRADAY: float = 0.05
    ENTRY_BUFFER_PERCENT_BTST: float = 0.08
    ENTRY_BUFFER_PERCENT_SWING: float = 0.10

    # =========================================================
    # STOCK RANKING
    # =========================================================
    # Ranking happens BEFORE deep technical scanning.
    RANK_WEIGHT_PRICE_MOMENTUM: float = 30.0
    RANK_WEIGHT_RELATIVE_STRENGTH: float = 25.0
    RANK_WEIGHT_VOLUME: float = 20.0
    RANK_WEIGHT_TREND: float = 15.0
    RANK_WEIGHT_BREAKOUT_PROXIMITY: float = 10.0

    MIN_STOCK_RANK_SCORE: float = 50.0

    # Avoid unusable/illiquid symbols.
    MIN_STOCK_PRICE: float = 10.0
    MAX_STOCK_PRICE: float = 100000.0
    MIN_AVG_DAILY_VOLUME: float = 100000.0

    # =========================================================
    # DATA VALIDATION / ANTI-FAKE
    # =========================================================
    MIN_REQUIRED_CANDLES_INTRADAY: int = 220
    MIN_REQUIRED_CANDLES_BTST: int = 220
    MIN_REQUIRED_CANDLES_SWING: int = 220

    ALLOW_FAKE_DATA: bool = False
    ALLOW_FALLBACK_RANDOM_DATA: bool = False
    ALLOW_ZERO_PRICE: bool = False

    # If live quote is older than this, it is considered stale.
    LIVE_TICK_MAX_AGE_SECONDS: int = 30

    # =========================================================
    # REFRESH
    # =========================================================
    LIVE_PRICE_REFRESH_SECONDS: int = 5
    INTRADAY_TECHNICAL_REFRESH_SECONDS: int = 60
    BTST_TECHNICAL_REFRESH_SECONDS: int = 180
    SWING_TECHNICAL_REFRESH_SECONDS: int = 300
    SECTOR_SCAN_REFRESH_SECONDS: int = 300

    # Prevent overlapping background scans.
    MIN_SECONDS_BETWEEN_FULL_SCANS: int = 45

    # =========================================================
    # RESULT LIMITS
    # =========================================================
    MAX_RESULTS_PER_MODE: int = 50
    MAX_STRONG_BUY_RESULTS: int = 25

    # =========================================================
    # ALERTS
    # =========================================================
    ENABLE_AUDIO_ALERTS: bool = True
    ALERT_ONLY_ON_NEW_SIGNAL: bool = True

    # =========================================================
    # RUNTIME STORAGE
    # =========================================================
    DATA_DIR: str = os.getenv("DATA_DIR", "runtime_data")

    INTRADAY_PREVIOUS_DAY_FILE: str = os.path.join(
        DATA_DIR, "intraday_previous_day_candidates.json"
    )
    INTRADAY_CURRENT_DAY_FILE: str = os.path.join(
        DATA_DIR, "intraday_current_day_candidates.json"
    )
    INTRADAY_COMMON_STOCKS_FILE: str = os.path.join(
        DATA_DIR, "intraday_common_stocks.json"
    )
    INTRADAY_SCAN_RESULTS_FILE: str = os.path.join(
        DATA_DIR, "intraday_scan_results.json"
    )

    BTST_PREVIOUS_DAY_FILE: str = os.path.join(
        DATA_DIR, "btst_previous_day_candidates.json"
    )
    BTST_CURRENT_DAY_FILE: str = os.path.join(
        DATA_DIR, "btst_current_day_candidates.json"
    )
    BTST_COMMON_STOCKS_FILE: str = os.path.join(
        DATA_DIR, "btst_common_stocks.json"
    )
    BTST_SCAN_RESULTS_FILE: str = os.path.join(
        DATA_DIR, "btst_scan_results.json"
    )

    SWING_PREVIOUS_DAY_FILE: str = os.path.join(
        DATA_DIR, "swing_previous_day_candidates.json"
    )
    SWING_CURRENT_DAY_FILE: str = os.path.join(
        DATA_DIR, "swing_current_day_candidates.json"
    )
    SWING_COMMON_STOCKS_FILE: str = os.path.join(
        DATA_DIR, "swing_common_stocks.json"
    )
    SWING_SCAN_RESULTS_FILE: str = os.path.join(
        DATA_DIR, "swing_scan_results.json"
    )

    # Compatibility aliases during migration.
    PREVIOUS_DAY_FILE: str = SWING_PREVIOUS_DAY_FILE
    CURRENT_DAY_FILE: str = SWING_CURRENT_DAY_FILE
    COMMON_STOCKS_FILE: str = SWING_COMMON_STOCKS_FILE
    SCAN_RESULTS_FILE: str = SWING_SCAN_RESULTS_FILE

    # =========================================================
    # FYERS
    # =========================================================
    FYERS_CLIENT_ID: str = os.getenv("FYERS_CLIENT_ID", "")
    FYERS_SECRET_KEY: str = os.getenv("FYERS_SECRET_KEY", "")
    FYERS_REDIRECT_URI: str = os.getenv("FYERS_REDIRECT_URI", "")
    FYERS_ACCESS_TOKEN: str = os.getenv("FYERS_ACCESS_TOKEN", "")

    FYERS_WEBSOCKET_ENABLED: bool = (
        os.getenv("FYERS_WEBSOCKET_ENABLED", "true").strip().lower()
        in {"1", "true", "yes", "on", "enabled"}
    )

    FYERS_WEBSOCKET_SYMBOLS: ClassVar[tuple[str, ...]] = (
        "NSE:NIFTY50-INDEX",
        "NSE:NIFTYBANK-INDEX",
    )

    # =========================================================
    # HELPERS
    # =========================================================

    @classmethod
    def fyers_configured(cls) -> bool:
        return bool(
            cls.FYERS_CLIENT_ID
            and cls.FYERS_SECRET_KEY
            and cls.FYERS_REDIRECT_URI
        )

    @classmethod
    def normalize_trading_mode(cls, mode: str | None) -> str:
        value = str(mode or cls.DEFAULT_TRADING_MODE).strip().lower()

        aliases = {
            "day": cls.MODE_INTRADAY,
            "daytrade": cls.MODE_INTRADAY,
            "day_trade": cls.MODE_INTRADAY,
            "intraday": cls.MODE_INTRADAY,
            "btst": cls.MODE_BTST,
            "buy_today_sell_tomorrow": cls.MODE_BTST,
            "buy-today-sell-tomorrow": cls.MODE_BTST,
            "swing": cls.MODE_SWING,
            "positional": cls.MODE_SWING,
        }

        normalized = aliases.get(value, value)

        if normalized not in cls.SUPPORTED_TRADING_MODES:
            return cls.DEFAULT_TRADING_MODE

        return normalized

    @classmethod
    def get_primary_resolution(cls, mode: str) -> str:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_PRIMARY_RESOLUTION,
            cls.MODE_BTST: cls.BTST_PRIMARY_RESOLUTION,
            cls.MODE_SWING: cls.SWING_PRIMARY_RESOLUTION,
        }
        return mapping[mode]

    @classmethod
    def get_confirmation_resolution(cls, mode: str) -> str:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_CONFIRMATION_RESOLUTION,
            cls.MODE_BTST: cls.BTST_CONFIRMATION_RESOLUTION,
            cls.MODE_SWING: cls.SWING_CONFIRMATION_RESOLUTION,
        }
        return mapping[mode]

    @classmethod
    def get_higher_timeframe_resolution(cls, mode: str) -> str:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_HIGHER_TIMEFRAME_RESOLUTION,
            cls.MODE_BTST: cls.BTST_HIGHER_TIMEFRAME_RESOLUTION,
            cls.MODE_SWING: cls.SWING_HIGHER_TIMEFRAME_RESOLUTION,
        }
        return mapping[mode]

    @classmethod
    def get_history_candles(cls, mode: str) -> int:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_HISTORY_CANDLES,
            cls.MODE_BTST: cls.BTST_HISTORY_CANDLES,
            cls.MODE_SWING: cls.SWING_HISTORY_CANDLES,
        }
        return mapping[mode]

    @classmethod
    def get_min_confirmations(cls, mode: str) -> int:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_MIN_CONFIRMATIONS,
            cls.MODE_BTST: cls.BTST_MIN_CONFIRMATIONS,
            cls.MODE_SWING: cls.SWING_MIN_CONFIRMATIONS,
        }
        return mapping[mode]

    @classmethod
    def get_rsi_range(cls, mode: str) -> tuple[float, float]:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: (
                cls.INTRADAY_RSI_MIN,
                cls.INTRADAY_RSI_MAX,
            ),
            cls.MODE_BTST: (
                cls.BTST_RSI_MIN,
                cls.BTST_RSI_MAX,
            ),
            cls.MODE_SWING: (
                cls.SWING_RSI_MIN,
                cls.SWING_RSI_MAX,
            ),
        }
        return mapping[mode]

    @classmethod
    def get_min_adx(cls, mode: str) -> float:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_MIN_ADX,
            cls.MODE_BTST: cls.BTST_MIN_ADX,
            cls.MODE_SWING: cls.SWING_MIN_ADX,
        }
        return mapping[mode]

    @classmethod
    def get_min_volume_ratio(cls, mode: str) -> float:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_MIN_VOLUME_RATIO,
            cls.MODE_BTST: cls.BTST_MIN_VOLUME_RATIO,
            cls.MODE_SWING: cls.SWING_MIN_VOLUME_RATIO,
        }
        return mapping[mode]

    @classmethod
    def get_breakout_lookback(cls, mode: str) -> int:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_BREAKOUT_LOOKBACK,
            cls.MODE_BTST: cls.BTST_BREAKOUT_LOOKBACK,
            cls.MODE_SWING: cls.SWING_BREAKOUT_LOOKBACK,
        }
        return mapping[mode]

    @classmethod
    def get_stop_loss_atr_multiplier(cls, mode: str) -> float:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_STOP_LOSS_ATR_MULTIPLIER,
            cls.MODE_BTST: cls.BTST_STOP_LOSS_ATR_MULTIPLIER,
            cls.MODE_SWING: cls.SWING_STOP_LOSS_ATR_MULTIPLIER,
        }
        return mapping[mode]

    @classmethod
    def get_target_atr_multiplier(cls, mode: str) -> float:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_TARGET_ATR_MULTIPLIER,
            cls.MODE_BTST: cls.BTST_TARGET_ATR_MULTIPLIER,
            cls.MODE_SWING: cls.SWING_TARGET_ATR_MULTIPLIER,
        }
        return mapping[mode]

    @classmethod
    def get_max_stop_loss_percent(cls, mode: str) -> float:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.MAX_STOP_LOSS_PERCENT_INTRADAY,
            cls.MODE_BTST: cls.MAX_STOP_LOSS_PERCENT_BTST,
            cls.MODE_SWING: cls.MAX_STOP_LOSS_PERCENT_SWING,
        }
        return mapping[mode]

    @classmethod
    def get_entry_buffer_percent(cls, mode: str) -> float:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.ENTRY_BUFFER_PERCENT_INTRADAY,
            cls.MODE_BTST: cls.ENTRY_BUFFER_PERCENT_BTST,
            cls.MODE_SWING: cls.ENTRY_BUFFER_PERCENT_SWING,
        }
        return mapping[mode]

    @classmethod
    def get_min_required_candles(cls, mode: str) -> int:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.MIN_REQUIRED_CANDLES_INTRADAY,
            cls.MODE_BTST: cls.MIN_REQUIRED_CANDLES_BTST,
            cls.MODE_SWING: cls.MIN_REQUIRED_CANDLES_SWING,
        }
        return mapping[mode]

    @classmethod
    def get_technical_refresh_seconds(cls, mode: str) -> int:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_TECHNICAL_REFRESH_SECONDS,
            cls.MODE_BTST: cls.BTST_TECHNICAL_REFRESH_SECONDS,
            cls.MODE_SWING: cls.SWING_TECHNICAL_REFRESH_SECONDS,
        }
        return mapping[mode]

    @classmethod
    def get_weights(cls, mode: str) -> dict[str, float]:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_WEIGHTS,
            cls.MODE_BTST: cls.BTST_WEIGHTS,
            cls.MODE_SWING: cls.SWING_WEIGHTS,
        }
        return dict(mapping[mode])

    @classmethod
    def get_previous_day_file(cls, mode: str) -> str:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_PREVIOUS_DAY_FILE,
            cls.MODE_BTST: cls.BTST_PREVIOUS_DAY_FILE,
            cls.MODE_SWING: cls.SWING_PREVIOUS_DAY_FILE,
        }
        return mapping[mode]

    @classmethod
    def get_current_day_file(cls, mode: str) -> str:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_CURRENT_DAY_FILE,
            cls.MODE_BTST: cls.BTST_CURRENT_DAY_FILE,
            cls.MODE_SWING: cls.SWING_CURRENT_DAY_FILE,
        }
        return mapping[mode]

    @classmethod
    def get_common_stocks_file(cls, mode: str) -> str:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_COMMON_STOCKS_FILE,
            cls.MODE_BTST: cls.BTST_COMMON_STOCKS_FILE,
            cls.MODE_SWING: cls.SWING_COMMON_STOCKS_FILE,
        }
        return mapping[mode]

    @classmethod
    def get_scan_results_file(cls, mode: str) -> str:
        mode = cls.normalize_trading_mode(mode)

        mapping = {
            cls.MODE_INTRADAY: cls.INTRADAY_SCAN_RESULTS_FILE,
            cls.MODE_BTST: cls.BTST_SCAN_RESULTS_FILE,
            cls.MODE_SWING: cls.SWING_SCAN_RESULTS_FILE,
        }
        return mapping[mode]

    @classmethod
    def validate_scoring_weights(cls) -> None:
        for mode in cls.SUPPORTED_TRADING_MODES:
            total = round(sum(cls.get_weights(mode).values()), 6)
            if total != 100.0:
                raise ValueError(
                    f"{mode} scoring weights must total 100, got {total}"
                )


# Backward-compatible module-level aliases.
FYERS_WEBSOCKET_ENABLED = Config.FYERS_WEBSOCKET_ENABLED
FYERS_WEBSOCKET_SYMBOLS = list(Config.FYERS_WEBSOCKET_SYMBOLS)

# Fail early if someone accidentally changes scoring totals.
Config.validate_scoring_weights()

