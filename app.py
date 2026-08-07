from __future__ import annotations

import atexit
import fcntl
import os
import threading
from datetime import timedelta
from functools import wraps
from typing import Any, Callable, TypeVar
from urllib.parse import unquote

from apscheduler.schedulers.background import BackgroundScheduler
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from services.cache_service import (
    CacheService,
    get_cache_service,
)
from services.common_stock_engine import (
    rollover_if_new_day,
)
from services.fyers_service import (
    FyersService,
    get_fyers_service,
)
from services.index_service import (
    IndexService,
    get_index_service,
)
from services.market_data_service import (
    MarketDataService,
    get_market_data_service,
)
from services.nse_sector_universe_service import (
    NSESectorUniverseService,
    get_nse_sector_universe_service,
)
from services.scanner_orchestrator import (
    ScannerOrchestrator,
    get_scanner_orchestrator,
)
from services.stock_ranker import (
    get_top_stocks_for_sector,
)
from services.technical_metrics_service import (
    TechnicalMetricsService,
    get_technical_metrics_service,
)
from utils.helpers import (
    clean_text,
    normalize_symbol,
    safe_float,
    safe_int,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_exception,
)


logger = get_logger("app")


# ==========================================================
# FLASK APPLICATION
# ==========================================================

app = Flask(__name__)

app.config.from_object(
    Config
)

app.secret_key = (
    Config.SECRET_KEY
)

app.permanent_session_lifetime = timedelta(
    hours=12
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,

    SESSION_COOKIE_SAMESITE="Lax",

    SESSION_COOKIE_SECURE=(
        os.getenv(
            "SESSION_COOKIE_SECURE",
            "true",
        )
        .strip()
        .lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    ),
)


app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1,
)


# ==========================================================
# SERVICES
# ==========================================================

cache_service: CacheService = (
    get_cache_service()
)

fyers_service: FyersService = (
    get_fyers_service()
)

index_service: IndexService = (
    get_index_service()
)

market_data_service: MarketDataService = (
    get_market_data_service()
)

universe_service: NSESectorUniverseService = (
    get_nse_sector_universe_service()
)

scanner_orchestrator: ScannerOrchestrator = (
    get_scanner_orchestrator()
)

technical_metrics_service: TechnicalMetricsService = (
    get_technical_metrics_service()
)


# ==========================================================
# APPLICATION SETTINGS
# ==========================================================

APP_NAME = Config.APP_NAME

APP_VERSION = Config.APP_VERSION


SUPPORTED_MODES = {
    Config.MODE_INTRADAY: "Intraday",

    Config.MODE_SWING: "Swing",
}


DEFAULT_MODE = (
    Config.normalize_trading_mode(
        os.getenv(
            "DEFAULT_TRADING_MODE",
            Config.DEFAULT_TRADING_MODE,
        )
    )
)


ENABLE_BACKGROUND_SCANNER = (
    os.getenv(
        "ENABLE_BACKGROUND_SCANNER",
        "true",
    )
    .strip()
    .lower()
    in {
        "1",
        "true",
        "yes",
        "on",
    }
)


DEFAULT_BACKGROUND_REFRESH_SECONDS = max(
    60,

    safe_int(
        os.getenv(
            "SCANNER_REFRESH_SECONDS",

            str(
                Config
                .SWING_TECHNICAL_REFRESH_SECONDS
            ),
        ),

        default=(
            Config
            .SWING_TECHNICAL_REFRESH_SECONDS
        ),
    )
    or Config.SWING_TECHNICAL_REFRESH_SECONDS,
)


# ==========================================================
# CACHE KEYS
# ==========================================================

ACCESS_TOKEN_CACHE_KEY = (
    "eagle:active_fyers_access_token"
)

SCAN_RESULT_KEY_PREFIX = (
    "eagle:scan-results:"
)

SCAN_DETAIL_KEY_PREFIX = (
    "eagle:stock-detail:"
)

SCAN_STATUS_CACHE_KEY = (
    "eagle:scanner-status"
)

SECTOR_STOCKS_CACHE_PREFIX = (
    "eagle:sector-top-stocks:"
)


# ==========================================================
# SCANNER STATE
# ==========================================================

scan_lock = threading.RLock()

scheduler_lock_file: Any = None

scheduler: BackgroundScheduler | None = None


scan_state: dict[str, Any] = {
    "running": False,

    "mode": DEFAULT_MODE,

    "stage": "idle",

    "sector_count": 0,

    "candidate_count": 0,

    "common_count": 0,

    "strong_buy_count": 0,

    "progress_percent": 0.0,

    "started_at": None,

    "completed_at": None,

    "last_error": None,

    "updated_at": (
        utc_now().isoformat()
    ),
}


F = TypeVar(
    "F",
    bound=Callable[..., Any],
)


# ==========================================================
# ACCESS TOKEN
# ==========================================================

def get_access_token() -> str:

    token = clean_text(
        session.get(
            "fyers_access_token"
        )
    )

    if token:

        cache_service.set(
            ACCESS_TOKEN_CACHE_KEY,

            token,

            ttl_seconds=(
                12 * 60 * 60
            ),
        )

        return token


    cached_token = clean_text(
        cache_service.get(
            ACCESS_TOKEN_CACHE_KEY,

            default="",
        )
    )

    if cached_token:
        return cached_token


    return clean_text(
        getattr(
            Config,

            "FYERS_ACCESS_TOKEN",

            "",
        )
    )


def get_background_access_token() -> str:

    cached_token = clean_text(
        cache_service.get(
            ACCESS_TOKEN_CACHE_KEY,

            default="",
        )
    )

    if cached_token:
        return cached_token


    return clean_text(
        getattr(
            Config,

            "FYERS_ACCESS_TOKEN",

            "",
        )
    )


def store_access_token(
    access_token: str,
) -> None:

    normalized_token = clean_text(
        access_token
    )

    if not normalized_token:
        return


    session.permanent = True

    session[
        "fyers_access_token"
    ] = normalized_token


    cache_service.set(
        ACCESS_TOKEN_CACHE_KEY,

        normalized_token,

        ttl_seconds=(
            12 * 60 * 60
        ),
    )


def clear_access_token() -> None:

    session.pop(
        "fyers_access_token",
        None,
    )

    session.pop(
        "fyers_profile",
        None,
    )

    cache_service.delete(
        ACCESS_TOKEN_CACHE_KEY
    )

    fyers_service.clear_client_cache()


# ==========================================================
# LOGIN REQUIRED
# ==========================================================

def login_required(
    function: F,
) -> F:

    @wraps(
        function
    )
    def wrapped(
        *args: Any,
        **kwargs: Any,
    ) -> Any:

        if get_access_token():

            return function(
                *args,
                **kwargs,
            )


        if request.path.startswith(
            "/api/"
        ):

            return jsonify(
                {
                    "success": False,

                    "authenticated": False,

                    "error": (
                        "FYERS login is required."
                    ),

                    "login_url": (
                        url_for(
                            "login"
                        )
                    ),
                }
            ), 401


        flash(
            "Please login with FYERS.",
            "warning",
        )


        return redirect(
            url_for(
                "login"
            )
        )

    return wrapped  # type: ignore[return-value]


# ==========================================================
# MODE
# ==========================================================

def request_mode() -> str:

    raw_mode = (
        request.args.get(
            "mode"
        )
        or request.args.get(
            "timeframe"
        )
        or request.form.get(
            "mode"
        )
        or request.form.get(
            "timeframe"
        )
        or DEFAULT_MODE
    )


    return (
        Config
        .normalize_trading_mode(
            raw_mode
        )
    )


# ==========================================================
# CACHE KEY HELPERS
# ==========================================================

def scan_results_cache_key(
    mode: str,
) -> str:

    normalized_mode = (
        Config
        .normalize_trading_mode(
            mode
        )
    )


    return (
        f"{SCAN_RESULT_KEY_PREFIX}"
        f"{normalized_mode}"
    )


def stock_detail_cache_key(
    symbol: str,
    mode: str,
) -> str:

    normalized_symbol = (
        normalize_symbol(
            symbol
        )
    )


    normalized_mode = (
        Config
        .normalize_trading_mode(
            mode
        )
    )


    return (
        f"{SCAN_DETAIL_KEY_PREFIX}"
        f"{normalized_symbol}:"
        f"{normalized_mode}"
    )


def sector_stocks_cache_key(
    sector: str,
    mode: str,
) -> str:

    normalized_mode = (
        Config
        .normalize_trading_mode(
            mode
        )
    )


    normalized_sector = (
        clean_text(
            sector
        )
        .casefold()
        .replace(
            " ",
            "_",
        )
        .replace(
            "&",
            "and",
        )
        .replace(
            "/",
            "_",
        )
    )


    return (
        f"{SECTOR_STOCKS_CACHE_PREFIX}"
        f"{normalized_mode}:"
        f"{normalized_sector}"
    )


# ==========================================================
# SCANNER STATE
# ==========================================================

def update_scan_state(
    **updates: Any,
) -> None:

    with scan_lock:

        scan_state.update(
            updates
        )


        scan_state[
            "updated_at"
        ] = (
            utc_now().isoformat()
        )


        cache_service.set(
            SCAN_STATUS_CACHE_KEY,

            dict(
                scan_state
            ),

            ttl_seconds=(
                24 * 60 * 60
            ),
        )


def get_scan_status() -> dict[str, Any]:

    with scan_lock:

        current_state = dict(
            scan_state
        )


    cached_state = (
        cache_service.get(
            SCAN_STATUS_CACHE_KEY
        )
    )


    if (
        isinstance(
            cached_state,
            dict,
        )
        and not current_state.get(
            "running"
        )
    ):

        return {
            **cached_state,

            "running": False,
        }


    return current_state


# ==========================================================
# TRADING DAY ROLLOVER
# ==========================================================

def prepare_trading_day(
    mode: str,
) -> bool:

    normalized_mode = (
        Config
        .normalize_trading_mode(
            mode
        )
    )


    try:

        archived = (
            rollover_if_new_day(
                mode=(
                    normalized_mode
                )
            )
        )


        if archived:

            logger.info(
                (
                    "Trading-day rollover "
                    "completed for %s."
                ),

                normalized_mode,

                extra=build_log_extra(
                    component="app",

                    event=(
                        "candidate_day_rollover"
                    ),

                    status="success",

                    mode=(
                        normalized_mode
                    ),
                ),
            )


        return archived


    except Exception as exception:

        logger.warning(
            (
                "Trading-day rollover "
                "failed for %s: %s"
            ),

            normalized_mode,

            exception,
        )


        return False


# ==========================================================
# BENCHMARK
# ==========================================================

def get_nifty_change_percent(
    access_token: str,
) -> float:

    try:

        response = (
            fyers_service
            .get_quotes(
                access_token,

                "NSE:NIFTY50-INDEX",
            )
        )


        rows = response.get(
            "d",
            [],
        )


        if not isinstance(
            rows,
            list,
        ):

            return 0.0


        for item in rows:

            if not isinstance(
                item,
                dict,
            ):
                continue


            values = item.get(
                "v",
                {},
            )


            if not isinstance(
                values,
                dict,
            ):
                continue


            change_percent = safe_float(
                values.get(
                    "chp"
                )
                or values.get(
                    "change_percent"
                )
            )


            if change_percent is not None:

                return float(
                    change_percent
                )


    except Exception as exception:

        logger.warning(
            (
                "Nifty benchmark quote "
                "unavailable: %s"
            ),

            exception,
        )


    return 0.0


# ==========================================================
# STRONG BUY SYMBOLS
# ==========================================================

def get_cached_strong_buy_symbols(
    mode: str,
) -> set[str]:

    payload = (
        cache_service.get(
            scan_results_cache_key(
                mode
            ),

            default={},
        )
    )


    if not isinstance(
        payload,
        dict,
    ):
        return set()


    results = payload.get(
        "results",
        [],
    )


    if not isinstance(
        results,
        list,
    ):
        return set()


    symbols: set[str] = set()


    for item in results:

        if not isinstance(
            item,
            dict,
        ):
            continue


        signal = clean_text(
            item.get(
                "signal"
            )
        ).upper()


        if signal != "STRONG BUY":
            continue


        symbol = normalize_symbol(
            item.get(
                "symbol"
            )
        )


        if symbol:

            symbols.add(
                symbol
            )


    return symbols


# ==========================================================
# TOP STOCKS OF ONE SECTOR
# ==========================================================

def build_sector_top_stocks(
    access_token: str,
    *,
    sector: str,
    mode: str,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:

    normalized_sector = clean_text(
        sector
    )


    normalized_mode = (
        Config
        .normalize_trading_mode(
            mode
        )
    )


    if not normalized_sector:

        raise ValueError(
            "Sector name is required."
        )


    if not clean_text(
        access_token
    ):

        raise ValueError(
            "FYERS access token is required."
        )


    cache_key = (
        sector_stocks_cache_key(
            normalized_sector,

            normalized_mode,
        )
    )


    if not force_refresh:

        cached = (
            cache_service.get(
                cache_key
            )
        )


        if isinstance(
            cached,
            list,
        ):

            return [
                dict(
                    item
                )

                for item
                in cached

                if isinstance(
                    item,
                    dict,
                )
            ]


    # ------------------------------------------------------
    # GET ALL STOCKS OF THIS SECTOR
    # ------------------------------------------------------

    sector_stocks = (
        universe_service
        .get_stocks_for_sector(
            normalized_sector,

            force_refresh=False,
        )
    )


    if not sector_stocks:

        raise RuntimeError(
            (
                "No stocks were found "
                f"for sector: "
                f"{normalized_sector}"
            )
        )


    # ------------------------------------------------------
    # BENCHMARK
    # ------------------------------------------------------

    benchmark_change_pct = (
        get_nifty_change_percent(
            access_token
        )
    )


    # ------------------------------------------------------
    # TECHNICAL METRICS
    # ------------------------------------------------------

    metrics_by_symbol = (
        technical_metrics_service
        .build_metrics_for_stocks(
            access_token,

            sector_stocks,

            mode=(
                normalized_mode
            ),

            benchmark_change_pct=(
                benchmark_change_pct
            ),

            force_refresh=(
                force_refresh
            ),
        )
    )


    if not metrics_by_symbol:

        raise RuntimeError(
            (
                "Verified technical metrics "
                "are unavailable for "
                f"{normalized_sector}."
            )
        )


    # ------------------------------------------------------
    # TOP 10 STOCKS
    #
    # Important:
    # Strong Buy is NOT required here.
    # Every selected sector shows Top 10 ranked stocks.
    # ------------------------------------------------------

    ranked_stocks = (
        get_top_stocks_for_sector(
            sector=(
                normalized_sector
            ),

            stocks=(
                sector_stocks
            ),

            metrics_by_symbol=(
                metrics_by_symbol
            ),

            limit=(
                Config
                .TOP_STOCKS_PER_SECTOR
            ),
        )
    )


    if not ranked_stocks:

        raise RuntimeError(
            (
                "No technically ranked "
                "stocks were produced for "
                f"{normalized_sector}."
            )
        )


    # ------------------------------------------------------
    # FINAL STRONG BUY SYMBOLS
    # ------------------------------------------------------

    strong_buy_symbols = (
        get_cached_strong_buy_symbols(
            normalized_mode
        )
    )


    output: list[
        dict[str, Any]
    ] = []


    for (
        position,
        ranked_stock,
    ) in enumerate(
        ranked_stocks,

        start=1,
    ):

        item = (
            ranked_stock
            .to_dict()
        )


        symbol = normalize_symbol(
            ranked_stock.symbol
        )


        metrics = (
            metrics_by_symbol.get(
                symbol,
                {},
            )
        )


        if not isinstance(
            metrics,
            dict,
        ):

            metrics = {}


        is_strong_buy = (
            symbol
            in strong_buy_symbols
        )


        item.update(
            {
                "rank": (
                    position
                ),

                "symbol": (
                    symbol
                ),

                "company_name": (
                    ranked_stock
                    .company_name
                ),

                "sector": (
                    ranked_stock
                    .sector
                ),

                "mode": (
                    normalized_mode
                ),

                "strong_buy": (
                    bool(
                        is_strong_buy
                    )
                ),

                "signal": (
                    "STRONG BUY"
                    if is_strong_buy
                    else "RANKED"
                ),

                "qualified_for_eagle_scanner": (
                    bool(
                        is_strong_buy
                    )
                ),

                "current_price": round(
                    safe_float(
                        metrics.get(
                            "current_price"
                        ),

                        default=0.0,
                    )
                    or 0.0,

                    2,
                ),

                "rsi": round(
                    safe_float(
                        metrics.get(
                            "rsi"
                        ),

                        default=0.0,
                    )
                    or 0.0,

                    2,
                ),

                "volume_ratio": round(
                    safe_float(
                        metrics.get(
                            "volume_ratio"
                        ),

                        default=0.0,
                    )
                    or 0.0,

                    2,
                ),

                "change_1d_pct": round(
                    safe_float(
                        metrics.get(
                            "change_1d_pct"
                        ),

                        default=0.0,
                    )
                    or 0.0,

                    2,
                ),

                "change_5d_pct": round(
                    safe_float(
                        metrics.get(
                            "change_5d_pct"
                        ),

                        default=0.0,
                    )
                    or 0.0,

                    2,
                ),

                "change_20d_pct": round(
                    safe_float(
                        metrics.get(
                            "change_20d_pct"
                        ),

                        default=0.0,
                    )
                    or 0.0,

                    2,
                ),

                "relative_strength_pct": round(
                    safe_float(
                        metrics.get(
                            "relative_strength_pct"
                        ),

                        default=0.0,
                    )
                    or 0.0,

                    2,
                ),

                "ema20": round(
                    safe_float(
                        metrics.get(
                            "ema20"
                        ),

                        default=0.0,
                    )
                    or 0.0,

                    2,
                ),

                "ema50": round(
                    safe_float(
                        metrics.get(
                            "ema50"
                        ),

                        default=0.0,
                    )
                    or 0.0,

                    2,
                ),

                "ema200": round(
                    safe_float(
                        metrics.get(
                            "ema200"
                        ),

                        default=0.0,
                    )
                    or 0.0,

                    2,
                ),

                "above_ema20": bool(
                    metrics.get(
                        "above_ema20",
                        False,
                    )
                ),

                "above_ema50": bool(
                    metrics.get(
                        "above_ema50",
                        False,
                    )
                ),

                "above_ema200": bool(
                    metrics.get(
                        "above_ema200",
                        False,
                    )
                ),

                "bullish": bool(
                    metrics.get(
                        "bullish",
                        False,
                    )
                ),

                "verified": True,

                "source": "FYERS",
            }
        )


        output.append(
            item
        )


    cache_service.set(
        cache_key,

        output,

        ttl_seconds=(
            60
            if normalized_mode
            == Config.MODE_INTRADAY
            else 300
        ),
    )


    return output


# ==========================================================
# BACKGROUND SCANNER
# ==========================================================

def run_background_scan(
    mode: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:

    normalized_mode = (
        Config
        .normalize_trading_mode(
            mode
            or DEFAULT_MODE
        )
    )


    access_token = (
        get_background_access_token()
    )


    if not access_token:

        update_scan_state(
            running=False,

            mode=(
                normalized_mode
            ),

            stage=(
                "authentication_required"
            ),

            last_error=(
                "FYERS login is required."
            ),

            completed_at=(
                utc_now()
                .isoformat()
            ),
        )


        return {
            "success": False,

            "error": (
                "FYERS login is required."
            ),
        }


    with scan_lock:

        if scan_state.get(
            "running"
        ):

            return {
                "success": False,

                "error": (
                    "Scanner is already running."
                ),
            }


        scan_state[
            "running"
        ] = True


    update_scan_state(
        running=True,

        mode=(
            normalized_mode
        ),

        stage="starting",

        sector_count=0,

        candidate_count=0,

        common_count=0,

        strong_buy_count=0,

        progress_percent=5.0,

        started_at=(
            utc_now()
            .isoformat()
        ),

        completed_at=None,

        last_error=None,
    )


    try:

        # --------------------------------------------------
        # STEP 1
        # --------------------------------------------------

        update_scan_state(
            stage=(
                "trading_day_check"
            ),

            progress_percent=8.0,
        )


        prepare_trading_day(
            normalized_mode
        )


        # --------------------------------------------------
        # STEP 2
        # --------------------------------------------------

        update_scan_state(
            stage="benchmark",

            progress_percent=12.0,
        )


        benchmark_change_pct = (
            get_nifty_change_percent(
                access_token
            )
        )


        # --------------------------------------------------
        # STEP 3
        # --------------------------------------------------

        update_scan_state(
            stage=(
                "sector_and_stock_ranking"
            ),

            progress_percent=20.0,
        )


        result = (
            scanner_orchestrator
            .run_scan(
                access_token,

                mode=(
                    normalized_mode
                ),

                benchmark_change_pct=(
                    benchmark_change_pct
                ),

                force_refresh=(
                    force_refresh
                ),
            )
        )


        top_sectors = (
            result.get(
                "top_sectors",
                [],
            )
        )


        strong_buy_results = (
            result.get(
                "results",
                [],
            )
        )


        if not isinstance(
            top_sectors,
            list,
        ):

            top_sectors = []


        if not isinstance(
            strong_buy_results,
            list,
        ):

            strong_buy_results = []


        strong_buy_results = [
            item

            for item
            in strong_buy_results

            if (
                isinstance(
                    item,
                    dict,
                )

                and clean_text(
                    item.get(
                        "signal"
                    )
                ).upper()
                == "STRONG BUY"
            )
        ]


        strong_buy_results.sort(
            key=lambda item: (
                -(
                    safe_float(
                        item.get(
                            "technical_score"
                        ),

                        default=0.0,
                    )
                    or 0.0
                ),

                -(
                    safe_float(
                        item.get(
                            "risk_reward"
                        ),

                        default=0.0,
                    )
                    or 0.0
                ),

                clean_text(
                    item.get(
                        "symbol"
                    )
                ),
            )
        )


        candidate_count = (
            safe_int(
                result.get(
                    "candidate_count"
                ),

                default=0,
            )
            or 0
        )


        common_count = (
            safe_int(
                result.get(
                    "common_count"
                ),

                default=0,
            )
            or 0
        )


        payload = {
            "success": True,

            "mode": (
                normalized_mode
            ),

            "timeframe": (
                normalized_mode
            ),

            "top_sectors": (
                top_sectors
            ),

            "sector_count": (
                len(
                    top_sectors
                )
            ),

            "candidate_count": (
                candidate_count
            ),

            "common_count": (
                common_count
            ),

            "strong_buy_count": (
                len(
                    strong_buy_results
                )
            ),

            "results": (
                strong_buy_results
            ),

            "benchmark_change_pct": (
                benchmark_change_pct
            ),

            "generated_at": (
                utc_now()
                .isoformat()
            ),

            "verified": True,

            "technical_only": True,

            "fixed_nifty500": False,

            "source": "FYERS",
        }


        cache_service.set(
            scan_results_cache_key(
                normalized_mode
            ),

            payload,

            ttl_seconds=max(
                (
                    Config
                    .SECTOR_SCAN_REFRESH_SECONDS
                    * 2
                ),

                1800,
            ),
        )


        update_scan_state(
            running=False,

            mode=(
                normalized_mode
            ),

            stage="completed",

            sector_count=(
                len(
                    top_sectors
                )
            ),

            candidate_count=(
                candidate_count
            ),

            common_count=(
                common_count
            ),

            strong_buy_count=(
                len(
                    strong_buy_results
                )
            ),

            progress_percent=100.0,

            completed_at=(
                utc_now()
                .isoformat()
            ),

            last_error=None,
        )


        logger.info(
            (
                "Eagle scan completed | "
                "mode=%s | "
                "sectors=%s | "
                "candidates=%s | "
                "common=%s | "
                "strong_buy=%s"
            ),

            normalized_mode,

            len(
                top_sectors
            ),

            candidate_count,

            common_count,

            len(
                strong_buy_results
            ),

            extra=build_log_extra(
                component="app",

                event=(
                    "background_scan_completed"
                ),

                status="success",

                mode=(
                    normalized_mode
                ),

                sector_count=(
                    len(
                        top_sectors
                    )
                ),

                candidate_count=(
                    candidate_count
                ),

                common_count=(
                    common_count
                ),

                strong_buy_count=(
                    len(
                        strong_buy_results
                    )
                ),
            ),
        )


        return payload


    except Exception as exception:

        log_exception(
            logger,

            (
                "Eagle background "
                "scan failed"
            ),

            exception=(
                exception
            ),

            component="app",

            error_code=(
                "BACKGROUND_SCAN_FAILED"
            ),

            mode=(
                normalized_mode
            ),
        )


        update_scan_state(
            running=False,

            mode=(
                normalized_mode
            ),

            stage="failed",

            completed_at=(
                utc_now()
                .isoformat()
            ),

            last_error=(
                str(
                    exception
                )
            ),

            progress_percent=0.0,
        )


        return {
            "success": False,

            "mode": (
                normalized_mode
            ),

            "error": (
                str(
                    exception
                )
            ),
        }


# ==========================================================
# SCAN THREAD
# ==========================================================

def start_scan_thread(
    mode: str,
    force_refresh: bool = False,
) -> bool:

    normalized_mode = (
        Config
        .normalize_trading_mode(
            mode
        )
    )


    with scan_lock:

        if scan_state.get(
            "running"
        ):

            return False


    scan_thread = (
        threading.Thread(
            target=(
                run_background_scan
            ),

            kwargs={
                "mode": (
                    normalized_mode
                ),

                "force_refresh": (
                    force_refresh
                ),
            },

            daemon=True,

            name=(
                f"eagle-scan-"
                f"{normalized_mode}"
            ),
        )
    )


    try:

        scan_thread.start()

        return True


    except Exception as exception:

        log_exception(
            logger,

            (
                "Unable to start "
                "scanner thread"
            ),

            exception=(
                exception
            ),

            component="app",

            error_code=(
                "SCAN_THREAD_START_FAILED"
            ),

            mode=(
                normalized_mode
            ),
        )


        update_scan_state(
            running=False,

            mode=(
                normalized_mode
            ),

            stage="failed",

            last_error=(
                str(
                    exception
                )
            ),

            completed_at=(
                utc_now()
                .isoformat()
            ),
        )


        return False


# ==========================================================
# SCHEDULER
# ==========================================================

def acquire_scheduler_lock() -> bool:

    global scheduler_lock_file


    try:

        scheduler_lock_file = open(
            "/tmp/eagle-smart-scanner.lock",

            "w",

            encoding="utf-8",
        )


        fcntl.flock(
            scheduler_lock_file,

            fcntl.LOCK_EX
            | fcntl.LOCK_NB,
        )


        scheduler_lock_file.write(
            str(
                os.getpid()
            )
        )


        scheduler_lock_file.flush()


        return True


    except (
        BlockingIOError,
        OSError,
    ):

        return False


def scheduled_default_scan() -> None:

    run_background_scan(
        mode=(
            DEFAULT_MODE
        ),

        force_refresh=False,
    )


def start_scheduler() -> None:

    global scheduler


    if not ENABLE_BACKGROUND_SCANNER:

        logger.info(
            (
                "Background scanner "
                "is disabled."
            )
        )

        return


    if not acquire_scheduler_lock():

        logger.info(
            (
                "Scheduler already running "
                "in another worker."
            )
        )

        return


    scheduler = BackgroundScheduler(
        timezone=(
            Config
            .MARKET_TIMEZONE
        ),

        daemon=True,
    )


    scheduler.add_job(
        scheduled_default_scan,

        trigger="interval",

        seconds=(
            DEFAULT_BACKGROUND_REFRESH_SECONDS
        ),

        id=(
            "eagle-default-scan"
        ),

        replace_existing=True,

        max_instances=1,

        coalesce=True,
    )


    scheduler.start()


    logger.info(
        (
            "Eagle background scheduler "
            "started | mode=%s | "
            "interval=%ss"
        ),

        DEFAULT_MODE,

        DEFAULT_BACKGROUND_REFRESH_SECONDS,

        extra=build_log_extra(
            component="app",

            event=(
                "scheduler_started"
            ),

            status="success",

            mode=(
                DEFAULT_MODE
            ),
        ),
    )


def stop_scheduler() -> None:

    global scheduler

    global scheduler_lock_file


    if scheduler is not None:

        try:

            scheduler.shutdown(
                wait=False
            )

        except Exception:
            pass


        scheduler = None


    if scheduler_lock_file is not None:

        try:

            fcntl.flock(
                scheduler_lock_file,

                fcntl.LOCK_UN,
            )


            scheduler_lock_file.close()


        except Exception:
            pass


        scheduler_lock_file = None


atexit.register(
    stop_scheduler
)


# ==========================================================
# TEMPLATE CONTEXT
# ==========================================================

@app.context_processor
def inject_global_template_data(
) -> dict[str, Any]:

    return {
        "app_name": (
            APP_NAME
        ),

        "app_version": (
            APP_VERSION
        ),

        "supported_modes": (
            SUPPORTED_MODES
        ),

        "supported_timeframes": (
            SUPPORTED_MODES
        ),

        "default_mode": (
            DEFAULT_MODE
        ),

        "default_timeframe": (
            DEFAULT_MODE
        ),

        "current_year": (
            utc_now()
            .year
        ),
    }


# ==========================================================
# HOME
# ==========================================================

@app.route("/")
def home() -> Any:

    if get_access_token():

        return redirect(
            url_for(
                "dashboard"
            )
        )


    return redirect(
        url_for(
            "login"
        )
    )


# ==========================================================
# LOGIN
# ==========================================================

@app.route("/login")
def login() -> Any:

    if get_access_token():

        return redirect(
            url_for(
                "dashboard"
            )
        )


    configuration = (
        fyers_service
        .configuration_status()
    )


    login_url = ""


    if configuration.get(
        "configured"
    ):

        try:

            login_url = (
                fyers_service
                .generate_login_url()
            )


        except Exception as exception:

            flash(
                str(
                    exception
                ),

                "error",
            )


    return render_template(
        "login.html",

        configuration=(
            configuration
        ),

        login_url=(
            login_url
        ),
    )


# ==========================================================
# CALLBACK
# ==========================================================

@app.route("/callback")
@app.route("/auth/callback")
def fyers_callback() -> Any:

    auth_code = clean_text(
        request.args.get(
            "auth_code"
        )

        or request.args.get(
            "code"
        )
    )


    callback_error = clean_text(
        request.args.get(
            "error"
        )

        or request.args.get(
            "error_description"
        )
    )


    if callback_error:

        flash(
            (
                "FYERS login failed: "
                f"{callback_error}"
            ),

            "error",
        )


        return redirect(
            url_for(
                "login"
            )
        )


    if not auth_code:

        flash(
            (
                "FYERS authorization code "
                "was not received."
            ),

            "error",
        )


        return redirect(
            url_for(
                "login"
            )
        )


    token_result = (
        fyers_service
        .exchange_auth_code(
            auth_code
        )
    )


    if (
        not token_result.success

        or not token_result.access_token
    ):

        flash(
            (
                token_result.message

                or "FYERS login failed."
            ),

            "error",
        )


        return redirect(
            url_for(
                "login"
            )
        )


    store_access_token(
        token_result.access_token
    )


    token_status = (
        fyers_service
        .validate_access_token(
            token_result
            .access_token
        )
    )


    if not token_status.get(
        "valid"
    ):

        clear_access_token()


        flash(
            (
                "FYERS token verification "
                "failed."
            ),

            "error",
        )


        return redirect(
            url_for(
                "login"
            )
        )


    session[
        "fyers_profile"
    ] = token_status.get(
        "profile",

        {},
    )


    flash(
        (
            "FYERS login successful. "
            "Eagle Smart Scanner is ready."
        ),

        "success",
    )


    start_scan_thread(
        DEFAULT_MODE
    )


    return redirect(
        url_for(
            "dashboard"
        )
    )


# ==========================================================
# LOGOUT
# ==========================================================

@app.route("/logout")
def logout() -> Any:

    clear_access_token()


    update_scan_state(
        running=False,

        stage="idle",
    )


    flash(
        (
            "You have been "
            "logged out."
        ),

        "success",
    )


    return redirect(
        url_for(
            "login"
        )
    )


# ==========================================================
# DASHBOARD
# ==========================================================

@app.route("/dashboard")
@login_required
def dashboard() -> Any:

    mode = (
        request_mode()
    )


    cached_payload = (
        cache_service.get(
            scan_results_cache_key(
                mode
            ),

            default={},
        )
    )


    initial_results: list[
        dict[str, Any]
    ] = []


    top_sectors: list[
        dict[str, Any]
    ] = []


    if isinstance(
        cached_payload,
        dict,
    ):

        results = (
            cached_payload.get(
                "results",

                [],
            )
        )


        if isinstance(
            results,
            list,
        ):

            initial_results = [
                item

                for item
                in results

                if isinstance(
                    item,
                    dict,
                )
            ]


        cached_sectors = (
            cached_payload.get(
                "top_sectors",

                [],
            )
        )


        if isinstance(
            cached_sectors,
            list,
        ):

            top_sectors = [
                item

                for item
                in cached_sectors

                if isinstance(
                    item,
                    dict,
                )
            ]


    try:

        sectors = (
            universe_service
            .get_sector_names()
        )


    except Exception as exception:

        logger.warning(
            (
                "Unable to load "
                "dashboard sectors: %s"
            ),

            exception,
        )


        sectors = []


    return render_template(
        "dashboard.html",

        mode=(
            mode
        ),

        timeframe=(
            mode
        ),

        initial_results=(
            initial_results
        ),

        sectors=(
            sectors
        ),

        top_sectors=(
            top_sectors
        ),

        scanner_status=(
            get_scan_status()
        ),

        profile=(
            session.get(
                "fyers_profile",

                {},
            )
        ),
    )


# ==========================================================
# STOCK DETAIL PAGE
# ==========================================================

@app.route(
    "/stock/<symbol>"
)
@login_required
def stock_detail_page(
    symbol: str,
) -> Any:

    normalized_symbol = (
        normalize_symbol(
            symbol
        )
    )


    mode = (
        request_mode()
    )


    detail = (
        cache_service.get(
            stock_detail_cache_key(
                normalized_symbol,

                mode,
            ),

            default={},
        )
    )


    return render_template(
        "stock_detail.html",

        symbol=(
            normalized_symbol
        ),

        mode=(
            mode
        ),

        timeframe=(
            mode
        ),

        stock_detail=(
            detail
        ),
    )


# ==========================================================
# PRIVACY
# ==========================================================

@app.route("/privacy")
def privacy() -> Any:

    return render_template(
        "privacy.html"
    )


# ==========================================================
# INDICES API
# ==========================================================

@app.route("/api/indices")
@login_required
def api_indices() -> Any:

    access_token = (
        get_access_token()
    )


    try:

        indices = (
            index_service
            .get_dashboard_indices(
                access_token,

                force_refresh=False,

                allow_stale_on_error=True,
            )
        )


        return jsonify(
            {
                "success": True,

                "indices": (
                    indices
                ),

                "total": (
                    len(
                        indices
                    )
                ),

                "updated_at": (
                    utc_now()
                    .isoformat()
                ),
            }
        )


    except Exception as exception:

        return jsonify(
            {
                "success": False,

                "indices": [],

                "error": (
                    str(
                        exception
                    )
                ),

                "updated_at": (
                    utc_now()
                    .isoformat()
                ),
            }
        ), 503


# ==========================================================
# SIGNALS API
# ==========================================================

@app.route("/api/signals")
@login_required
def api_signals() -> Any:

    mode = (
        request_mode()
    )


    payload = (
        cache_service.get(
            scan_results_cache_key(
                mode
            ),

            default=None,
        )
    )


    if not isinstance(
        payload,
        dict,
    ):

        started = (
            start_scan_thread(
                mode
            )
        )


        return jsonify(
            {
                "success": True,

                "results": [],

                "total_results": 0,

                "mode": (
                    mode
                ),

                "timeframe": (
                    mode
                ),

                "scan_started": (
                    started
                ),

                "scanner_status": (
                    get_scan_status()
                ),

                "message": (
                    "Verified technical scan "
                    "is being prepared."
                ),
            }
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


    results = [
        item

        for item
        in results

        if (
            isinstance(
                item,
                dict,
            )

            and clean_text(
                item.get(
                    "signal"
                )
            ).upper()
            == "STRONG BUY"
        )
    ]


    sector_filter = clean_text(
        request.args.get(
            "sector"
        )
    )


    if sector_filter:

        results = [
            item

            for item
            in results

            if clean_text(
                item.get(
                    "sector"
                )
            ).casefold()
            == sector_filter.casefold()
        ]


    minimum_score = safe_float(
        request.args.get(
            "minimum_score"
        )

        or request.args.get(
            "score"
        ),

        default=None,
    )


    if minimum_score is not None:

        results = [
            item

            for item
            in results

            if (
                safe_float(
                    item.get(
                        "technical_score"
                    ),

                    default=0.0,
                )
                or 0.0
            )
            >= minimum_score
        ]


    chart_pattern = clean_text(
        request.args.get(
            "pattern"
        )
    )


    if chart_pattern:

        results = [
            item

            for item
            in results

            if clean_text(
                item.get(
                    "chart_pattern"
                )
            ).casefold()
            == chart_pattern.casefold()
        ]


    results.sort(
        key=lambda item: (
            -(
                safe_float(
                    item.get(
                        "technical_score"
                    ),

                    default=0.0,
                )
                or 0.0
            ),

            -(
                safe_float(
                    item.get(
                        "risk_reward"
                    ),

                    default=0.0,
                )
                or 0.0
            ),

            clean_text(
                item.get(
                    "symbol"
                )
            ),
        )
    )


    return jsonify(
        {
            "success": True,

            "results": (
                results
            ),

            "total_results": (
                len(
                    results
                )
            ),

            "mode": (
                mode
            ),

            "timeframe": (
                mode
            ),

            "top_sectors": (
                payload.get(
                    "top_sectors",

                    [],
                )
            ),

            "candidate_count": (
                payload.get(
                    "candidate_count",

                    0,
                )
            ),

            "common_count": (
                payload.get(
                    "common_count",

                    0,
                )
            ),

            "strong_buy_count": (
                len(
                    results
                )
            ),

            "generated_at": (
                payload.get(
                    "generated_at"
                )
            ),

            "scanner_status": (
                get_scan_status()
            ),
        }
    )


# ==========================================================
# SEARCH API
# ==========================================================

@app.route("/api/search")
@login_required
def api_search() -> Any:

    query = clean_text(
        request.args.get(
            "q"
        )
    )


    if not query:

        return jsonify(
            {
                "success": True,

                "query": "",

                "results": [],

                "total": 0,
            }
        )


    try:

        results = (
            universe_service
            .search_stocks(
                query,

                limit=20,
            )
        )


        return jsonify(
            {
                "success": True,

                "query": (
                    query
                ),

                "results": (
                    results
                ),

                "total": (
                    len(
                        results
                    )
                ),
            }
        )


    except Exception as exception:

        return jsonify(
            {
                "success": False,

                "query": (
                    query
                ),

                "results": [],

                "total": 0,

                "error": (
                    str(
                        exception
                    )
                ),
            }
        ), 503


# ==========================================================
# SECTOR TOP STOCKS RESPONSE
# ==========================================================

def _sector_top_stocks_response(
    *,
    sector: str,
) -> Any:

    access_token = (
        get_access_token()
    )


    mode = (
        request_mode()
    )


    force_refresh = (
        request.args.get(
            "refresh",

            "false",
        )
        .strip()
        .lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )


    if not sector:

        return jsonify(
            {
                "success": False,

                "error": (
                    "Sector name is required."
                ),
            }
        ), 400


    try:

        stocks = (
            build_sector_top_stocks(
                access_token,

                sector=(
                    sector
                ),

                mode=(
                    mode
                ),

                force_refresh=(
                    force_refresh
                ),
            )
        )


        strong_buy_count = sum(
            1

            for item
            in stocks

            if bool(
                item.get(
                    "strong_buy"
                )
            )
        )


        return jsonify(
            {
                "success": True,

                "sector": (
                    sector
                ),

                "mode": (
                    mode
                ),

                "timeframe": (
                    mode
                ),

                "stocks": (
                    stocks
                ),

                "results": (
                    stocks
                ),

                "total": (
                    len(
                        stocks
                    )
                ),

                "strong_buy_count": (
                    strong_buy_count
                ),

                "top_limit": (
                    Config
                    .TOP_STOCKS_PER_SECTOR
                ),

                "generated_at": (
                    utc_now()
                    .isoformat()
                ),
            }
        )


    except Exception as exception:

        log_exception(
            logger,

            (
                "Sector Top Stocks "
                "generation failed"
            ),

            exception=(
                exception
            ),

            component="app",

            error_code=(
                "SECTOR_TOP_STOCKS_FAILED"
            ),

            mode=(
                mode
            ),

            sector=(
                sector
            ),
        )


        return jsonify(
            {
                "success": False,

                "sector": (
                    sector
                ),

                "mode": (
                    mode
                ),

                "stocks": [],

                "results": [],

                "total": 0,

                "error": (
                    str(
                        exception
                    )
                ),
            }
        ), 503


# ==========================================================
# SECTOR TOP STOCKS PATH API
# ==========================================================

@app.route(
    "/api/sector/<path:sector_name>/stocks"
)
@login_required
def api_sector_top_stocks(
    sector_name: str,
) -> Any:

    sector = clean_text(
        unquote(
            sector_name
        )
    )


    return (
        _sector_top_stocks_response(
            sector=(
                sector
            )
        )
    )


# ==========================================================
# SECTOR TOP STOCKS QUERY API
# ==========================================================

@app.route(
    "/api/sector-stocks"
)
@login_required
def api_sector_stocks_query() -> Any:

    sector = clean_text(
        request.args.get(
            "sector"
        )
    )


    return (
        _sector_top_stocks_response(
            sector=(
                sector
            )
        )
    )


# ==========================================================
# STOCK DETAIL API
# ==========================================================

@app.route(
    "/api/stock/<symbol>"
)
@login_required
def api_stock_detail(
    symbol: str,
) -> Any:

    access_token = (
        get_access_token()
    )


    normalized_symbol = (
        normalize_symbol(
            symbol
        )
    )


    mode = (
        request_mode()
    )


    force_refresh = (
        request.args.get(
            "refresh",

            "false",
        )
        .strip()
        .lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )


    if not normalized_symbol:

        return jsonify(
            {
                "success": False,

                "error": (
                    "Invalid stock symbol."
                ),
            }
        ), 400


    try:

        stock = (
            universe_service
            .find_stock(
                normalized_symbol
            )
        )


    except Exception as exception:

        return jsonify(
            {
                "success": False,

                "error": (
                    str(
                        exception
                    )
                ),
            }
        ), 503


    if stock is None:

        return jsonify(
            {
                "success": False,

                "error": (
                    "Stock is not available "
                    "in the current NSE "
                    "sector universe."
                ),
            }
        ), 404


    cache_key = (
        stock_detail_cache_key(
            normalized_symbol,

            mode,
        )
    )


    if not force_refresh:

        cached = (
            cache_service.get(
                cache_key
            )
        )


        if (
            isinstance(
                cached,
                dict,
            )

            and cached
        ):

            return jsonify(
                {
                    "success": True,

                    "stock": (
                        cached
                    ),

                    "cached": True,
                }
            )


    try:

        benchmark_change_pct = (
            get_nifty_change_percent(
                access_token
            )
        )


        result = (
            market_data_service
            .analyze_stock(
                access_token,

                normalized_symbol,

                sector=(
                    stock.sector
                ),

                mode=(
                    mode
                ),

                benchmark_change_pct=(
                    benchmark_change_pct
                ),

                force_refresh=(
                    force_refresh
                ),
            )
        )


        if not isinstance(
            result,
            dict,
        ):

            raise RuntimeError(
                (
                    "Technical analysis "
                    "returned invalid data."
                )
            )


        result[
            "company_name"
        ] = (
            stock.company_name
        )


        result[
            "sector"
        ] = (
            stock.sector
        )


        result[
            "qualified_for_eagle_scanner"
        ] = (
            clean_text(
                result.get(
                    "signal"
                )
            ).upper()
            == "STRONG BUY"
        )


        cache_service.set(
            cache_key,

            result,

            ttl_seconds=(
                300
                if mode
                == Config.MODE_SWING
                else 60
            ),
        )


        return jsonify(
            {
                "success": True,

                "stock": (
                    result
                ),

                "cached": False,
            }
        )


    except Exception as exception:

        log_exception(
            logger,

            (
                "Stock technical "
                "analysis failed"
            ),

            exception=(
                exception
            ),

            symbol=(
                normalized_symbol
            ),

            component="app",

            error_code=(
                "STOCK_DETAIL_FAILED"
            ),

            mode=(
                mode
            ),
        )


        return jsonify(
            {
                "success": False,

                "symbol": (
                    normalized_symbol
                ),

                "mode": (
                    mode
                ),

                "error": (
                    str(
                        exception
                    )
                ),
            }
        ), 503


# ==========================================================
# SCAN STATUS API
# ==========================================================

@app.route(
    "/api/scan/status"
)
@login_required
def api_scan_status() -> Any:

    return jsonify(
        {
            "success": True,

            "scanner": (
                get_scan_status()
            ),
        }
    )


# ==========================================================
# MANUAL SCAN REFRESH
# ==========================================================

@app.route(
    "/api/scan/refresh",

    methods=[
        "POST"
    ],
)
@login_required
def api_scan_refresh() -> Any:

    request_data = (
        request.get_json(
            silent=True
        )

        or {}
    )


    mode = (
        Config
        .normalize_trading_mode(
            request_data.get(
                "mode"
            )

            or request_data.get(
                "timeframe"
            )

            or request.form.get(
                "mode"
            )

            or request.form.get(
                "timeframe"
            )

            or DEFAULT_MODE
        )
    )


    started = (
        start_scan_thread(
            mode,

            force_refresh=True,
        )
    )


    if not started:

        return jsonify(
            {
                "success": False,

                "error": (
                    "Scanner is already running."
                ),

                "scanner": (
                    get_scan_status()
                ),
            }
        ), 409


    return jsonify(
        {
            "success": True,

            "message": (
                "Technical scan started."
            ),

            "mode": (
                mode
            ),

            "timeframe": (
                mode
            ),

            "scanner": (
                get_scan_status()
            ),
        }
    ), 202


# ==========================================================
# SECTORS API
# ==========================================================

@app.route("/api/sectors")
@login_required
def api_sectors() -> Any:

    try:

        sectors = (
            universe_service
            .get_sector_names()
        )


        return jsonify(
            {
                "success": True,

                "sectors": (
                    sectors
                ),

                "total": (
                    len(
                        sectors
                    )
                ),
            }
        )


    except Exception as exception:

        return jsonify(
            {
                "success": False,

                "sectors": [],

                "total": 0,

                "error": (
                    str(
                        exception
                    )
                ),
            }
        ), 503


# ==========================================================
# TOP SECTORS API
# ==========================================================

@app.route(
    "/api/top-sectors"
)
@login_required
def api_top_sectors() -> Any:

    mode = (
        request_mode()
    )


    payload = (
        cache_service.get(
            scan_results_cache_key(
                mode
            ),

            default={},
        )
    )


    if not isinstance(
        payload,
        dict,
    ):

        payload = {}


    sectors = (
        payload.get(
            "top_sectors",

            [],
        )
    )


    if not isinstance(
        sectors,
        list,
    ):

        sectors = []


    return jsonify(
        {
            "success": True,

            "mode": (
                mode
            ),

            "sectors": (
                sectors
            ),

            "total": (
                len(
                    sectors
                )
            ),

            "generated_at": (
                payload.get(
                    "generated_at"
                )
            ),
        }
    )


# ==========================================================
# HEALTH
# ==========================================================

@app.route("/health")
def health() -> Any:

    access_token = (
        get_access_token()
    )


    fyers_configuration = (
        fyers_service
        .configuration_status()
    )


    cache_health = (
        cache_service
        .health()
    )


    try:

        universe_health = (
            universe_service
            .health()
        )


    except Exception as exception:

        universe_health = {
            "service": (
                "NSE Sector Universe"
            ),

            "status": (
                "unhealthy"
            ),

            "is_healthy": False,

            "error": (
                str(
                    exception
                )
            ),
        }


    try:

        market_health = (
            market_data_service
            .health(
                access_token
                if access_token
                else None
            )
        )


    except Exception as exception:

        market_health = {
            "service": (
                "Market Data Service"
            ),

            "status": (
                "unhealthy"
            ),

            "is_healthy": False,

            "error": (
                str(
                    exception
                )
            ),
        }


    scanner_status = (
        get_scan_status()
    )


    healthy = (
        bool(
            fyers_configuration.get(
                "configured"
            )
        )

        and bool(
            cache_health.get(
                "is_healthy"
            )
        )

        and bool(
            universe_health.get(
                "is_healthy"
            )
        )
    )


    return jsonify(
        {
            "app": (
                APP_NAME
            ),

            "version": (
                APP_VERSION
            ),

            "status": (
                "healthy"
                if healthy
                else "degraded"
            ),

            "authenticated": (
                bool(
                    access_token
                )
            ),

            "fyers_configured": (
                fyers_configuration.get(
                    "configured",

                    False,
                )
            ),

            "technical_only": True,

            "fundamental_analysis": False,

            "fixed_nifty500": False,

            "sector_top_stock_api": True,

            "top_sector_limit": (
                Config
                .TOP_SECTORS_COUNT
            ),

            "top_stocks_per_sector": (
                Config
                .TOP_STOCKS_PER_SECTOR
            ),

            "maximum_candidate_universe": (
                Config
                .MAX_SCANNER_UNIVERSE
            ),

            "supported_modes": [
                Config.MODE_INTRADAY,

                Config.MODE_SWING,
            ],

            "default_mode": (
                DEFAULT_MODE
            ),

            "cache": (
                cache_health
            ),

            "universe": (
                universe_health
            ),

            "market_data": (
                market_health
            ),

            "scanner": (
                scanner_status
            ),

            "checked_at": (
                utc_now()
                .isoformat()
            ),
        }
    )


# ==========================================================
# ERROR HANDLERS
# ==========================================================

@app.errorhandler(400)
def bad_request(
    error: Any,
) -> Any:

    if request.path.startswith(
        "/api/"
    ):

        return jsonify(
            {
                "success": False,

                "error": (
                    "Bad request."
                ),
            }
        ), 400


    return render_template(
        "error.html",

        error_code=400,

        error_message=(
            "Bad request."
        ),
    ), 400


@app.errorhandler(404)
def not_found(
    error: Any,
) -> Any:

    if request.path.startswith(
        "/api/"
    ):

        return jsonify(
            {
                "success": False,

                "error": (
                    "Requested resource "
                    "was not found."
                ),
            }
        ), 404


    return render_template(
        "error.html",

        error_code=404,

        error_message=(
            "The requested page "
            "was not found."
        ),
    ), 404


@app.errorhandler(500)
def internal_error(
    error: Any,
) -> Any:

    log_exception(
        logger,

        (
            "Unhandled "
            "application error"
        ),

        exception=(
            error
        ),

        component="app",

        error_code=(
            "HTTP_500"
        ),
    )


    if request.path.startswith(
        "/api/"
    ):

        return jsonify(
            {
                "success": False,

                "error": (
                    "An internal application "
                    "error occurred."
                ),
            }
        ), 500


    return render_template(
        "error.html",

        error_code=500,

        error_message=(
            "An internal application "
            "error occurred."
        ),
    ), 500


# ==========================================================
# STARTUP
# ==========================================================

try:

    start_scheduler()


except Exception as scheduler_exception:

    log_exception(
        logger,

        (
            "Unable to start "
            "scheduler"
        ),

        exception=(
            scheduler_exception
        ),

        component="app",

        error_code=(
            "SCHEDULER_START_FAILED"
        ),
    )


# ==========================================================
# LOCAL DEVELOPMENT
# ==========================================================

if __name__ == "__main__":

    app.run(
        host=(
            "0.0.0.0"
        ),

        port=int(
            os.getenv(
                "PORT",

                "5000",
            )
        ),

        debug=(
            os.getenv(
                "FLASK_DEBUG",

                "false",
            )
            .strip()
            .lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            }
        ),

        threaded=True,
    )
