from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # -----------------------------
    # APP SETTINGS
    # -----------------------------
    APP_NAME: str = "Eagle Smart Scanner"
    APP_VERSION: str = "2.0.0"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-secret-key")

    # -----------------------------
    # MARKET SETTINGS
    # -----------------------------
    MARKET_TIMEZONE: str = "Asia/Kolkata"
    MARKET_OPEN_HOUR: int = 9
    MARKET_OPEN_MINUTE: int = 15
    MARKET_CLOSE_HOUR: int = 15
    MARKET_CLOSE_MINUTE: int = 30

    # -----------------------------
    # SCANNER UNIVERSE
    # -----------------------------
    INDEX_NAME: str = "NIFTY 500"

    # Top 10 strongest sectors
    TOP_SECTORS_COUNT: int = 10

    # Top 10 stocks from every selected sector
    TOP_STOCKS_PER_SECTOR: int = 10

    # Maximum initial stock universe:
    # 10 sectors × 10 stocks = 100 stocks
    MAX_SCANNER_UNIVERSE: int = (
        TOP_SECTORS_COUNT * TOP_STOCKS_PER_SECTOR
    )

    # -----------------------------
    # TECHNICAL SETTINGS
    # -----------------------------
    EMA_FAST: int = 20
    EMA_MEDIUM: int = 50
    EMA_LONG: int = 200

    RSI_PERIOD: int = 14
    RSI_MIN_STRONG_BUY: float = 55.0
    RSI_MAX_STRONG_BUY: float = 75.0

    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9

    ATR_PERIOD: int = 14

    SUPERTREND_PERIOD: int = 10
    SUPERTREND_MULTIPLIER: float = 3.0

    VOLUME_AVG_PERIOD: int = 20
    MIN_VOLUME_RATIO: float = 1.20

    # -----------------------------
    # STRONG BUY RULES
    # -----------------------------
    STRONG_BUY_MIN_SCORE: float = 80.0

    # Minimum number of technical confirmations
    MIN_CONFIRMATIONS: int = 6

    # -----------------------------
    # RISK MANAGEMENT
    # -----------------------------
    MIN_RISK_REWARD: float = 2.0
    STOP_LOSS_ATR_MULTIPLIER: float = 1.5
    TARGET_ATR_MULTIPLIER: float = 3.0

    # -----------------------------
    # DATA / CANDLE SETTINGS
    # -----------------------------
    DEFAULT_RESOLUTION: str = "D"

    # Number of historical candles required
    # 260 gives enough room for EMA 200
    HISTORY_CANDLES: int = 260

    # -----------------------------
    # AUTO REFRESH
    # -----------------------------
    LIVE_PRICE_REFRESH_SECONDS: int = 10
    TECHNICAL_SCAN_REFRESH_SECONDS: int = 300
    SECTOR_SCAN_REFRESH_SECONDS: int = 900

    # -----------------------------
    # CACHE / STORAGE
    # -----------------------------
    DATA_DIR: str = os.getenv("DATA_DIR", "runtime_data")

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

    # -----------------------------
    # FYERS
    # -----------------------------
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

    # -----------------------------
    # VALIDATION
    # -----------------------------
    @classmethod
    def fyers_configured(cls) -> bool:
        return bool(
            cls.FYERS_CLIENT_ID
            and cls.FYERS_ACCESS_TOKEN
        )
