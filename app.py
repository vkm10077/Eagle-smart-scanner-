from __future__ import annotations

"""
Eagle Smart Scanner - Flask Application

Final application layer for the technical-only Eagle architecture.

Pipeline
--------
FYERS login
    -> FYERS Data WebSocket
    -> Top technical NSE sectors
    -> Top technical stocks per selected sector
    -> Dynamic WebSocket stock subscription
    -> Pattern scan
    -> Deep technical scan
    -> BUY / STRONG BUY only
    -> Dashboard / APIs

Legacy modules intentionally removed:
- ScannerEngine
- FundamentalService
- NIFTY500
- nifty500.py dependency
- FMP
- old quarterly/half-yearly/yearly/5Y/10Y scanner modes

Supported modes:
- Intraday
- BTST
- Swing
"""

import json
import logging
import os
import secrets
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    session,
    url_for,
)
from jinja2 import TemplateNotFound
from werkzeug.middleware.proxy_fix import ProxyFix
from zoneinfo import ZoneInfo

from config import Config


# ============================================================
# CONFIG COMPATIBILITY
# ============================================================

_WEIGHT_ALIASES: dict[str, tuple[str, str]] = {
    "INTRADAY_WEIGHT_TREND": ("INTRADAY_WEIGHTS", "trend"),
    "INTRADAY_WEIGHT_RSI": ("INTRADAY_WEIGHTS", "rsi"),
    "INTRADAY_WEIGHT_MACD": ("INTRADAY_WEIGHTS", "macd"),
    "INTRADAY_WEIGHT_SUPERTREND": ("INTRADAY_WEIGHTS", "supertrend"),
    "INTRADAY_WEIGHT_VWAP": ("INTRADAY_WEIGHTS", "vwap"),
    "INTRADAY_WEIGHT_VOLUME": ("INTRADAY_WEIGHTS", "volume"),
    "INTRADAY_WEIGHT_BREAKOUT": ("INTRADAY_WEIGHTS", "breakout"),
    "INTRADAY_WEIGHT_PRICE_ACTION": ("INTRADAY_WEIGHTS", "price_action"),
    "INTRADAY_WEIGHT_RELATIVE_STRENGTH": ("INTRADAY_WEIGHTS", "relative_strength"),
    "INTRADAY_WEIGHT_PATTERNS": ("INTRADAY_WEIGHTS", "patterns"),

    "BTST_WEIGHT_TREND": ("BTST_WEIGHTS", "trend"),
    "BTST_WEIGHT_RSI": ("BTST_WEIGHTS", "rsi"),
    "BTST_WEIGHT_MACD": ("BTST_WEIGHTS", "macd"),
    "BTST_WEIGHT_SUPERTREND": ("BTST_WEIGHTS", "supertrend"),
    "BTST_WEIGHT_VWAP": ("BTST_WEIGHTS", "vwap"),
    "BTST_WEIGHT_VOLUME": ("BTST_WEIGHTS", "volume"),
    "BTST_WEIGHT_BREAKOUT": ("BTST_WEIGHTS", "breakout"),
    "BTST_WEIGHT_PRICE_ACTION": ("BTST_WEIGHTS", "price_action"),
    "BTST_WEIGHT_RELATIVE_STRENGTH": ("BTST_WEIGHTS", "relative_strength"),
    "BTST_WEIGHT_PATTERNS": ("BTST_WEIGHTS", "patterns"),
    "BTST_WEIGHT_CLOSING_STRENGTH": ("BTST_WEIGHTS", "closing_strength"),

    "SWING_WEIGHT_TREND": ("SWING_WEIGHTS", "trend"),
    "SWING_WEIGHT_RSI": ("SWING_WEIGHTS", "rsi"),
    "SWING_WEIGHT_MACD": ("SWING_WEIGHTS", "macd"),
    "SWING_WEIGHT_SUPERTREND": ("SWING_WEIGHTS", "supertrend"),
    "SWING_WEIGHT_VOLUME": ("SWING_WEIGHTS", "volume"),
    "SWING_WEIGHT_BREAKOUT": ("SWING_WEIGHTS", "breakout"),
    "SWING_WEIGHT_PRICE_ACTION": ("SWING_WEIGHTS", "price_action"),
    "SWING_WEIGHT_RELATIVE_STRENGTH": ("SWING_WEIGHTS", "relative_strength"),
    "SWING_WEIGHT_CHART_PATTERN": ("SWING_WEIGHTS", "chart_pattern"),
    "SWING_WEIGHT_CANDLE_PATTERN": ("SWING_WEIGHTS", "candle_pattern"),
}

for _alias, (_mapping_name, _key) in _WEIGHT_ALIASES.items():
    if not hasattr(Config, _alias):
        setattr(
            Config,
            _alias,
            float(getattr(Config, _mapping_name)[_key]),
        )


# Import Eagle services after Config compatibility aliases are ready.
from data.sector_map import normalize_stock_symbol  # noqa: E402
from scanners.pattern_scanner import get_pattern_scanner  # noqa: E402
from scanners.technical_scanner import get_technical_scanner  # noqa: E402
from services.cache_service import get_cache_service  # noqa: E402
from services.common_stock_engine import FinalStockSignal, get_common_stock_engine  # noqa: E402
from services.fyers_service import (  # noqa: E402
    FyersAuthenticationError,
    FyersService,
    get_fyers_service,
)
from services.fyers_websocket_service import (  # noqa: E402
    get_fyers_websocket_service,
    get_live_market_snapshot,
    get_market_websocket_status,
    start_market_websocket,
    stop_market_websocket,
    update_market_websocket_symbols,
)
from services.live_market_store import get_live_market_store  # noqa: E402
from services.market_data_service import get_market_data_service  # noqa: E402
from services.nse_sector_universe_service import get_nse_sector_universe_service  # noqa: E402
from services.sector_scanner import SectorScanResult, get_sector_scanner  # noqa: E402
from services.stock_ranker import RankedStock, get_stock_ranker  # noqa: E402


# ============================================================
# APP SETTINGS
# ============================================================

APP_NAME = Config.APP_NAME
APP_VERSION = Config.APP_VERSION

APP_ENV = str(
    os.getenv("APP_ENV", os.getenv("FLASK_ENV", "production"))
).strip().lower()

IS_PRODUCTION = APP_ENV == "production"

SECRET_KEY = str(
    os.getenv("SECRET_KEY", Config.SECRET_KEY or "")
).strip()

if not SECRET_KEY or SECRET_KEY == "change-this-secret-key":
    if IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY is missing. Add a strong SECRET_KEY in Render Environment Variables."
        )
    SECRET_KEY = secrets.token_hex(32)

SESSION_LIFETIME_HOURS = max(
    1,
    min(
        int(os.getenv("SESSION_LIFETIME_HOURS", "12")),
        168,
    ),
)

SUPPORTED_MODES = tuple(Config.SUPPORTED_TRADING_MODES)
DEFAULT_MODE = Config.DEFAULT_TRADING_MODE

AUTO_SCAN_ON_DASHBOARD = (
    os.getenv("AUTO_SCAN_ON_DASHBOARD", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)


# ============================================================
# FLASK
# ============================================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

app.secret_key = SECRET_KEY

app.config.update(
    APP_NAME=APP_NAME,
    APP_VERSION=APP_VERSION,
    ENV=APP_ENV,
    DEBUG=False,
    TESTING=False,
    SESSION_COOKIE_NAME="eagle_scanner_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_LIFETIME_HOURS),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    JSON_SORT_KEYS=False,
)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1,
    x_prefix=1,
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(APP_NAME)


# ============================================================
# SERVICES / CACHE / SCAN STATE
# ============================================================

cache = get_cache_service()

_scan_lock = threading.Lock()
_state_lock = threading.RLock()

_scan_state: dict[str, dict[str, Any]] = {
    mode: {
        "running": False,
        "started_at": None,
        "completed_at": None,
        "last_error": None,
        "result_count": 0,
    }
    for mode in SUPPORTED_MODES
}


# ============================================================
# GENERAL HELPERS
# ============================================================

def now_ist() -> datetime:
    return datetime.now(
        ZoneInfo(Config.MARKET_TIMEZONE)
    )


def now_iso() -> str:
    return now_ist().isoformat(
        timespec="seconds"
    )


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def normalize_mode(value: str | None) -> str:
    return Config.normalize_trading_mode(value)


def normalize_symbol(value: Any) -> str:
    return normalize_stock_symbol(
        str(value or "")
    )


def serialize_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    if is_dataclass(value):
        return serialize_value(
            asdict(value)
        )

    if isinstance(value, dict):
        return {
            str(key): serialize_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            serialize_value(item)
            for item in value
        ]

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass

    if hasattr(value, "to_dict"):
        try:
            return serialize_value(
                value.to_dict()
            )
        except Exception:
            pass

    return str(value)


def api_error(
    message: str,
    status_code: int = 500,
    error_code: str = "server_error",
    details: Any | None = None,
):
    payload: dict[str, Any] = {
        "success": False,
        "error": error_code,
        "message": message,
        "timestamp": now_iso(),
    }

    if details is not None and not IS_PRODUCTION:
        payload["details"] = serialize_value(details)

    return jsonify(payload), status_code


def is_auth_error(error: Any) -> bool:
    if isinstance(error, FyersAuthenticationError):
        return True

    text = str(error or "").lower()

    markers = (
        "invalid token",
        "access token",
        "unauthorized",
        "unauthorised",
        "authentication",
        "token expired",
        "session expired",
        "code -16",
        "'code': -16",
        '"code": -16',
    )

    return any(
        marker in text
        for marker in markers
    )


# ============================================================
# FYERS SESSION / TOKEN SYNC
# ============================================================

def get_access_token() -> str | None:
    value = str(
        session.get("access_token") or ""
    ).strip()

    return value or None


def user_is_logged_in() -> bool:
    return bool(get_access_token())


def sync_access_token(
    access_token: str | None = None,
) -> FyersService:
    token = str(
        access_token
        or get_access_token()
        or ""
    ).strip()

    service = get_fyers_service()

    if token and service.access_token != token:
        service.set_access_token(token)

    return service


def store_access_token(
    access_token: str,
) -> None:
    token = str(access_token or "").strip()

    if not token:
        raise ValueError(
            "FYERS access token is empty."
        )

    next_url = session.get("next_url")

    session.clear()
    session.permanent = True

    session["access_token"] = token
    session["logged_in_at"] = utc_now_iso()

    if next_url:
        session["next_url"] = next_url

    sync_access_token(token)

    for mode in SUPPORTED_MODES:
        cache.delete(f"scanner:{mode}")


def remove_access_token() -> None:
    session.clear()

    try:
        get_fyers_service().set_access_token("")
    except Exception:
        pass


def login_required(
    view: Callable[..., Any],
) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not user_is_logged_in():
            if request.path.startswith("/api/"):
                return api_error(
                    "FYERS login is required.",
                    401,
                    "authentication_required",
                )

            session["next_url"] = request.url
            return redirect(url_for("login"))

        sync_access_token()

        return view(*args, **kwargs)

    return wrapped


# ============================================================
# FYERS AUTH
# ============================================================

def generate_fyers_login_url() -> str:
    service = FyersService(
        client_id=Config.FYERS_CLIENT_ID,
        secret_key=Config.FYERS_SECRET_KEY,
        redirect_uri=Config.FYERS_REDIRECT_URI,
    )

    return service.create_auth_url(
        state="eagle-smart-scanner"
    )


def exchange_auth_code_for_token(
    auth_code: str,
) -> str:
    service = FyersService(
        client_id=Config.FYERS_CLIENT_ID,
        secret_key=Config.FYERS_SECRET_KEY,
        redirect_uri=Config.FYERS_REDIRECT_URI,
    )

    return service.exchange_auth_code(
        auth_code
    )


def validate_fyers_session(
    access_token: str | None = None,
) -> dict[str, Any]:
    service = sync_access_token(
        access_token
    )

    profile = service.get_profile()

    return {
        "valid": True,
        "profile": serialize_value(
            profile.get("data", profile)
        ),
    }


# ============================================================
# FYERS WEBSOCKET
# ============================================================

def ensure_market_websocket(
    stock_symbols: list[str] | None = None,
) -> dict[str, Any]:
    if not Config.FYERS_WEBSOCKET_ENABLED:
        return {
            "enabled": False,
            "running": False,
            "connected": False,
        }

    token = get_access_token()

    if not token:
        return {
            "enabled": True,
            "running": False,
            "connected": False,
            "last_error": "FYERS login required.",
        }

    status = get_market_websocket_status()

    if not status.get("running"):
        status = start_market_websocket(
            access_token=token,
            client_id=Config.FYERS_CLIENT_ID,
            symbols=stock_symbols,
        )
    elif stock_symbols:
        status = update_market_websocket_symbols(
            stock_symbols
        )

    return status


def stop_live_market(
    *,
    clear_market_data: bool = True,
) -> None:
    try:
        stop_market_websocket(
            clear_market_data=clear_market_data
        )
    except Exception:
        logger.exception(
            "FYERS WebSocket stop failed"
        )


# ============================================================
# RESULT STORAGE
# ============================================================

def result_file(mode: str) -> Path:
    return Path(
        Config.get_scan_results_file(mode)
    )


def persist_results(
    *,
    mode: str,
    started_at: str,
    completed_at: str,
    sectors: list[SectorScanResult],
    stocks_ranked: int,
    stocks_deep_scanned: int,
    results: list[FinalStockSignal],
    errors: list[str],
) -> dict[str, Any]:
    payload = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "mode": mode,
        "started_at": started_at,
        "completed_at": completed_at,
        "sectors_selected": len(sectors),
        "stocks_ranked": stocks_ranked,
        "stocks_deep_scanned": stocks_deep_scanned,
        "buy_count": sum(
            1 for item in results
            if item.signal == "BUY"
        ),
        "strong_buy_count": sum(
            1 for item in results
            if item.signal == "STRONG BUY"
        ),
        "errors": errors,
        "results": [
            asdict(item)
            for item in results
        ],
    }

    path = result_file(mode)
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = path.with_suffix(
        path.suffix + ".tmp"
    )

    temp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    os.replace(temp, path)

    cache.set(
        f"scanner:{mode}",
        payload,
        ttl_seconds=Config.get_technical_refresh_seconds(mode),
    )

    return payload


def load_results(
    mode: str,
) -> dict[str, Any]:
    mode = normalize_mode(mode)

    cached = cache.get(
        f"scanner:{mode}"
    )

    if isinstance(cached, dict):
        return cached

    path = result_file(mode)

    if not path.exists():
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "mode": mode,
            "results": [],
            "buy_count": 0,
            "strong_buy_count": 0,
            "errors": [],
            "completed_at": None,
        }

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        logger.exception(
            "Unable to read persisted scanner file: %s",
            path,
        )
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "mode": mode,
            "results": [],
            "buy_count": 0,
            "strong_buy_count": 0,
            "errors": [],
            "completed_at": None,
        }

    if not isinstance(payload, dict):
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "mode": mode,
            "results": [],
            "buy_count": 0,
            "strong_buy_count": 0,
            "errors": [],
            "completed_at": None,
        }

    return payload


# ============================================================
# FINAL EAGLE SCAN
# ============================================================

def execute_eagle_scan(
    mode: str | None,
) -> dict[str, Any]:
    normalized_mode = normalize_mode(mode)

    if not get_access_token():
        raise FyersAuthenticationError(
            "FYERS login required."
        )

    sync_access_token()
    ensure_market_websocket()

    with _state_lock:
        if _scan_state[normalized_mode]["running"]:
            existing = load_results(
                normalized_mode
            )
            existing["running"] = True
            existing["message"] = (
                "Scanner is already running."
            )
            return existing

    if not _scan_lock.acquire(blocking=False):
        existing = load_results(
            normalized_mode
        )
        existing["running"] = True
        existing["message"] = (
            "Another Eagle scan is already running."
        )
        return existing

    started_at = now_iso()

    with _state_lock:
        _scan_state[normalized_mode].update(
            {
                "running": True,
                "started_at": started_at,
                "last_error": None,
            }
        )

    errors: list[str] = []
    selected_sectors: list[SectorScanResult] = []
    grouped_ranked: list[
        tuple[SectorScanResult, list[RankedStock]]
    ] = []
    final_results: list[FinalStockSignal] = []

    stocks_ranked = 0
    stocks_deep_scanned = 0

    try:
        sector_scanner = get_sector_scanner()
        stock_ranker = get_stock_ranker()
        common_engine = get_common_stock_engine()

        # 1) strongest sectors
        selected_sectors = sector_scanner.scan(
            top_n=Config.TOP_SECTORS_COUNT
        )

        # 2) rank stocks first, so WebSocket can subscribe to final universe
        dynamic_stock_symbols: list[str] = []

        for sector in selected_sectors:
            try:
                ranked_stocks = stock_ranker.rank_sector(
                    sector,
                    top_n=Config.TOP_STOCKS_PER_SECTOR,
                )
            except Exception as exc:
                logger.exception(
                    "Stock ranking failed | sector=%s",
                    sector.sector_key,
                )
                errors.append(
                    f"{sector.sector_name}: stock ranking failed: {exc}"
                )
                continue

            ranked_stocks = [
                stock
                for stock in ranked_stocks
                if stock.eligible
            ][: Config.TOP_STOCKS_PER_SECTOR]

            if not ranked_stocks:
                continue

            grouped_ranked.append(
                (sector, ranked_stocks)
            )

            stocks_ranked += len(
                ranked_stocks
            )

            dynamic_stock_symbols.extend(
                stock.fyers_symbol
                for stock in ranked_stocks
            )

        # 3) Update live subscription with selected stocks.
        if dynamic_stock_symbols:
            try:
                ensure_market_websocket(
                    dynamic_stock_symbols
                )
            except Exception as exc:
                logger.exception(
                    "Dynamic WebSocket subscription update failed"
                )
                errors.append(
                    f"WebSocket symbol update failed: {exc}"
                )

        # 4) Deep technical + pattern scan
        for sector, ranked_stocks in grouped_ranked:
            for stock in ranked_stocks:
                stocks_deep_scanned += 1

                try:
                    signal = common_engine.evaluate(
                        stock,
                        sector,
                        mode=normalized_mode,
                    )
                except Exception as exc:
                    logger.exception(
                        "Deep technical scan failed | symbol=%s | mode=%s",
                        stock.fyers_symbol,
                        normalized_mode,
                    )
                    errors.append(
                        f"{stock.fyers_symbol}: {exc}"
                    )
                    continue

                if signal is not None:
                    final_results.append(
                        signal
                    )

        final_results.sort(
            key=lambda item: (
                1
                if item.signal == "STRONG BUY"
                else 0,
                item.final_confidence,
                item.technical_score,
                item.stock_rank_score,
                item.sector_score,
            ),
            reverse=True,
        )

        final_results = final_results[
            : Config.MAX_RESULTS_PER_MODE
        ]

        strong_only = [
            item
            for item in final_results
            if item.signal == "STRONG BUY"
        ]

        if len(strong_only) > Config.MAX_STRONG_BUY_RESULTS:
            allowed_strong_symbols = {
                item.fyers_symbol
                for item in strong_only[
                    : Config.MAX_STRONG_BUY_RESULTS
                ]
            }

            final_results = [
                item
                for item in final_results
                if (
                    item.signal != "STRONG BUY"
                    or item.fyers_symbol in allowed_strong_symbols
                )
            ]

        completed_at = now_iso()

        payload = persist_results(
            mode=normalized_mode,
            started_at=started_at,
            completed_at=completed_at,
            sectors=selected_sectors,
            stocks_ranked=stocks_ranked,
            stocks_deep_scanned=stocks_deep_scanned,
            results=final_results,
            errors=errors,
        )

        with _state_lock:
            _scan_state[normalized_mode].update(
                {
                    "running": False,
                    "completed_at": completed_at,
                    "last_error": (
                        errors[-1] if errors else None
                    ),
                    "result_count": len(
                        final_results
                    ),
                }
            )

        logger.info(
            "Eagle scan completed | mode=%s | sectors=%s | ranked=%s | "
            "deep_scanned=%s | results=%s",
            normalized_mode,
            len(selected_sectors),
            stocks_ranked,
            stocks_deep_scanned,
            len(final_results),
        )

        return payload

    except Exception as exc:
        logger.exception(
            "Eagle scan failed | mode=%s",
            normalized_mode,
        )

        with _state_lock:
            _scan_state[normalized_mode].update(
                {
                    "running": False,
                    "last_error": str(exc),
                }
            )

        raise

    finally:
        _scan_lock.release()


# ============================================================
# SINGLE STOCK ANALYSIS
# ============================================================

def analyze_single_stock(
    symbol: str,
    *,
    mode: str | None,
) -> dict[str, Any]:
    normalized_mode = normalize_mode(mode)
    clean_symbol = normalize_symbol(symbol)

    if not clean_symbol:
        raise ValueError(
            "Stock symbol is empty."
        )

    fyers_symbol = f"NSE:{clean_symbol}-EQ"

    ensure_market_websocket(
        [fyers_symbol]
    )

    market_data = get_market_data_service()

    primary_df = market_data.get_primary_dataframe(
        fyers_symbol,
        normalized_mode,
    )

    pattern = get_pattern_scanner().scan(
        primary_df,
        mode=normalized_mode,
    )

    technical = get_technical_scanner().scan(
        fyers_symbol,
        mode=normalized_mode,
        pattern_confirmation=pattern.confirmation,
    )

    return {
        "symbol": clean_symbol,
        "fyers_symbol": fyers_symbol,
        "mode": normalized_mode,
        "technical": serialize_value(
            technical
        ),
        "patterns": serialize_value(
            pattern
        ),
    }


# ============================================================
# TEMPLATE HELPERS
# ============================================================

@app.context_processor
def inject_template_globals() -> dict[str, Any]:
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "is_logged_in": user_is_logged_in(),
        "default_mode": DEFAULT_MODE,
        "supported_modes": SUPPORTED_MODES,
        "default_timeframe": DEFAULT_MODE,
        "supported_timeframes": SUPPORTED_MODES,
        "current_year": now_ist().year,
    }


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )

    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )

    return response


# ============================================================
# FALLBACK HTML
# ============================================================

FALLBACK_HOME_HTML = """
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ app_name }}</title>
<style>
body{margin:0;font-family:Arial,sans-serif;background:#020617;color:#f8fafc}
.wrap{max-width:800px;margin:auto;padding:32px 18px}
.card{background:#0f172a;border:1px solid #334155;border-radius:18px;padding:24px}
a{display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:12px 18px;border-radius:10px}
.muted{color:#94a3b8}
</style>
</head>
<body>
<div class="wrap"><div class="card">
<h1>Eagle Smart Scanner</h1>
<p class="muted">Technical-only NSE sector scanner — Intraday, BTST, Swing</p>
{% if fyers_configured %}
<a href="{{ url_for('login') }}">FYERS Login</a>
{% else %}
<p>FYERS_CLIENT_ID, FYERS_SECRET_KEY और FYERS_REDIRECT_URI configure करें।</p>
{% endif %}
</div></div>
</body>
</html>
"""

FALLBACK_DASHBOARD_HTML = """
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ page_title }}</title>
<style>
body{margin:0;font-family:Arial,sans-serif;background:#020617;color:#f8fafc}
.wrap{max-width:1400px;margin:auto;padding:18px}
.top,.modes{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.card{background:#0f172a;border:1px solid #334155;border-radius:16px;padding:15px;margin-top:15px}
a,button{background:#2563eb;color:#fff;border:0;text-decoration:none;padding:10px 13px;border-radius:9px;cursor:pointer}
a.active{background:#16a34a}
.error{border-color:#ef4444;color:#fecaca}
.muted{color:#94a3b8}
.table-wrap{overflow:auto}
table{border-collapse:collapse;width:100%;min-width:1150px}
th,td{padding:9px;border-bottom:1px solid #334155;text-align:left;font-size:12px}
.strong{color:#4ade80;font-weight:700}
.buy{color:#86efac;font-weight:700}
</style>
</head>
<body>
<div class="wrap">
<div class="top">
<div>
<h1>{{ app_name }}</h1>
<div class="muted">Pure Technical Scanner | {{ selected_mode|upper }}</div>
</div>
<div>
<a href="{{ url_for('profile') }}">Profile</a>
<a href="{{ url_for('logout') }}">Logout</a>
</div>
</div>

<div class="card modes">
<div>
{% for mode in supported_modes %}
<a class="{% if mode == selected_mode %}active{% endif %}"
href="{{ url_for('dashboard', mode=mode) }}">{{ mode|upper }}</a>
{% endfor %}
</div>
<button id="refreshBtn" onclick="runScan()">Run / Refresh Scanner</button>
</div>

{% if scanner_error %}
<div class="card error"><b>Scanner Error</b><br>{{ scanner_error }}</div>
{% endif %}

<div class="card">
<div class="muted">
Results: {{ stocks|length }} |
Last update: {{ updated_at or 'Not scanned yet' }} |
STRONG BUY: {{ strong_buy_count }} |
BUY: {{ buy_count }}
</div>
</div>

<div class="card table-wrap">
{% if stocks %}
<table>
<thead>
<tr>
<th>Sector</th><th>Stock</th><th>LTP</th><th>Entry</th><th>SL</th>
<th>Target</th><th>R:R</th><th>Confidence</th><th>Signal</th>
<th>Mode</th><th>Chart Pattern</th><th>Candle Pattern</th><th>Detail</th>
</tr>
</thead>
<tbody>
{% for stock in stocks %}
<tr>
<td>{{ stock.get('sector_name','—') }}</td>
<td>{{ stock.get('symbol','—') }}</td>
<td>{{ stock.get('current_price','—') }}</td>
<td>{{ stock.get('entry_price','—') }}</td>
<td>{{ stock.get('stop_loss','—') }}</td>
<td>{{ stock.get('target','—') }}</td>
<td>{{ stock.get('risk_reward','—') }}</td>
<td>{{ stock.get('final_confidence','—') }}</td>
<td class="{% if stock.get('signal') == 'STRONG BUY' %}strong{% else %}buy{% endif %}">
{{ stock.get('signal','—') }}
</td>
<td>{{ stock.get('mode','—') }}</td>
<td>{{ stock.get('chart_pattern') or '—' }}</td>
<td>{{ stock.get('candle_pattern') or '—' }}</td>
<td><a href="{{ url_for('stock_detail', symbol=stock.get('symbol',''), mode=selected_mode) }}">View</a></td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<p>अभी saved BUY/STRONG BUY result नहीं है। Run / Refresh Scanner दबाएँ।</p>
{% endif %}
</div>
</div>

<script>
async function runScan(){
  const btn=document.getElementById('refreshBtn');
  btn.disabled=true;
  btn.textContent='Scanning...';
  try{
    const r=await fetch('/api/scanner/refresh',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mode:'{{ selected_mode }}'})
    });
    const d=await r.json();
    if(!r.ok){throw new Error(d.message||'Scan failed');}
    location.reload();
  }catch(e){
    alert(e.message);
    btn.disabled=false;
    btn.textContent='Run / Refresh Scanner';
  }
}
</script>
</body>
</html>
"""

FALLBACK_ERROR_HTML = """
<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ page_title }}</title>
<style>
body{margin:0;font-family:Arial,sans-serif;background:#020617;color:#f8fafc}
.card{max-width:760px;margin:60px auto;background:#0f172a;border:1px solid #ef4444;border-radius:16px;padding:24px}
a{display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:10px 14px;border-radius:9px}
pre{white-space:pre-wrap;color:#fecaca}
</style>
</head>
<body>
<div class="card">
<h1>{{ error_title }}</h1>
<pre>{{ error_message }}</pre>
<a href="{{ back_url }}">वापस जाएँ</a>
</div>
</body>
</html>
"""


def safe_render(
    template_name: str,
    fallback_html: str,
    **context: Any,
):
    try:
        rendered = render_template(
            template_name,
            **context,
        )

        if rendered and rendered.strip():
            return rendered

    except TemplateNotFound:
        logger.warning(
            "%s not found; fallback used",
            template_name,
        )

    except Exception:
        logger.exception(
            "%s render failed; fallback used",
            template_name,
        )

    return render_template_string(
        fallback_html,
        **context,
    )


# ============================================================
# PAGE ROUTES
# ============================================================

@app.route("/", methods=["GET"])
def home():
    if user_is_logged_in():
        return redirect(
            url_for("dashboard")
        )

    return safe_render(
        "login.html",
        FALLBACK_HOME_HTML,
        page_title=APP_NAME,
        fyers_configured=(
            get_fyers_service()
            .is_app_configured()
        ),
    )


@app.route("/login", methods=["GET"])
def login():
    force = str(
        request.args.get("force", "")
    ).lower() in {
        "1",
        "true",
        "yes",
    }

    if force:
        stop_live_market(
            clear_market_data=True
        )
        remove_access_token()

    if user_is_logged_in():
        return redirect(
            url_for("dashboard")
        )

    try:
        return redirect(
            generate_fyers_login_url()
        )

    except Exception as exc:
        logger.exception(
            "FYERS login URL failed"
        )

        return (
            safe_render(
                "error.html",
                FALLBACK_ERROR_HTML,
                page_title="FYERS Login Error",
                error_title="FYERS Login शुरू नहीं हो पाया",
                error_message=str(exc),
                back_url=url_for("home"),
            ),
            500,
        )


@app.route("/callback", methods=["GET"])
@app.route("/fyers/callback", methods=["GET"])
def fyers_callback():
    callback_error = (
        request.args.get("error")
        or request.args.get("message")
        or request.args.get("error_description")
    )

    if callback_error:
        return (
            safe_render(
                "error.html",
                FALLBACK_ERROR_HTML,
                page_title="FYERS Login Error",
                error_title="FYERS Login असफल रहा",
                error_message=str(callback_error),
                back_url=url_for("login", force="1"),
            ),
            400,
        )

    auth_code = (
        request.args.get("auth_code")
        or request.args.get("code")
    )

    if not auth_code:
        return (
            safe_render(
                "error.html",
                FALLBACK_ERROR_HTML,
                page_title="Callback Error",
                error_title="Authorization code नहीं मिला",
                error_message=(
                    "FYERS callback में auth_code/code parameter नहीं मिला।"
                ),
                back_url=url_for("login", force="1"),
            ),
            400,
        )

    try:
        next_url = session.get("next_url")

        token = exchange_auth_code_for_token(
            str(auth_code)
        )

        store_access_token(token)
        validate_fyers_session(token)

        # Start live feed immediately after successful login.
        ensure_market_websocket()

        if next_url:
            session.pop("next_url", None)
            return redirect(next_url)

        return redirect(
            url_for("dashboard")
        )

    except Exception as exc:
        logger.exception(
            "FYERS callback/token failed"
        )

        stop_live_market(
            clear_market_data=True
        )
        remove_access_token()

        return (
            safe_render(
                "error.html",
                FALLBACK_ERROR_HTML,
                page_title="Token Error",
                error_title="FYERS access token नहीं मिला",
                error_message=str(exc),
                back_url=url_for("login", force="1"),
            ),
            500,
        )


@app.route("/logout", methods=["GET", "POST"])
def logout():
    stop_live_market(
        clear_market_data=True
    )
    remove_access_token()
    return redirect(
        url_for("home")
    )


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    mode = normalize_mode(
        request.args.get("mode")
        or request.args.get("timeframe")
    )

    scanner_error: str | None = None

    force_refresh = str(
        request.args.get("refresh", "")
    ).lower() in {
        "1",
        "true",
        "yes",
    }

    try:
        validate_fyers_session()
        ensure_market_websocket()

        if force_refresh or AUTO_SCAN_ON_DASHBOARD:
            execute_eagle_scan(mode)

    except Exception as exc:
        scanner_error = str(exc)

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()
            return redirect(
                url_for("login", force="1")
            )

    payload = load_results(mode)
    stocks = payload.get("results", [])

    errors = payload.get("errors") or []

    return safe_render(
        "dashboard.html",
        FALLBACK_DASHBOARD_HTML,
        page_title=APP_NAME,
        stocks=stocks,
        scanner_results=stocks,
        selected_mode=mode,
        selected_timeframe=mode,
        supported_modes=SUPPORTED_MODES,
        supported_timeframes=SUPPORTED_MODES,
        scanner_error=(
            scanner_error
            or (
                errors[-1]
                if errors
                else None
            )
        ),
        updated_at=payload.get("completed_at"),
        buy_count=payload.get("buy_count", 0),
        strong_buy_count=payload.get("strong_buy_count", 0),
        websocket_status=get_market_websocket_status(),
    )


@app.route("/stock/<string:symbol>", methods=["GET"])
@login_required
def stock_detail(symbol: str):
    mode = normalize_mode(
        request.args.get("mode")
        or request.args.get("timeframe")
    )

    clean_symbol = normalize_symbol(symbol)

    try:
        validate_fyers_session()
        stock = analyze_single_stock(
            clean_symbol,
            mode=mode,
        )

    except Exception as exc:
        logger.exception(
            "Single stock analysis failed | %s",
            clean_symbol,
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()
            return redirect(
                url_for("login", force="1")
            )

        return (
            safe_render(
                "error.html",
                FALLBACK_ERROR_HTML,
                page_title=f"{clean_symbol} Analysis",
                error_title=f"{clean_symbol} analysis नहीं मिला",
                error_message=str(exc),
                back_url=url_for(
                    "dashboard",
                    mode=mode,
                ),
            ),
            500,
        )

    try:
        rendered = render_template(
            "stock_detail.html",
            page_title=f"{clean_symbol} Analysis",
            symbol=clean_symbol,
            stock=stock,
            selected_mode=mode,
            selected_timeframe=mode,
        )

        if rendered and rendered.strip():
            return rendered

    except Exception:
        logger.exception(
            "stock_detail.html render failed"
        )

    return jsonify(
        {
            "success": True,
            "stock": stock,
            "timestamp": now_iso(),
        }
    )


@app.route("/search", methods=["GET"])
@login_required
def search_stock():
    query = normalize_symbol(
        request.args.get("q")
    )

    mode = normalize_mode(
        request.args.get("mode")
        or request.args.get("timeframe")
    )

    if not query:
        return redirect(
            url_for(
                "dashboard",
                mode=mode,
            )
        )

    return redirect(
        url_for(
            "stock_detail",
            symbol=query,
            mode=mode,
        )
    )


@app.route("/profile", methods=["GET"])
@login_required
def profile():
    try:
        profile_data = validate_fyers_session().get("profile")
        profile_error = None

    except Exception as exc:
        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()
            return redirect(
                url_for("login", force="1")
            )

        profile_data = None
        profile_error = str(exc)

    try:
        rendered = render_template(
            "profile.html",
            page_title="FYERS Profile",
            profile=profile_data,
            profile_error=profile_error,
        )

        if rendered and rendered.strip():
            return rendered

    except Exception:
        logger.exception(
            "profile.html render failed"
        )

    return jsonify(
        {
            "success": profile_error is None,
            "profile": profile_data,
            "error": profile_error,
        }
    )


# ============================================================
# HEALTH / STATUS
# ============================================================

@app.route("/health", methods=["GET"])
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify(
        {
            "success": True,
            "status": "healthy",
            "app": APP_NAME,
            "version": APP_VERSION,
            "environment": APP_ENV,
            "logged_in": user_is_logged_in(),
            "market_data": get_market_data_service().health(),
            "websocket": get_market_websocket_status(),
            "live_store": get_live_market_store().status(),
            "scanner": serialize_value(_scan_state),
            "timestamp": now_iso(),
        }
    )


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify(
        {
            "success": True,
            "application": {
                "name": APP_NAME,
                "version": APP_VERSION,
                "environment": APP_ENV,
            },
            "configuration": {
                "top_sectors": Config.TOP_SECTORS_COUNT,
                "top_stocks_per_sector": Config.TOP_STOCKS_PER_SECTOR,
                "max_universe": Config.MAX_SCANNER_UNIVERSE,
                "modes": SUPPORTED_MODES,
                "fake_data_allowed": Config.ALLOW_FAKE_DATA,
                "fyers_configured": get_fyers_service().is_app_configured(),
                "websocket_enabled": Config.FYERS_WEBSOCKET_ENABLED,
            },
            "session": {
                "logged_in": user_is_logged_in(),
                "logged_in_at": session.get("logged_in_at"),
            },
            "scanner": serialize_value(_scan_state),
            "websocket": get_market_websocket_status(),
            "live_market_store": get_live_market_store().status(),
            "cache": cache.stats(),
            "sector_universe": get_nse_sector_universe_service().health(),
            "timestamp": now_iso(),
        }
    )


@app.route("/api/websocket/status", methods=["GET"])
@login_required
def api_websocket_status():
    try:
        ensure_market_websocket()
    except Exception:
        logger.exception(
            "WebSocket ensure failed"
        )

    return jsonify(
        {
            "success": True,
            "websocket": get_market_websocket_status(),
            "market_data": get_live_market_snapshot(),
            "timestamp": now_iso(),
        }
    )


# ============================================================
# SCANNER APIs
# ============================================================

@app.route("/api/scanner", methods=["GET"])
@login_required
def api_scanner():
    mode = normalize_mode(
        request.args.get("mode")
        or request.args.get("timeframe")
    )

    refresh = str(
        request.args.get("refresh", "")
    ).lower() in {
        "1",
        "true",
        "yes",
    }

    try:
        validate_fyers_session()
        ensure_market_websocket()

        payload = (
            execute_eagle_scan(mode)
            if refresh
            else load_results(mode)
        )

        return jsonify(
            {
                "success": True,
                **serialize_value(payload),
                "running": _scan_state[mode]["running"],
                "websocket": get_market_websocket_status(),
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Scanner API failed"
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()
            return api_error(
                "FYERS session invalid/expired. Login again.",
                401,
                "invalid_fyers_session",
            )

        return api_error(
            str(exc),
            500,
            "scanner_failed",
            exc,
        )


@app.route("/api/scanner/refresh", methods=["POST"])
@login_required
def api_scanner_refresh():
    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    mode = normalize_mode(
        body.get("mode")
        or body.get("timeframe")
        or request.form.get("mode")
        or request.form.get("timeframe")
        or request.args.get("mode")
    )

    try:
        validate_fyers_session()
        ensure_market_websocket()

        payload = execute_eagle_scan(mode)

        return jsonify(
            {
                "success": True,
                "message": "Eagle technical scan completed.",
                **serialize_value(payload),
                "websocket": get_market_websocket_status(),
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Scanner refresh failed"
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()
            return api_error(
                "FYERS session invalid/expired. Login again.",
                401,
                "invalid_fyers_session",
            )

        return api_error(
            str(exc),
            500,
            "scanner_refresh_failed",
            exc,
        )


@app.route("/api/scanner/cache", methods=["GET"])
@login_required
def api_scanner_cache():
    mode = normalize_mode(
        request.args.get("mode")
    )

    payload = load_results(mode)

    return jsonify(
        {
            "success": True,
            "mode": mode,
            "result_count": len(
                payload.get("results", [])
            ),
            "completed_at": payload.get("completed_at"),
            "running": _scan_state[mode]["running"],
            "timestamp": now_iso(),
        }
    )


@app.route("/api/scanner/clear-cache", methods=["POST"])
@login_required
def api_scanner_clear_cache():
    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    mode_value = (
        body.get("mode")
        or request.args.get("mode")
    )

    if mode_value:
        mode = normalize_mode(mode_value)
        cache.delete(
            f"scanner:{mode}"
        )
    else:
        for mode in SUPPORTED_MODES:
            cache.delete(
                f"scanner:{mode}"
            )

    return jsonify(
        {
            "success": True,
            "message": "Scanner memory cache cleared.",
            "timestamp": now_iso(),
        }
    )


@app.route("/api/sectors", methods=["GET"])
@login_required
def api_sectors():
    try:
        validate_fyers_session()
        ensure_market_websocket()

        sectors = get_sector_scanner().scan(
            top_n=Config.TOP_SECTORS_COUNT
        )

        return jsonify(
            {
                "success": True,
                "count": len(sectors),
                "sectors": serialize_value(sectors),
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        return api_error(
            str(exc),
            500,
            "sector_scan_failed",
            exc,
        )

# ============================================================
# DASHBOARD COMPATIBILITY APIs
# Live Indices / Signals / Scan Status / Top Sectors /
# Selected Sector Top Stocks
# ============================================================


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _sector_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(
            item.get("sector_name")
            or item.get("sector")
            or item.get("name")
            or item.get("sector_key")
            or ""
        ).strip()

    return str(
        getattr(item, "sector_name", None)
        or getattr(item, "sector", None)
        or getattr(item, "name", None)
        or getattr(item, "sector_key", None)
        or ""
    ).strip()


def _sector_score(item: Any) -> float:
    if isinstance(item, dict):
        value = (
            item.get("score")
            or item.get("sector_score")
            or item.get("technical_score")
            or 0
        )
    else:
        value = (
            getattr(item, "score", None)
            or getattr(item, "sector_score", None)
            or getattr(item, "technical_score", None)
            or 0
        )

    return _safe_float(value)


def _ranked_stock_to_dict(
    stock: Any,
    *,
    rank: int,
    sector_name: str,
) -> dict[str, Any]:

    raw = serialize_value(stock)

    if not isinstance(raw, dict):
        raw = {}

    symbol = normalize_symbol(
        raw.get("symbol")
        or raw.get("stock_symbol")
        or raw.get("ticker")
        or raw.get("fyers_symbol")
        or ""
    )

    fyers_symbol = str(
        raw.get("fyers_symbol")
        or (
            f"NSE:{symbol}-EQ"
            if symbol
            else ""
        )
    )

    score = _safe_float(
        raw.get("rank_score")
        or raw.get("stock_rank_score")
        or raw.get("technical_score")
        or raw.get("score")
        or 0
    )

    current_price = _safe_float(
        raw.get("current_price")
        or raw.get("ltp")
        or raw.get("price")
        or 0
    )

    return {
        **raw,
        "rank": rank,
        "symbol": symbol,
        "fyers_symbol": fyers_symbol,
        "sector": (
            raw.get("sector")
            or raw.get("sector_name")
            or sector_name
        ),
        "sector_name": (
            raw.get("sector_name")
            or raw.get("sector")
            or sector_name
        ),
        "current_price": current_price,
        "rank_score": score,
        "stock_rank_score": score,
        "eligible": bool(
            raw.get("eligible", True)
        ),
    }


def _find_sector_scan_result(
    requested_sector: str,
) -> SectorScanResult | None:

    clean_requested = str(
        requested_sector or ""
    ).strip().lower()

    if not clean_requested:
        return None

    sectors = get_sector_scanner().scan(
        top_n=Config.TOP_SECTORS_COUNT
    )

    for sector in sectors:
        names = {
            str(
                getattr(
                    sector,
                    "sector_name",
                    "",
                )
            ).strip().lower(),
            str(
                getattr(
                    sector,
                    "sector_key",
                    "",
                )
            ).strip().lower(),
        }

        if clean_requested in names:
            return sector

    return None


# ============================================================
# LIVE INDEX API
# ============================================================

@app.route("/api/indices", methods=["GET"])
@login_required
def api_indices():
    try:
        validate_fyers_session()

        ensure_market_websocket()

        snapshot = get_live_market_snapshot()

        if not isinstance(snapshot, dict):
            snapshot = {}

        preferred_symbols = [
            "NSE:NIFTY50-INDEX",
            "NSE:NIFTYBANK-INDEX",
            "NSE:FINNIFTY-INDEX",
            "NSE:MIDCPNIFTY-INDEX",
        ]

        indices: list[dict[str, Any]] = []

        for fyers_symbol in preferred_symbols:

            raw = snapshot.get(fyers_symbol)

            if raw is None:
                continue

            if not isinstance(raw, dict):
                raw = {
                    "ltp": raw
                }

            ltp = _safe_float(
                raw.get("ltp")
                or raw.get("price")
                or raw.get("last_price")
                or raw.get("current_price")
            )

            previous_close = _safe_float(
                raw.get("prev_close")
                or raw.get("previous_close")
                or raw.get("close")
            )

            change = raw.get("change")

            if change is None and ltp and previous_close:
                change = ltp - previous_close

            change = _safe_float(change)

            change_percent = raw.get(
                "change_percent"
            )

            if change_percent is None:
                change_percent = raw.get(
                    "change_pct"
                )

            if (
                change_percent is None
                and previous_close
            ):
                change_percent = (
                    change / previous_close
                ) * 100.0

            display_names = {
                "NSE:NIFTY50-INDEX":
                    "NIFTY 50",

                "NSE:NIFTYBANK-INDEX":
                    "BANK NIFTY",

                "NSE:FINNIFTY-INDEX":
                    "FIN NIFTY",

                "NSE:MIDCPNIFTY-INDEX":
                    "MIDCAP NIFTY",
            }

            indices.append(
                {
                    "symbol": fyers_symbol,
                    "name": display_names.get(
                        fyers_symbol,
                        fyers_symbol,
                    ),
                    "ltp": ltp,
                    "current_price": ltp,
                    "change": change,
                    "change_percent":
                        _safe_float(
                            change_percent
                        ),
                    "timestamp": (
                        raw.get("timestamp")
                        or raw.get("last_updated")
                        or now_iso()
                    ),
                    "raw": serialize_value(raw),
                }
            )

        return jsonify(
            {
                "success": True,
                "count": len(indices),
                "indices": indices,
                "websocket":
                    get_market_websocket_status(),
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Index API failed"
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()

            return api_error(
                "FYERS session invalid/expired. Login again.",
                401,
                "invalid_fyers_session",
            )

        return api_error(
            str(exc),
            500,
            "indices_failed",
            exc,
        )


# ============================================================
# FINAL BUY / STRONG BUY SIGNAL API
# ============================================================

@app.route("/api/signals", methods=["GET"])
@login_required
def api_signals():

    mode = normalize_mode(
        request.args.get("mode")
        or request.args.get("timeframe")
    )

    payload = load_results(mode)

    results = payload.get(
        "results",
        [],
    )

    if not isinstance(results, list):
        results = []

    # Safety:
    # dashboard never shows HOLD/SELL/neutral records.
    filtered: list[dict[str, Any]] = []

    for item in results:

        if not isinstance(item, dict):
            continue

        signal = str(
            item.get("signal") or ""
        ).strip().upper()

        if signal not in {
            "BUY",
            "STRONG BUY",
        }:
            continue

        filtered.append(item)

    filtered.sort(
        key=lambda item: (
            1
            if str(
                item.get("signal")
            ).upper() == "STRONG BUY"
            else 0,

            _safe_float(
                item.get("final_confidence")
            ),

            _safe_float(
                item.get("technical_score")
            ),
        ),
        reverse=True,
    )

    return jsonify(
        {
            "success": True,
            "mode": mode,
            "count": len(filtered),
            "buy_count": sum(
                1
                for item in filtered
                if str(
                    item.get("signal")
                ).upper() == "BUY"
            ),
            "strong_buy_count": sum(
                1
                for item in filtered
                if str(
                    item.get("signal")
                ).upper() == "STRONG BUY"
            ),
            "results": filtered,
            "updated_at":
                payload.get("completed_at"),
            "running":
                _scan_state[mode]["running"],
            "timestamp": now_iso(),
        }
    )


# ============================================================
# SCANNER STATUS API
# ============================================================

@app.route("/api/scan/status", methods=["GET"])
@login_required
def api_scan_status():

    mode = normalize_mode(
        request.args.get("mode")
        or request.args.get("timeframe")
    )

    state = dict(
        _scan_state[mode]
    )

    payload = load_results(mode)

    result_count = len(
        payload.get("results", [])
    )

    sector_count = int(
        payload.get(
            "sectors_selected",
            0,
        )
        or 0
    )

    ranked_count = int(
        payload.get(
            "stocks_ranked",
            0,
        )
        or 0
    )

    deep_count = int(
        payload.get(
            "stocks_deep_scanned",
            0,
        )
        or 0
    )

    strong_buy_count = int(
        payload.get(
            "strong_buy_count",
            0,
        )
        or 0
    )

    buy_count = int(
        payload.get(
            "buy_count",
            0,
        )
        or 0
    )

    running = bool(
        state.get("running")
    )

    if running:
        stage = "technical_scan"
        progress = 60
    elif payload.get("completed_at"):
        stage = "completed"
        progress = 100
    else:
        stage = "idle"
        progress = 0

    return jsonify(
        {
            "success": True,
            "mode": mode,
            "running": running,
            "stage": stage,
            "progress_percent": progress,
            "sector_count": sector_count,
            "candidate_count": ranked_count,
            "common_count": deep_count,
            "result_count": result_count,
            "buy_count": buy_count,
            "strong_buy_count":
                strong_buy_count,
            "started_at":
                state.get("started_at"),
            "completed_at": (
                state.get("completed_at")
                or payload.get(
                    "completed_at"
                )
            ),
            "last_error":
                state.get("last_error"),
            "timestamp": now_iso(),
        }
    )


# ============================================================
# SCAN REFRESH COMPATIBILITY API
# ============================================================

@app.route("/api/scan/refresh", methods=["POST"])
@login_required
def api_scan_refresh():

    body = (
        request.get_json(
            silent=True
        )
        or {}
    )

    mode = normalize_mode(
        body.get("mode")
        or body.get("timeframe")
        or request.form.get("mode")
        or request.args.get("mode")
    )

    try:
        validate_fyers_session()

        ensure_market_websocket()

        payload = execute_eagle_scan(
            mode
        )

        return jsonify(
            {
                "success": True,
                "message":
                    "Eagle technical scan completed.",
                **serialize_value(payload),
                "running":
                    _scan_state[mode]["running"],
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Dashboard scan refresh failed"
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()

            return api_error(
                "FYERS session invalid/expired. Login again.",
                401,
                "invalid_fyers_session",
            )

        return api_error(
            str(exc),
            500,
            "scan_refresh_failed",
            exc,
        )


# ============================================================
# TOP 10 SECTOR API
# ============================================================

@app.route("/api/top-sectors", methods=["GET"])
@login_required
def api_top_sectors():

    try:
        validate_fyers_session()

        ensure_market_websocket()

        sectors = get_sector_scanner().scan(
            top_n=Config.TOP_SECTORS_COUNT
        )

        output: list[
            dict[str, Any]
        ] = []

        for rank, sector in enumerate(
            sectors,
            start=1,
        ):

            raw = serialize_value(
                sector
            )

            if not isinstance(
                raw,
                dict,
            ):
                raw = {}

            name = _sector_name(
                sector
            )

            score = _sector_score(
                sector
            )

            output.append(
                {
                    **raw,
                    "rank": rank,
                    "sector": name,
                    "sector_name": name,
                    "score": score,
                    "sector_score": score,
                }
            )

        return jsonify(
            {
                "success": True,
                "count": len(output),
                "sectors": output,
                "top_sectors": output,
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Top sector API failed"
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()

            return api_error(
                "FYERS session invalid/expired. Login again.",
                401,
                "invalid_fyers_session",
            )

        return api_error(
            str(exc),
            500,
            "top_sector_scan_failed",
            exc,
        )


# ============================================================
# SELECTED SECTOR -> TOP 10 STOCKS
# ============================================================

@app.route("/api/sector-stocks", methods=["GET"])
@login_required
def api_sector_stocks_query():

    requested_sector = str(
        request.args.get("sector")
        or request.args.get("name")
        or ""
    ).strip()

    if not requested_sector:
        return api_error(
            "Sector is required.",
            400,
            "sector_required",
        )

    mode = normalize_mode(
        request.args.get("mode")
        or request.args.get("timeframe")
    )

    try:
        validate_fyers_session()

        sector = _find_sector_scan_result(
            requested_sector
        )

        if sector is None:
            return api_error(
                f"Sector not found: {requested_sector}",
                404,
                "sector_not_found",
            )

        ranked = (
            get_stock_ranker()
            .rank_sector(
                sector,
                top_n=Config.TOP_STOCKS_PER_SECTOR,
            )
        )

        ranked = [
            stock
            for stock in ranked
            if getattr(
                stock,
                "eligible",
                True,
            )
        ][
            : Config.TOP_STOCKS_PER_SECTOR
        ]

        fyers_symbols = [
            stock.fyers_symbol
            for stock in ranked
            if getattr(
                stock,
                "fyers_symbol",
                None,
            )
        ]

        if fyers_symbols:
            try:
                ensure_market_websocket(
                    fyers_symbols
                )
            except Exception:
                logger.exception(
                    "Sector stock WebSocket subscription failed"
                )

        final_payload = load_results(
            mode
        )

        final_results = (
            final_payload.get(
                "results",
                [],
            )
            or []
        )

        signal_map: dict[
            str,
            dict[str, Any]
        ] = {}

        for result in final_results:

            if not isinstance(
                result,
                dict,
            ):
                continue

            symbol = normalize_symbol(
                result.get(
                    "fyers_symbol"
                )
                or result.get(
                    "symbol"
                )
            )

            if symbol:
                signal_map[
                    symbol
                ] = result

        sector_name = _sector_name(
            sector
        )

        stocks: list[
            dict[str, Any]
        ] = []

        for rank, stock in enumerate(
            ranked,
            start=1,
        ):

            item = _ranked_stock_to_dict(
                stock,
                rank=rank,
                sector_name=sector_name,
            )

            final_signal = signal_map.get(
                item["symbol"]
            )

            if final_signal:
                item["final_status"] = (
                    final_signal.get(
                        "signal"
                    )
                    or "STRONG BUY"
                )

                item["technical_score"] = (
                    final_signal.get(
                        "technical_score"
                    )
                    or item.get(
                        "technical_score"
                    )
                )

                item["entry_price"] = (
                    final_signal.get(
                        "entry_price"
                    )
                )

                item["stop_loss"] = (
                    final_signal.get(
                        "stop_loss"
                    )
                )

                item["target_price"] = (
                    final_signal.get(
                        "target_price"
                    )
                    or final_signal.get(
                        "target"
                    )
                )

            else:
                item["final_status"] = (
                    "RANKED"
                )

            stocks.append(item)

        return jsonify(
            {
                "success": True,
                "mode": mode,
                "sector": sector_name,
                "sector_score":
                    _sector_score(sector),
                "count": len(stocks),
                "stocks": stocks,
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Sector stock API failed | sector=%s",
            requested_sector,
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()

            return api_error(
                "FYERS session invalid/expired. Login again.",
                401,
                "invalid_fyers_session",
            )

        return api_error(
            str(exc),
            500,
            "sector_stock_scan_failed",
            exc,
        )

# ============================================================
# DASHBOARD COMPATIBILITY APIs
# ============================================================

@app.route("/api/indices", methods=["GET"])
@login_required
def api_indices():
    """
    Live index data for dashboard.

    Primary source:
    FYERS WebSocket live market snapshot.

    No fake/demo prices are generated here.
    """
    try:
        validate_fyers_session()
        ensure_market_websocket()

        snapshot = get_live_market_snapshot()

        if isinstance(snapshot, dict):
            market_data = (
                snapshot.get("indices")
                or snapshot.get("market_data")
                or snapshot.get("data")
                or snapshot
            )
        else:
            market_data = {}

        return jsonify(
            {
                "success": True,
                "indices": serialize_value(market_data),
                "market_data": serialize_value(market_data),
                "websocket": get_market_websocket_status(),
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Indices API failed"
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()

            return api_error(
                "FYERS session invalid/expired. Login again.",
                401,
                "invalid_fyers_session",
            )

        return api_error(
            str(exc),
            500,
            "indices_failed",
            exc,
        )


@app.route("/api/signals", methods=["GET"])
@login_required
def api_signals():
    """
    Dashboard Strong Buy signal feed.

    Uses already persisted Eagle scan results.
    It does NOT start a fresh heavy scan.
    """
    mode = normalize_mode(
        request.args.get("mode")
        or request.args.get("timeframe")
    )

    try:
        validate_fyers_session()
        ensure_market_websocket()

        payload = load_results(mode)

        raw_results = payload.get(
            "results",
            [],
        )

        if not isinstance(
            raw_results,
            list,
        ):
            raw_results = []

        # Dashboard final table intentionally shows
        # STRONG BUY only.
        strong_results = [
            item
            for item in raw_results
            if str(
                item.get("signal", "")
                if isinstance(item, dict)
                else getattr(
                    item,
                    "signal",
                    "",
                )
            ).strip().upper()
            == "STRONG BUY"
        ]

        try:
            sectors = get_sector_scanner().scan(
                top_n=Config.TOP_SECTORS_COUNT
            )
        except Exception:
            logger.exception(
                "Top sector refresh failed in signals API"
            )
            sectors = []

        top_sectors = []

        for sector in sectors:
            item = serialize_value(
                sector
            )

            if not isinstance(
                item,
                dict,
            ):
                continue

            top_sectors.append(
                {
                    **item,
                    "sector": (
                        item.get("sector")
                        or item.get("sector_name")
                        or item.get("name")
                        or item.get("sector_key")
                        or ""
                    ),
                    "score": (
                        item.get("score")
                        or item.get("sector_score")
                        or item.get("technical_score")
                        or 0
                    ),
                }
            )

        with _state_lock:
            mode_state = dict(
                _scan_state.get(
                    mode,
                    {},
                )
            )

        scanner_status = {
            **mode_state,
            "stage": (
                "scanning"
                if mode_state.get("running")
                else "idle"
            ),
            "progress_percent": (
                50
                if mode_state.get("running")
                else 100
                if payload.get("completed_at")
                else 0
            ),
            "sector_count": len(
                top_sectors
            ),
            "candidate_count": int(
                payload.get(
                    "stocks_ranked",
                    0,
                )
                or 0
            ),
            "common_count": len(
                raw_results
            ),
            "strong_buy_count": len(
                strong_results
            ),
        }

        return jsonify(
            {
                "success": True,
                "mode": mode,
                "results": serialize_value(
                    strong_results
                ),
                "top_sectors": top_sectors,
                "candidate_count": scanner_status[
                    "candidate_count"
                ],
                "common_count": scanner_status[
                    "common_count"
                ],
                "strong_buy_count": len(
                    strong_results
                ),
                "scanner_status": scanner_status,
                "generated_at": (
                    payload.get(
                        "completed_at"
                    )
                    or now_iso()
                ),
                "websocket": get_market_websocket_status(),
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Signals API failed"
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()

            return api_error(
                "FYERS session invalid/expired. Login again.",
                401,
                "invalid_fyers_session",
            )

        return api_error(
            str(exc),
            500,
            "signals_failed",
            exc,
        )


@app.route("/api/scanner/status", methods=["GET"])
@login_required
def api_scan_status():
    mode = normalize_mode(
        request.args.get("mode")
        or request.args.get("timeframe")
    )

    payload = load_results(
        mode
    )

    results = payload.get(
        "results",
        [],
    )

    if not isinstance(
        results,
        list,
    ):
        results = []

    strong_buy_count = sum(
        1
        for item in results
        if str(
            item.get("signal", "")
            if isinstance(item, dict)
            else getattr(
                item,
                "signal",
                "",
            )
        ).strip().upper()
        == "STRONG BUY"
    )

    with _state_lock:
        state_data = dict(
            _scan_state.get(
                mode,
                {},
            )
        )

    running = bool(
        state_data.get(
            "running"
        )
    )

    scanner = {
        **state_data,
        "mode": mode,
        "stage": (
            "scanning"
            if running
            else (
                "completed"
                if payload.get(
                    "completed_at"
                )
                else "idle"
            )
        ),
        "progress_percent": (
            50
            if running
            else 100
            if payload.get(
                "completed_at"
            )
            else 0
        ),
        "sector_count": int(
            payload.get(
                "sectors_selected",
                0,
            )
            or 0
        ),
        "candidate_count": int(
            payload.get(
                "stocks_ranked",
                0,
            )
            or 0
        ),
        "common_count": len(
            results
        ),
        "strong_buy_count": (
            strong_buy_count
        ),
    }

    return jsonify(
        {
            "success": True,
            "scanner": scanner,
            "scanner_status": scanner,
            "timestamp": now_iso(),
        }
    )


@app.route("/api/top-sectors", methods=["GET"])
@login_required
def api_top_sectors():
    try:
        validate_fyers_session()
        ensure_market_websocket()

        sectors = get_sector_scanner().scan(
            top_n=Config.TOP_SECTORS_COUNT
        )

        output = []

        for sector in sectors:
            item = serialize_value(
                sector
            )

            if not isinstance(
                item,
                dict,
            ):
                continue

            output.append(
                {
                    **item,
                    "sector": (
                        item.get("sector")
                        or item.get("sector_name")
                        or item.get("name")
                        or item.get("sector_key")
                        or ""
                    ),
                    "score": (
                        item.get("score")
                        or item.get("sector_score")
                        or item.get("technical_score")
                        or 0
                    ),
                }
            )

        return jsonify(
            {
                "success": True,
                "count": len(
                    output
                ),
                "top_sectors": output,
                "sectors": output,
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Top sectors API failed"
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()

            return api_error(
                "FYERS session invalid/expired. Login again.",
                401,
                "invalid_fyers_session",
            )

        return api_error(
            str(exc),
            500,
            "top_sectors_failed",
            exc,
        )


@app.route("/api/sector-stocks", methods=["GET"])
@login_required
def api_sector_stocks_query():
    """
    Return Top N technically ranked stocks for
    one selected Top-10 sector.

    Important:
    These are ranking results, not automatically
    Strong Buy signals.
    """
    sector_query = str(
        request.args.get(
            "sector",
            "",
        )
    ).strip()

    mode = normalize_mode(
        request.args.get("mode")
        or request.args.get("timeframe")
    )

    try:
        limit = int(
            request.args.get(
                "limit",
                Config.TOP_STOCKS_PER_SECTOR,
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        limit = Config.TOP_STOCKS_PER_SECTOR

    limit = max(
        1,
        min(
            limit,
            Config.TOP_STOCKS_PER_SECTOR,
        ),
    )

    if not sector_query:
        return api_error(
            "Sector is required.",
            400,
            "sector_required",
        )

    try:
        validate_fyers_session()
        ensure_market_websocket()

        sectors = get_sector_scanner().scan(
            top_n=Config.TOP_SECTORS_COUNT
        )

        selected_sector = None

        query_lower = (
            sector_query
            .strip()
            .lower()
        )

        for sector in sectors:
            sector_data = serialize_value(
                sector
            )

            if not isinstance(
                sector_data,
                dict,
            ):
                continue

            possible_names = {
                str(
                    sector_data.get(
                        "sector",
                        ""
                    )
                ).strip().lower(),
                str(
                    sector_data.get(
                        "sector_name",
                        ""
                    )
                ).strip().lower(),
                str(
                    sector_data.get(
                        "name",
                        ""
                    )
                ).strip().lower(),
                str(
                    sector_data.get(
                        "sector_key",
                        ""
                    )
                ).strip().lower(),
            }

            if query_lower in possible_names:
                selected_sector = sector
                break

        if selected_sector is None:
            return api_error(
                (
                    f"Sector '{sector_query}' "
                    "is not currently present in the Top sectors."
                ),
                404,
                "sector_not_found",
            )

        ranked = get_stock_ranker().rank_sector(
            selected_sector,
            top_n=limit,
        )

        ranked = [
            stock
            for stock in ranked
            if getattr(
                stock,
                "eligible",
                True,
            )
        ][:limit]

        websocket_symbols = [
            getattr(
                stock,
                "fyers_symbol",
                "",
            )
            for stock in ranked
            if getattr(
                stock,
                "fyers_symbol",
                "",
            )
        ]

        if websocket_symbols:
            ensure_market_websocket(
                websocket_symbols
            )

        # Existing final scan is used only to mark
        # whether a ranked stock has already qualified.
        saved_payload = load_results(
            mode
        )

        saved_results = (
            saved_payload.get(
                "results",
                []
            )
            or []
        )

        saved_by_symbol = {}

        for saved in saved_results:
            if not isinstance(
                saved,
                dict,
            ):
                continue

            saved_symbol = normalize_symbol(
                saved.get(
                    "symbol"
                )
                or saved.get(
                    "fyers_symbol"
                )
            )

            if saved_symbol:
                saved_by_symbol[
                    saved_symbol
                ] = saved

        stocks = []

        for rank_number, stock in enumerate(
            ranked,
            start=1,
        ):
            item = serialize_value(
                stock
            )

            if not isinstance(
                item,
                dict,
            ):
                continue

            clean_symbol = normalize_symbol(
                item.get(
                    "symbol"
                )
                or item.get(
                    "fyers_symbol"
                )
            )

            saved = saved_by_symbol.get(
                clean_symbol,
                {},
            )

            signal = str(
                saved.get(
                    "signal",
                    ""
                )
            ).strip().upper()

            stocks.append(
                {
                    **item,
                    "rank": rank_number,
                    "symbol": clean_symbol,
                    "sector": (
                        item.get("sector")
                        or item.get(
                            "sector_name"
                        )
                        or sector_query
                    ),
                    "company_name": (
                        item.get(
                            "company_name"
                        )
                        or item.get(
                            "stock_name"
                        )
                        or item.get(
                            "name"
                        )
                        or clean_symbol
                    ),
                    "score": (
                        item.get("score")
                        or item.get(
                            "stock_rank_score"
                        )
                        or item.get(
                            "rank_score"
                        )
                        or item.get(
                            "technical_score"
                        )
                        or 0
                    ),
                    "signal": (
                        signal
                        if signal
                        == "STRONG BUY"
                        else "RANKED"
                    ),
                    "technical_score": (
                        saved.get(
                            "technical_score"
                        )
                        or item.get(
                            "technical_score"
                        )
                        or 0
                    ),
                    "current_price": (
                        saved.get(
                            "current_price"
                        )
                        or item.get(
                            "current_price"
                        )
                        or item.get(
                            "ltp"
                        )
                        or 0
                    ),
                }
            )

        return jsonify(
            {
                "success": True,
                "sector": sector_query,
                "mode": mode,
                "count": len(
                    stocks
                ),
                "stocks": stocks,
                "results": stocks,
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Sector stocks API failed | sector=%s",
            sector_query,
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()

            return api_error(
                "FYERS session invalid/expired. Login again.",
                401,
                "invalid_fyers_session",
            )

        return api_error(
            str(exc),
            500,
            "sector_stocks_failed",
            exc,
        )


# ============================================================
# STOCK / SEARCH / PROFILE APIs
# ============================================================

@app.route("/api/stock/<string:symbol>", methods=["GET"])
@login_required
def api_stock_detail(symbol: str):
    mode = normalize_mode(
        request.args.get("mode")
        or request.args.get("timeframe")
    )

    try:
        validate_fyers_session()

        stock = analyze_single_stock(
            symbol,
            mode=mode,
        )

        return jsonify(
            {
                "success": True,
                "stock": stock,
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        logger.exception(
            "Stock API failed | %s",
            symbol,
        )

        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()
            return api_error(
                "FYERS session invalid/expired. Login again.",
                401,
                "invalid_fyers_session",
            )

        return api_error(
            str(exc),
            500,
            "stock_analysis_failed",
            exc,
        )


@app.route("/api/search", methods=["GET"])
@login_required
def api_search():
    query = normalize_symbol(
        request.args.get("q")
        or request.args.get("symbol")
    )

    if not query:
        return api_error(
            "Stock symbol is required.",
            400,
            "symbol_required",
        )

    return api_stock_detail(query)


@app.route("/api/profile", methods=["GET"])
@login_required
def api_profile():
    try:
        result = validate_fyers_session()

        return jsonify(
            {
                "success": True,
                "profile": result.get("profile"),
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        if is_auth_error(exc):
            stop_live_market(
                clear_market_data=True
            )
            remove_access_token()

        return api_error(
            str(exc),
            401 if is_auth_error(exc) else 500,
            "invalid_fyers_session"
            if is_auth_error(exc)
            else "profile_failed",
            exc,
        )


# ============================================================
# AUTH / MODE API
# ============================================================

@app.route("/api/auth/status", methods=["GET"])
def api_auth_status():
    return jsonify(
        {
            "success": True,
            "logged_in": user_is_logged_in(),
            "logged_in_at": session.get("logged_in_at"),
            "timestamp": now_iso(),
        }
    )


@app.route("/api/auth/validate", methods=["GET"])
@login_required
def api_auth_validate():
    try:
        result = validate_fyers_session()

        return jsonify(
            {
                "success": True,
                "valid": True,
                "profile": result.get("profile"),
                "timestamp": now_iso(),
            }
        )

    except Exception as exc:
        stop_live_market(
            clear_market_data=True
        )
        remove_access_token()

        return api_error(
            "FYERS session invalid/expired. Login again.",
            401,
            "invalid_fyers_session",
            exc,
        )


@app.route("/api/timeframes", methods=["GET"])
@app.route("/api/modes", methods=["GET"])
def api_modes():
    labels = {
        Config.MODE_INTRADAY: "Intraday — 5m / 15m confirmation",
        Config.MODE_BTST: "BTST — 15m / 60m / Daily",
        Config.MODE_SWING: "Swing — Daily / Weekly",
    }

    items = [
        {
            "value": mode,
            "label": labels[mode],
            "default": mode == DEFAULT_MODE,
        }
        for mode in SUPPORTED_MODES
    ]

    return jsonify(
        {
            "success": True,
            "modes": items,
            "timeframes": items,
            "default": DEFAULT_MODE,
            "timestamp": now_iso(),
        }
    )


# ============================================================
# ROBOTS / FAVICON / ERRORS
# ============================================================

@app.route("/robots.txt", methods=["GET"])
def robots_txt():
    return (
        "User-agent: *\n"
        "Disallow: /dashboard\n"
        "Disallow: /stock/\n"
        "Disallow: /profile\n"
        "Disallow: /api/\n",
        200,
        {
            "Content-Type": "text/plain; charset=utf-8"
        },
    )


@app.route("/favicon.ico", methods=["GET"])
def favicon():
    return "", 204


@app.errorhandler(404)
def page_not_found(error):
    if request.path.startswith("/api/"):
        return api_error(
            "Requested API route not found.",
            404,
            "not_found",
        )

    return (
        safe_render(
            "error.html",
            FALLBACK_ERROR_HTML,
            page_title="Page Not Found",
            error_title="Page नहीं मिला",
            error_message="Requested URL उपलब्ध नहीं है।",
            back_url=url_for("home"),
        ),
        404,
    )


@app.errorhandler(500)
def internal_server_error(error):
    logger.exception(
        "Internal server error: %s",
        error,
    )

    if request.path.startswith("/api/"):
        return api_error(
            "Internal server error. Check Render logs.",
            500,
            "internal_server_error",
        )

    return (
        safe_render(
            "error.html",
            FALLBACK_ERROR_HTML,
            page_title="Server Error",
            error_title="Internal Server Error",
            error_message=(
                "Application error आया। Render Logs का latest traceback देखें।"
            ),
            back_url=url_for("home"),
        ),
        500,
    )


@app.errorhandler(Exception)
def unexpected_error(error):
    logger.exception(
        "Unexpected application error"
    )

    if request.path.startswith("/api/"):
        return api_error(
            str(error)
            if not IS_PRODUCTION
            else "Unexpected server error.",
            500,
            "unexpected_error",
            error,
        )

    return (
        safe_render(
            "error.html",
            FALLBACK_ERROR_HTML,
            page_title="Application Error",
            error_title="Application Error",
            error_message=(
                str(error)
                if not IS_PRODUCTION
                else (
                    "Unexpected application error. Render Logs check करें।"
                )
            ),
            back_url=url_for("home"),
        ),
        500,
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
