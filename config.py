import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ==========================================================
    # PROJECT INFORMATION
    # ==========================================================
    APP_NAME = "Eagle Smart Scanner"
    VERSION = "1.0.0"

    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "CHANGE_THIS_TO_A_RANDOM_SECRET_KEY"
    )

    # ==========================================================
    # FYERS API
    # ==========================================================
    FYERS_CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "")
    FYERS_SECRET_KEY = os.getenv("FYERS_SECRET_KEY", "")
    FYERS_REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI", "")

    # ==========================================================
    # SESSION
    # ==========================================================
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # HTTPS deploy होने पर True कर देंगे
    SESSION_COOKIE_SECURE = False

    # ==========================================================
    # CACHE
    # ==========================================================
    CACHE_TIMEOUT = 60

    INDEX_REFRESH_SECONDS = 10
    STOCK_REFRESH_SECONDS = 15
    SCANNER_REFRESH_SECONDS = 180

    # ==========================================================
    # SCANNER SETTINGS
    # ==========================================================
    DEFAULT_TIMEFRAME = "3_month"

    SUPPORTED_TIMEFRAMES = [
        "15_30_days",
        "3_month",
        "6_month",
        "1_year",
        "3_year"
    ]

    SHOW_SIGNALS = [
        "BUY",
        "STRONG BUY"
    ]

    MAX_STOCKS = 500

    # ==========================================================
    # TABLE SETTINGS
    # ==========================================================
    DASHBOARD_COLUMNS = [
        "Stock Name",
        "Sector",
        "Current Price",
        "Entry Price",
        "Stop Loss",
        "Target Price",
        "Move-Up Probability",
        "Holding Period",
        "Signal",
        "View Detail"
    ]

    # ==========================================================
    # TECHNICAL FILTERS
    # ==========================================================
    TECHNICAL_FILTERS = [
        "EMA20",
        "EMA50",
        "EMA200",
        "RSI",
        "MACD",
        "SUPERTREND",
        "ADX",
        "VOLUME_BREAKOUT",
        "SUPPORT_RESISTANCE",
        "RELATIVE_STRENGTH"
    ]

    # ==========================================================
    # FUNDAMENTAL FILTERS
    # ==========================================================
    FUNDAMENTAL_FILTERS = [
        "SALES_GROWTH",
        "PROFIT_GROWTH",
        "EPS_GROWTH",
        "ROE",
        "ROCE",
        "DEBT_TO_EQUITY",
        "OPERATING_CASHFLOW",
        "PROMOTER_HOLDING",
        "PROMOTER_PLEDGE",
        "VALUATION"
    ]

    # ==========================================================
    # CHART PATTERNS
    # ==========================================================
    CHART_PATTERNS = [
        "CUP_HANDLE",
        "ASCENDING_TRIANGLE",
        "SYMMETRICAL_TRIANGLE",
        "FLAG",
        "DOUBLE_BOTTOM",
        "INVERSE_HEAD_SHOULDER",
        "FALLING_WEDGE",
        "RECTANGLE_BREAKOUT",
        "ROUNDED_BOTTOM",
        "CONSOLIDATION_BREAKOUT"
    ]

    # ==========================================================
    # TABLET SUPPORT
    # ==========================================================
    TABLET_OPTIMIZED = True

    AUTO_REFRESH = True

    DEBUG = False
