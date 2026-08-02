from __future__ import annotations

import atexit
import fcntl
import os
import threading
import time
from datetime import timedelta
from functools import wraps
from typing import Any, Callable, TypeVar

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
from data.nifty500 import (
    find_stock,
    get_nifty500_stocks,
    search_stocks,
)
from data.sector_map import (
    build_sector_map,
    get_all_sectors,
    get_sector_group,
)
from scanners.research_engine import (
    ResearchEngine,
    get_research_engine,
)
from services.cache_service import (
    CacheService,
    get_cache_service,
)
from services.fyers_service import (
    FyersAuthenticationError,
    FyersConfigurationError,
    FyersService,
    get_fyers_service,
)
from services.index_service import (
    IndexService,
    get_index_service,
)
from utils.helpers import (
    clean_text,
    filter_buy_results,
    is_buy_signal,
    normalize_symbol,
    normalize_timeframe,
    safe_int,
    sort_scan_results,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_exception,
)


logger = get_logger("app")


app = Flask(__name__)
app.config.from_object(Config)

app.secret_key = app.config["SECRET_KEY"]

app.permanent_session_lifetime = app.config[
    "PERMANENT_SESSION_LIFETIME"
]

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        os.getenv(
            "SESSION_COOKIE_SECURE",
            "true",
        ).strip().lower()
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

cache_service: CacheService = get_cache_service()
fyers_service: FyersService = get_fyers_service()
index_service: IndexService = get_index_service()
research_engine: ResearchEngine = get_research_engine()


# ==========================================================
# APPLICATION SETTINGS
# ==========================================================

APP_NAME = "Eagle Smart Scanner"

DEFAULT_TIMEFRAME = normalize_timeframe(
    app.config.get(
        "DEFAULT_TIMEFRAME",
        "3_month",
    )
)

SUPPORTED_TIMEFRAMES = {
    "15_30_days": "15–30 Days",
    "3_month": "3 Months",
    "6_month": "6 Months",
    "1_year": "1 Year",
    "3_year": "3 Years",
}

MAX_SCAN_STOCKS = max(
    1,
    min(
        safe_int(
            os.getenv(
                "MAX_SCAN_STOCKS",
                "500",
            ),
            default=500,
        )
        or 500,
        500,
    ),
)

SCANNER_REFRESH_SECONDS = max(
    180,
    safe_int(
        os.getenv(
            "SCANNER_REFRESH_SECONDS",
            str(
                app.config.get(
                    "SCANNER_REFRESH_SECONDS",
                    180,
                )
            ),
        ),
        default=180,
    )
    or 180,
)

ENABLE_BACKGROUND_SCANNER = (
    os.getenv(
        "ENABLE_BACKGROUND_SCANNER",
        "true",
    ).strip().lower()
    in {
        "1",
        "true",
        "yes",
        "on",
    }
)

SCAN_RESULTS_CACHE_SECONDS = max(
    SCANNER_REFRESH_SECONDS * 2,
    600,
)

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


# ==========================================================
# VERIFIED SECTOR BENCHMARKS
# ==========================================================

SECTOR_INDEX_SYMBOLS: dict[str, str] = {
    "Banking and Finance": (
        "NSE:NIFTYFINSERVICE-INDEX"
    ),
    "Technology": "NSE:NIFTYIT-INDEX",
    "Consumer": "NSE:NIFTYFMCG-INDEX",
    "Industrials": "NSE:NIFTYINFRA-INDEX",
    "Energy": "NSE:NIFTYENERGY-INDEX",
    "Healthcare": "NSE:NIFTYPHARMA-INDEX",
    "Materials": "NSE:NIFTYMETAL-INDEX",
    "Automobile": "NSE:NIFTYAUTO-INDEX",
    "Communication": "NSE:NIFTYMEDIA-INDEX",
    "Real Estate": "NSE:NIFTYREALTY-INDEX",
    "Other": "NSE:NIFTY50-INDEX",
}

NIFTY_BENCHMARK_SYMBOL = "NSE:NIFTY50-INDEX"


# ==========================================================
# SCANNER STATE
# ==========================================================

scan_lock = threading.RLock()
scheduler_lock_file: Any = None
scheduler: BackgroundScheduler | None = None

scan_state: dict[str, Any] = {
    "running": False,
    "timeframe": DEFAULT_TIMEFRAME,
    "total_stocks": 0,
    "processed_stocks": 0,
    "qualified_stocks": 0,
    "rejected_stocks": 0,
    "failed_stocks": 0,
    "progress_percent": 0.0,
    "started_at": None,
    "completed_at": None,
    "last_error": None,
    "last_symbol": None,
}


F = TypeVar("F", bound=Callable[..., Any])


# ==========================================================
# AUTHENTICATION HELPERS
# ==========================================================

def get_access_token() -> str:
    token = clean_text(
        session.get("fyers_access_token")
    )

    if token:
        return token

    cached_token = clean_text(
        cache_service.get(
            ACCESS_TOKEN_CACHE_KEY,
            default="",
        )
    )

    return cached_token


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
        ttl_seconds=12 * 60 * 60,
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


def login_required(
    function: F,
) -> F:
    @wraps(function)
    def wrapped(
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        access_token = get_access_token()

        if access_token:
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
                    "login_url": url_for(
                        "login"
                    ),
                }
            ), 401

        flash(
            "Please login with FYERS.",
            "warning",
        )

        return redirect(
            url_for("login")
        )

    return wrapped  # type: ignore[return-value]


# ==========================================================
# CACHE KEYS
# ==========================================================

def scan_results_cache_key(
    timeframe: str,
) -> str:
    return (
        f"{SCAN_RESULT_KEY_PREFIX}"
        f"{normalize_timeframe(timeframe)}"
    )


def stock_detail_cache_key(
    symbol: str,
    timeframe: str,
) -> str:
    return (
        f"{SCAN_DETAIL_KEY_PREFIX}"
        f"{normalize_symbol(symbol)}:"
        f"{normalize_timeframe(timeframe)}"
    )


# ==========================================================
# SCANNER STATUS
# ==========================================================

def update_scan_state(
    **updates: Any,
) -> None:
    with scan_lock:
        scan_state.update(updates)

        total = (
            safe_int(
                scan_state.get(
                    "total_stocks"
                ),
                default=0,
            )
            or 0
        )

        processed = (
            safe_int(
                scan_state.get(
                    "processed_stocks"
                ),
                default=0,
            )
            or 0
        )

        scan_state[
            "progress_percent"
        ] = (
            round(
                processed / total * 100,
                2,
            )
            if total > 0
            else 0.0
        )

        scan_state[
            "updated_at"
        ] = utc_now().isoformat()

        cache_service.set(
            SCAN_STATUS_CACHE_KEY,
            dict(scan_state),
            ttl_seconds=24 * 60 * 60,
        )


def get_scan_status() -> dict[str, Any]:
    with scan_lock:
        current_state = dict(
            scan_state
        )

    cached_state = cache_service.get(
        SCAN_STATUS_CACHE_KEY
    )

    if (
        isinstance(cached_state, dict)
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
# INDEX HISTORY HELPERS
# ==========================================================

def normalize_history_candles(
    response: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_candles = response.get(
        "candles"
    )

    if raw_candles is None:
        data = response.get("data")

        if isinstance(data, dict):
            raw_candles = data.get(
                "candles"
            )

    if not isinstance(
        raw_candles,
        list,
    ):
        return []

    candles: list[dict[str, Any]] = []

    for item in raw_candles:
        if (
            not isinstance(
                item,
                (list, tuple),
            )
            or len(item) < 6
        ):
            continue

        try:
            timestamp = int(item[0])
            open_price = float(item[1])
            high_price = float(item[2])
            low_price = float(item[3])
            close_price = float(item[4])
            volume = float(item[5])

        except (
            TypeError,
            ValueError,
        ):
            continue

        if (
            min(
                open_price,
                high_price,
                low_price,
                close_price,
            )
            <= 0
        ):
            continue

        if (
            high_price
            < max(
                open_price,
                close_price,
                low_price,
            )
        ):
            continue

        if (
            low_price
            > min(
                open_price,
                close_price,
                high_price,
            )
        ):
            continue

        candles.append(
            {
                "timestamp": (
                    time.strftime(
                        "%Y-%m-%dT%H:%M:%S+00:00",
                        time.gmtime(
                            timestamp
                        ),
                    )
                ),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": max(
                    0.0,
                    volume,
                ),
            }
        )

    candles.sort(
        key=lambda item: item[
            "timestamp"
        ]
    )

    return candles


def fetch_index_history(
    access_token: str,
    index_symbol: str,
    timeframe: str,
) -> list[dict[str, Any]]:
    normalized_timeframe = (
        normalize_timeframe(timeframe)
    )

    cache_key = (
        "eagle:index-history:"
        f"{index_symbol}:"
        f"{normalized_timeframe}"
    )

    cached = cache_service.get(
        cache_key
    )

    if (
        isinstance(cached, list)
        and cached
    ):
        return cached

    history_days = {
        "15_30_days": 320,
        "3_month": 450,
        "6_month": 650,
        "1_year": 1000,
        "3_year": 1800,
    }[normalized_timeframe]

    today = utc_now().date()

    start_date = (
        today
        - timedelta(
            days=history_days
        )
    )

    response = fyers_service.get_history(
        access_token,
        symbol=index_symbol,
        resolution="D",
        range_from=(
            start_date.isoformat()
        ),
        range_to=today.isoformat(),
        date_format="1",
        continuous="1",
    )

    candles = normalize_history_candles(
        response
    )

    if not candles:
        raise RuntimeError(
            (
                "Verified index history is "
                f"unavailable for {index_symbol}."
            )
        )

    cache_service.set(
        cache_key,
        candles,
        ttl_seconds=60 * 60,
    )

    return candles


def build_sector_candle_map(
    access_token: str,
    timeframe: str,
) -> dict[
    str,
    list[dict[str, Any]],
]:
    raw_sector_map = build_sector_map()

    sector_groups = {
        sector: get_sector_group(
            sector
        )
        for sector in set(
            raw_sector_map.values()
        )
    }

    group_candles: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for group_name in set(
        sector_groups.values()
    ):
        index_symbol = (
            SECTOR_INDEX_SYMBOLS.get(
                group_name
            )
            or SECTOR_INDEX_SYMBOLS[
                "Other"
            ]
        )

        try:
            group_candles[
                group_name
            ] = fetch_index_history(
                access_token,
                index_symbol,
                timeframe,
            )

        except Exception as exception:
            logger.warning(
                (
                    "Sector benchmark unavailable "
                    "for %s: %s"
                ),
                group_name,
                str(exception),
                extra=build_log_extra(
                    component="app",
                    event=(
                        "sector_benchmark_failed"
                    ),
                    status="warning",
                    sector_group=(
                        group_name
                    ),
                ),
            )

    result: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for sector, group_name in (
        sector_groups.items()
    ):
        candles = group_candles.get(
            group_name
        )

        if candles:
            result[sector] = candles

    return result


# ==========================================================
# BACKGROUND SCANNER
# ==========================================================

def run_background_scan(
    timeframe: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    normalized_timeframe = (
        normalize_timeframe(
            timeframe
            or DEFAULT_TIMEFRAME
        )
    )

    access_token = clean_text(
        cache_service.get(
            ACCESS_TOKEN_CACHE_KEY,
            default="",
        )
    )

    if not access_token:
        update_scan_state(
            running=False,
            timeframe=(
                normalized_timeframe
            ),
            last_error=(
                "FYERS login is required."
            ),
            completed_at=(
                utc_now().isoformat()
            ),
        )

        return {
            "success": False,
            "error": (
                "FYERS login is required."
            ),
        }

    with scan_lock:
        if scan_state.get("running"):
            return {
                "success": False,
                "error": (
                    "Scanner is already running."
                ),
            }

        update_scan_state(
            running=True,
            timeframe=(
                normalized_timeframe
            ),
            total_stocks=0,
            processed_stocks=0,
            qualified_stocks=0,
            rejected_stocks=0,
            failed_stocks=0,
            progress_percent=0.0,
            started_at=(
                utc_now().isoformat()
            ),
            completed_at=None,
            last_error=None,
            last_symbol=None,
        )

    try:
        stocks = get_nifty500_stocks()

        stocks = stocks[
            :MAX_SCAN_STOCKS
        ]

        update_scan_state(
            total_stocks=len(stocks)
        )

        benchmark_candles = (
            fetch_index_history(
                access_token,
                NIFTY_BENCHMARK_SYMBOL,
                normalized_timeframe,
            )
        )

        sector_candle_map = (
            build_sector_candle_map(
                access_token,
                normalized_timeframe,
            )
        )

        qualified_results: list[
            dict[str, Any]
        ] = []

        rejected_count = 0
        failed_count = 0

        for position, stock in enumerate(
            stocks,
            start=1,
        ):
            update_scan_state(
                last_symbol=stock.symbol,
                processed_stocks=(
                    position - 1
                ),
            )

            sector_candles = (
                sector_candle_map.get(
                    stock.industry
                )
            )

            try:
                result = (
                    research_engine
                    .research_stock(
                        access_token=(
                            access_token
                        ),
                        symbol=stock.symbol,
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
                )

                cache_service.set(
                    stock_detail_cache_key(
                        stock.symbol,
                        normalized_timeframe,
                    ),
                    result,
                    ttl_seconds=(
                        SCAN_RESULTS_CACHE_SECONDS
                    ),
                )

                if is_buy_signal(
                    result.get("signal")
                ):
                    qualified_results.append(
                        result
                    )
                else:
                    rejected_count += 1

            except Exception as exception:
                failed_count += 1

                logger.warning(
                    "Stock scan failed for %s: %s",
                    stock.symbol,
                    str(exception),
                    extra=build_log_extra(
                        component="app",
                        symbol=stock.symbol,
                        timeframe=(
                            normalized_timeframe
                        ),
                        event=(
                            "stock_scan_failed"
                        ),
                        status="failed",
                    ),
                )

            update_scan_state(
                processed_stocks=position,
                qualified_stocks=len(
                    qualified_results
                ),
                rejected_stocks=(
                    rejected_count
                ),
                failed_stocks=failed_count,
            )

        qualified_results = (
            sort_scan_results(
                filter_buy_results(
                    qualified_results
                )
            )
        )

        payload = {
            "timeframe": (
                normalized_timeframe
            ),
            "results": (
                qualified_results
            ),
            "total_results": len(
                qualified_results
            ),
            "total_scanned": len(
                stocks
            ),
            "rejected_count": (
                rejected_count
            ),
            "failed_count": (
                failed_count
            ),
            "generated_at": (
                utc_now().isoformat()
            ),
            "verified": True,
        }

        cache_service.set(
            scan_results_cache_key(
                normalized_timeframe
            ),
            payload,
            ttl_seconds=(
                SCAN_RESULTS_CACHE_SECONDS
            ),
        )

        update_scan_state(
            running=False,
            processed_stocks=len(stocks),
            qualified_stocks=len(
                qualified_results
            ),
            rejected_stocks=(
                rejected_count
            ),
            failed_stocks=failed_count,
            completed_at=(
                utc_now().isoformat()
            ),
            last_error=None,
            last_symbol=None,
        )

        logger.info(
            (
                "Background scan completed "
                "for %s with %s result(s)."
            ),
            normalized_timeframe,
            len(qualified_results),
            extra=build_log_extra(
                component="app",
                timeframe=(
                    normalized_timeframe
                ),
                event=(
                    "background_scan_completed"
                ),
                status="success",
                qualified_count=len(
                    qualified_results
                ),
            ),
        )

        return {
            "success": True,
            **payload,
        }

    except Exception as exception:
        log_exception(
            logger,
            "Background scan failed",
            exception=exception,
            timeframe=(
                normalized_timeframe
            ),
            component="app",
            error_code=(
                "BACKGROUND_SCAN_FAILED"
            ),
        )

        update_scan_state(
            running=False,
            completed_at=(
                utc_now().isoformat()
            ),
            last_error=str(exception),
        )

        return {
            "success": False,
            "error": str(exception),
        }


def start_scan_thread(
    timeframe: str,
    force_refresh: bool = False,
) -> bool:
    with scan_lock:
        if scan_state.get("running"):
            return False

    scan_thread = threading.Thread(
        target=run_background_scan,
        kwargs={
            "timeframe": timeframe,
            "force_refresh": (
                force_refresh
            ),
        },
        daemon=True,
        name=(
            "eagle-background-scanner"
        ),
    )

    scan_thread.start()

    return True


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
            str(os.getpid())
        )

        scheduler_lock_file.flush()

        return True

    except (
        BlockingIOError,
        OSError,
    ):
        return False


def start_scheduler() -> None:
    global scheduler

    if not ENABLE_BACKGROUND_SCANNER:
        logger.info(
            "Background scanner is disabled."
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
        timezone="Asia/Kolkata",
        daemon=True,
    )

    scheduler.add_job(
        run_background_scan,
        trigger="interval",
        seconds=(
            SCANNER_REFRESH_SECONDS
        ),
        kwargs={
            "timeframe": (
                DEFAULT_TIMEFRAME
            ),
            "force_refresh": False,
        },
        id="eagle-default-scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()

    logger.info(
        (
            "Background scheduler started "
            "with %s-second interval."
        ),
        SCANNER_REFRESH_SECONDS,
        extra=build_log_extra(
            component="app",
            event="scheduler_started",
            status="success",
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
        "app_name": APP_NAME,
        "app_version": app.config.get(
            "VERSION",
            "1.0.0",
        ),
        "supported_timeframes": (
            SUPPORTED_TIMEFRAMES
        ),
        "default_timeframe": (
            DEFAULT_TIMEFRAME
        ),
        "current_year": (
            utc_now().year
        ),
    }


# ==========================================================
# PAGE ROUTES
# ==========================================================

@app.route("/")
def home() -> Any:
    if get_access_token():
        return redirect(
            url_for("dashboard")
        )

    return redirect(
        url_for("login")
    )


@app.route("/login")
def login() -> Any:
    if get_access_token():
        return redirect(
            url_for("dashboard")
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
                str(exception),
                "error",
            )

    return render_template(
        "login.html",
        configuration=configuration,
        login_url=login_url,
    )


@app.route("/callback")
@app.route("/auth/callback")
def fyers_callback() -> Any:
    auth_code = clean_text(
        request.args.get("auth_code")
        or request.args.get("code")
    )

    callback_error = clean_text(
        request.args.get("error")
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
            url_for("login")
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
            url_for("login")
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
            url_for("login")
        )

    store_access_token(
        token_result.access_token
    )

    token_status = (
        fyers_service
        .validate_access_token(
            token_result.access_token
        )
    )

    if not token_status.get("valid"):
        clear_access_token()

        flash(
            (
                "FYERS token verification "
                "failed."
            ),
            "error",
        )

        return redirect(
            url_for("login")
        )

    session["fyers_profile"] = (
        token_status.get(
            "profile",
            {},
        )
    )

    flash(
        (
            "FYERS login successful. "
            "Eagle Smart Scanner is ready."
        ),
        "success",
    )

    start_scan_thread(
        DEFAULT_TIMEFRAME
    )

    return redirect(
        url_for("dashboard")
    )


@app.route("/logout")
def logout() -> Any:
    clear_access_token()

    flash(
        "You have been logged out.",
        "success",
    )

    return redirect(
        url_for("login")
    )


@app.route("/dashboard")
@login_required
def dashboard() -> Any:
    timeframe = normalize_timeframe(
        request.args.get(
            "timeframe",
            DEFAULT_TIMEFRAME,
        )
    )

    cached_payload = (
        cache_service.get(
            scan_results_cache_key(
                timeframe
            ),
            default={},
        )
    )

    initial_results = []

    if isinstance(
        cached_payload,
        dict,
    ):
        initial_results = (
            cached_payload.get(
                "results",
                [],
            )
        )

    return render_template(
        "dashboard.html",
        timeframe=timeframe,
        initial_results=(
            initial_results
        ),
        sectors=get_all_sectors(),
        scanner_status=(
            get_scan_status()
        ),
        profile=session.get(
            "fyers_profile",
            {},
        ),
    )


@app.route(
    "/stock/<symbol>"
)
@login_required
def stock_detail_page(
    symbol: str,
) -> Any:
    normalized_symbol = (
        normalize_symbol(symbol)
    )

    timeframe = normalize_timeframe(
        request.args.get(
            "timeframe",
            DEFAULT_TIMEFRAME,
        )
    )

    detail = cache_service.get(
        stock_detail_cache_key(
            normalized_symbol,
            timeframe,
        ),
        default={},
    )

    return render_template(
        "stock_detail.html",
        symbol=normalized_symbol,
        timeframe=timeframe,
        stock_detail=detail,
    )


@app.route("/privacy")
def privacy() -> Any:
    return render_template(
        "privacy.html"
    )


# ==========================================================
# API ROUTES
# ==========================================================

@app.route("/api/indices")
@login_required
def api_indices() -> Any:
    access_token = get_access_token()

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
                "indices": indices,
                "total": len(indices),
                "updated_at": (
                    utc_now().isoformat()
                ),
            }
        )

    except Exception as exception:
        return jsonify(
            {
                "success": False,
                "indices": [],
                "error": str(exception),
                "updated_at": (
                    utc_now().isoformat()
                ),
            }
        ), 503


@app.route("/api/signals")
@login_required
def api_signals() -> Any:
    timeframe = normalize_timeframe(
        request.args.get(
            "timeframe",
            DEFAULT_TIMEFRAME,
        )
    )

    payload = cache_service.get(
        scan_results_cache_key(
            timeframe
        ),
        default=None,
    )

    if not isinstance(
        payload,
        dict,
    ):
        started = start_scan_thread(
            timeframe
        )

        return jsonify(
            {
                "success": True,
                "results": [],
                "total_results": 0,
                "timeframe": timeframe,
                "scan_started": started,
                "scanner_status": (
                    get_scan_status()
                ),
                "message": (
                    "Verified scan is being "
                    "prepared in background."
                ),
            }
        )

    results = payload.get(
        "results",
        [],
    )

    sector_filter = clean_text(
        request.args.get("sector")
    )

    signal_filter = clean_text(
        request.args.get("signal")
    ).upper()

    minimum_probability = (
        request.args.get(
            "minimum_probability"
        )
    )

    filtered_results = [
        item
        for item in results
        if isinstance(item, dict)
    ]

    if sector_filter:
        filtered_results = [
            item
            for item in filtered_results
            if clean_text(
                item.get("sector")
            ).casefold()
            == sector_filter.casefold()
        ]

    if signal_filter in {
        "BUY",
        "STRONG BUY",
    }:
        filtered_results = [
            item
            for item in filtered_results
            if clean_text(
                item.get("signal")
            ).upper()
            == signal_filter
        ]

    try:
        probability_limit = float(
            minimum_probability
        )

        filtered_results = [
            item
            for item in filtered_results
            if float(
                item.get(
                    "move_up_probability",
                    0,
                )
            )
            >= probability_limit
        ]

    except (
        TypeError,
        ValueError,
    ):
        pass

    return jsonify(
        {
            "success": True,
            "results": (
                sort_scan_results(
                    filtered_results
                )
            ),
            "total_results": len(
                filtered_results
            ),
            "timeframe": timeframe,
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


@app.route("/api/search")
@login_required
def api_search() -> Any:
    query = clean_text(
        request.args.get("q")
    )

    if len(query) < 1:
        return jsonify(
            {
                "success": True,
                "results": [],
            }
        )

    results = search_stocks(
        query,
        limit=20,
    )

    return jsonify(
        {
            "success": True,
            "query": query,
            "results": results,
            "total": len(results),
        }
    )


@app.route(
    "/api/stock/<symbol>"
)
@login_required
def api_stock_detail(
    symbol: str,
) -> Any:
    access_token = get_access_token()

    normalized_symbol = (
        normalize_symbol(symbol)
    )

    timeframe = normalize_timeframe(
        request.args.get(
            "timeframe",
            DEFAULT_TIMEFRAME,
        )
    )

    force_refresh = (
        request.args.get(
            "refresh",
            "false",
        ).strip().lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )

    stock = find_stock(
        normalized_symbol
    )

    if stock is None:
        return jsonify(
            {
                "success": False,
                "error": (
                    "Stock is not part of "
                    "the current Nifty 500 list."
                ),
            }
        ), 404

    cache_key = (
        stock_detail_cache_key(
            normalized_symbol,
            timeframe,
        )
    )

    if not force_refresh:
        cached_detail = (
            cache_service.get(
                cache_key
            )
        )

        if isinstance(
            cached_detail,
            dict,
        ) and cached_detail:
            return jsonify(
                {
                    "success": True,
                    "stock": cached_detail,
                    "cached": True,
                }
            )

    try:
        benchmark_candles = (
            fetch_index_history(
                access_token,
                NIFTY_BENCHMARK_SYMBOL,
                timeframe,
            )
        )

        sector_group = get_sector_group(
            stock.industry
        )

        sector_symbol = (
            SECTOR_INDEX_SYMBOLS.get(
                sector_group,
                NIFTY_BENCHMARK_SYMBOL,
            )
        )

        sector_candles = (
            fetch_index_history(
                access_token,
                sector_symbol,
                timeframe,
            )
        )

        result = (
            research_engine
            .research_stock(
                access_token=access_token,
                symbol=normalized_symbol,
                timeframe=timeframe,
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
        )

        cache_service.set(
            cache_key,
            result,
            ttl_seconds=(
                SCAN_RESULTS_CACHE_SECONDS
            ),
        )

        return jsonify(
            {
                "success": True,
                "stock": result,
                "cached": False,
            }
        )

    except Exception as exception:
        return jsonify(
            {
                "success": False,
                "error": str(exception),
                "symbol": normalized_symbol,
            }
        ), 503


@app.route(
    "/api/scan/status"
)
@login_required
def api_scan_status() -> Any:
    return jsonify(
        {
            "success": True,
            "scanner": get_scan_status(),
        }
    )


@app.route(
    "/api/scan/refresh",
    methods=["POST"],
)
@login_required
def api_scan_refresh() -> Any:
    request_data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    timeframe = normalize_timeframe(
        request_data.get(
            "timeframe"
        )
        or request.form.get(
            "timeframe"
        )
        or DEFAULT_TIMEFRAME
    )

    started = start_scan_thread(
        timeframe,
        force_refresh=True,
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
                "Verified background scan started."
            ),
            "timeframe": timeframe,
            "scanner": get_scan_status(),
        }
    ), 202


@app.route("/api/sectors")
@login_required
def api_sectors() -> Any:
    sectors = get_all_sectors()

    return jsonify(
        {
            "success": True,
            "sectors": sectors,
            "total": len(sectors),
        }
    )


# ==========================================================
# HEALTH ROUTES
# ==========================================================

@app.route("/health")
def health() -> Any:
    access_token = get_access_token()

    configuration = (
        fyers_service
        .configuration_status()
    )

    cache_health = (
        cache_service.health()
    )

    status = (
        "healthy"
        if (
            configuration.get(
                "configured"
            )
            and cache_health.get(
                "is_healthy"
            )
        )
        else "degraded"
    )

    return jsonify(
        {
            "app": APP_NAME,
            "status": status,
            "version": app.config.get(
                "VERSION",
                "1.0.0",
            ),
            "fyers_configured": (
                configuration.get(
                    "configured",
                    False,
                )
            ),
            "authenticated": bool(
                access_token
            ),
            "fundamental_configured": (
                bool(
                    os.getenv(
                        "FMP_API_KEY"
                    )
                )
            ),
            "cache": cache_health,
            "scanner": get_scan_status(),
            "checked_at": (
                utc_now().isoformat()
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
                "error": "Bad request.",
            }
        ), 400

    return render_template(
        "error.html",
        error_code=400,
        error_message="Bad request.",
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
            "The requested page was not found."
        ),
    ), 404


@app.errorhandler(500)
def internal_error(
    error: Any,
) -> Any:
    log_exception(
        logger,
        "Unhandled application error",
        exception=error,
        component="app",
        error_code="HTTP_500",
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
            "An internal application error occurred."
        ),
    ), 500


# ==========================================================
# APPLICATION STARTUP
# ==========================================================

try:
    start_scheduler()

except Exception as scheduler_exception:
    log_exception(
        logger,
        "Unable to start scheduler",
        exception=scheduler_exception,
        component="app",
        error_code=(
            "SCHEDULER_START_FAILED"
        ),
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "5000",
            )
        ),
        debug=app.config.get(
            "DEBUG",
            False,
        ),
        threaded=True,
    )
