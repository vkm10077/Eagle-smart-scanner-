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


# ==========================================================
# FLASK APPLICATION
# ==========================================================

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
                "20",
            ),
            default=20,
        )
        or 20,
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
                    600,
                )
            ),
        ),
        default=600,
    )
    or 600,
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
# BENCHMARK SYMBOLS
# ==========================================================

# इन candidates को क्रम से try किया जाएगा।
# कोई एक fail होने पर पूरा scanner बंद नहीं होगा।
BENCHMARK_SYMBOL_CANDIDATES = (
    "NSE:NIFTYBEES-EQ",
    "NSE:NIFTY50-INDEX",
)

# Sector-specific symbols अभी compulsory नहीं रखे गए हैं।
# Valid main benchmark मिलने पर वही sector comparison के लिए उपयोग होगा।
SECTOR_INDEX_SYMBOLS: dict[str, str] = {
    "Banking and Finance": "NSE:NIFTYBEES-EQ",
    "Technology": "NSE:NIFTYBEES-EQ",
    "Consumer": "NSE:NIFTYBEES-EQ",
    "Industrials": "NSE:NIFTYBEES-EQ",
    "Energy": "NSE:NIFTYBEES-EQ",
    "Healthcare": "NSE:NIFTYBEES-EQ",
    "Materials": "NSE:NIFTYBEES-EQ",
    "Automobile": "NSE:NIFTYBEES-EQ",
    "Communication": "NSE:NIFTYBEES-EQ",
    "Real Estate": "NSE:NIFTYBEES-EQ",
    "Other": "NSE:NIFTYBEES-EQ",
}


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
    "benchmark_symbol": None,
}


F = TypeVar(
    "F",
    bound=Callable[..., Any],
)


# ==========================================================
# AUTHENTICATION HELPERS
# ==========================================================

def get_access_token() -> str:
    token = clean_text(
        session.get(
            "fyers_access_token"
        )
    )

    if token:
        return token

    return clean_text(
        cache_service.get(
            ACCESS_TOKEN_CACHE_KEY,
            default="",
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
        scan_state.update(
            updates
        )

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
# HISTORY NORMALIZATION
# ==========================================================

def normalize_history_candles(
    response: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_candles = response.get(
        "candles"
    )

    if raw_candles is None:
        response_data = response.get(
            "data"
        )

        if isinstance(
            response_data,
            dict,
        ):
            raw_candles = (
                response_data.get(
                    "candles"
                )
            )

    if not isinstance(
        raw_candles,
        list,
    ):
        return []

    candles: list[dict[str, Any]] = []
    seen_timestamps: set[int] = set()

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
            timestamp = int(
                item[0]
            )

            open_price = float(
                item[1]
            )

            high_price = float(
                item[2]
            )

            low_price = float(
                item[3]
            )

            close_price = float(
                item[4]
            )

            volume = float(
                item[5]
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        if timestamp in seen_timestamps:
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

        if high_price < max(
            open_price,
            low_price,
            close_price,
        ):
            continue

        if low_price > min(
            open_price,
            high_price,
            close_price,
        ):
            continue

        seen_timestamps.add(
            timestamp
        )

        candles.append(
            {
                "timestamp": time.strftime(
                    "%Y-%m-%dT%H:%M:%S+00:00",
                    time.gmtime(
                        timestamp
                    ),
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


# ==========================================================
# BENCHMARK HISTORY
# ==========================================================

def fetch_index_history(
    access_token: str,
    index_symbol: str,
    timeframe: str,
) -> list[dict[str, Any]]:
    normalized_timeframe = (
        normalize_timeframe(
            timeframe
        )
    )

    normalized_index_symbol = (
        clean_text(
            index_symbol
        ).upper()
    )

    if not normalized_index_symbol:
        raise RuntimeError(
            "Benchmark symbol is missing."
        )

    cache_key = (
        "eagle:index-history:"
        f"{normalized_index_symbol}:"
        f"{normalized_timeframe}"
    )

    cached = cache_service.get(
        cache_key
    )

    if (
        isinstance(
            cached,
            list,
        )
        and cached
    ):
        return cached

    history_days = {
        "15_30_days": 320,
        "3_month": 450,
        "6_month": 650,
        "1_year": 1000,
        "3_year": 1800,
    }.get(
        normalized_timeframe,
        450,
    )

    today = utc_now().date()

    start_date = (
        today
        - timedelta(
            days=history_days
        )
    )

    response = fyers_service.get_history(
        access_token,
        symbol=normalized_index_symbol,
        resolution="D",
        range_from=(
            start_date.isoformat()
        ),
        range_to=(
            today.isoformat()
        ),
        date_format="1",
        continuous="1",
    )

    candles = normalize_history_candles(
        response
    )

    if not candles:
        raise RuntimeError(
            (
                "Verified benchmark history "
                f"is unavailable for "
                f"{normalized_index_symbol}."
            )
        )

    cache_service.set(
        cache_key,
        candles,
        ttl_seconds=60 * 60,
    )

    return candles


def get_available_benchmark_history(
    access_token: str,
    timeframe: str,
) -> tuple[
    list[dict[str, Any]] | None,
    str | None,
]:
    last_error: str | None = None

    for benchmark_symbol in (
        BENCHMARK_SYMBOL_CANDIDATES
    ):
        try:
            candles = fetch_index_history(
                access_token,
                benchmark_symbol,
                timeframe,
            )

            if candles:
                logger.info(
                    (
                        "Benchmark history loaded "
                        "for %s."
                    ),
                    benchmark_symbol,
                    extra=build_log_extra(
                        component="app",
                        timeframe=(
                            normalize_timeframe(
                                timeframe
                            )
                        ),
                        event=(
                            "benchmark_history_loaded"
                        ),
                        status="success",
                        benchmark_symbol=(
                            benchmark_symbol
                        ),
                    ),
                )

                return (
                    candles,
                    benchmark_symbol,
                )

        except Exception as exception:
            last_error = str(
                exception
            )

            logger.warning(
                (
                    "Benchmark failed for %s: %s"
                ),
                benchmark_symbol,
                last_error,
                extra=build_log_extra(
                    component="app",
                    timeframe=(
                        normalize_timeframe(
                            timeframe
                        )
                    ),
                    event=(
                        "benchmark_history_failed"
                    ),
                    status="warning",
                    benchmark_symbol=(
                        benchmark_symbol
                    ),
                ),
            )

    if last_error:
        logger.warning(
            (
                "All benchmark candidates "
                "failed: %s"
            ),
            last_error,
        )

    return None, None


def build_sector_candle_map(
    access_token: str,
    timeframe: str,
    fallback_benchmark: (
        list[dict[str, Any]]
        | None
    ) = None,
) -> dict[
    str,
    list[dict[str, Any]],
]:
    raw_sector_map = build_sector_map()

    sector_names = set(
        raw_sector_map.values()
    )

    result: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    # अभी sector-specific ETF failures से बचने के लिए
    # verified fallback benchmark ही उपयोग किया जाएगा।
    if fallback_benchmark:
        for sector_name in sector_names:
            result[
                sector_name
            ] = fallback_benchmark

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
        benchmark_symbol=None,
    )

    try:
        stocks = list(
            get_nifty500_stocks()
        )

        stocks = stocks[
            :MAX_SCAN_STOCKS
        ]

        update_scan_state(
            total_stocks=len(
                stocks
            )
        )

        (
            benchmark_candles,
            benchmark_symbol,
        ) = get_available_benchmark_history(
            access_token,
            normalized_timeframe,
        )

        update_scan_state(
            benchmark_symbol=(
                benchmark_symbol
            )
        )

        sector_candle_map = (
            build_sector_candle_map(
                access_token,
                normalized_timeframe,
                fallback_benchmark=(
                    benchmark_candles
                ),
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
                last_symbol=(
                    stock.symbol
                ),
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
                        symbol=(
                            stock.symbol
                        ),
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
                    result.get(
                        "signal"
                    )
                ):
                    qualified_results.append(
                        result
                    )

                else:
                    rejected_count += 1

            except Exception as exception:
                failed_count += 1

                logger.warning(
                    (
                        "Stock scan failed for "
                        "%s: %s"
                    ),
                    stock.symbol,
                    str(exception),
                    extra=build_log_extra(
                        component="app",
                        symbol=(
                            stock.symbol
                        ),
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
                processed_stocks=(
                    position
                ),
                qualified_stocks=len(
                    qualified_results
                ),
                rejected_stocks=(
                    rejected_count
                ),
                failed_stocks=(
                    failed_count
                ),
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
            "benchmark_symbol": (
                benchmark_symbol
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
            processed_stocks=len(
                stocks
            ),
            qualified_stocks=len(
                qualified_results
            ),
            rejected_stocks=(
                rejected_count
            ),
            failed_stocks=(
                failed_count
            ),
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
                failed_count=(
                    failed_count
                ),
                rejected_count=(
                    rejected_count
                ),
                benchmark_symbol=(
                    benchmark_symbol
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
            last_error=str(
                exception
            ),
            last_symbol=None,
        )

        return {
            "success": False,
            "error": str(
                exception
            ),
        }


def start_scan_thread(
    timeframe: str,
    force_refresh: bool = False,
) -> bool:
    with scan_lock:
        if scan_state.get(
            "running"
        ):
            return False

        scan_state[
            "running"
        ] = True

    scan_thread = threading.Thread(
        target=run_background_scan,
        kwargs={
            "timeframe": (
                timeframe
            ),
            "force_refresh": (
                force_refresh
            ),
        },
        daemon=True,
        name=(
            "eagle-background-scanner"
        ),
    )

    try:
        scan_thread.start()
        return True

    except Exception:
        update_scan_state(
            running=False
        )
        raise


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
            url_for(
                "dashboard"
            )
        )

    return redirect(
        url_for(
            "login"
        )
    )


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
                str(exception),
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
            token_result.access_token
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
        DEFAULT_TIMEFRAME
    )

    return redirect(
        url_for(
            "dashboard"
        )
    )


@app.route("/logout")
def logout() -> Any:
    clear_access_token()

    update_scan_state(
        running=False,
        last_symbol=None,
    )

    flash(
        "You have been logged out.",
        "success",
    )

    return redirect(
        url_for(
            "login"
        )
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

    initial_results: list[
        dict[str, Any]
    ] = []

    if isinstance(
        cached_payload,
        dict,
    ):
        cached_results = (
            cached_payload.get(
                "results"
            )
        )

        if isinstance(
            cached_results,
            list,
        ):
            initial_results = (
                cached_results
            )

    return render_template(
        "dashboard.html",
        timeframe=(
            timeframe
        ),
        initial_results=(
            initial_results
        ),
        sectors=(
            get_all_sectors()
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
        symbol=(
            normalized_symbol
        ),
        timeframe=(
            timeframe
        ),
        stock_detail=(
            detail
        ),
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
                "indices": indices,
                "total": len(
                    indices
                ),
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
                "error": str(
                    exception
                ),
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

    if not isinstance(
        results,
        list,
    ):
        results = []

    sector_filter = clean_text(
        request.args.get(
            "sector"
        )
    )

    signal_filter = clean_text(
        request.args.get(
            "signal"
        )
    ).upper()

    minimum_probability = (
        request.args.get(
            "minimum_probability"
        )
    )

    filtered_results = [
        item
        for item in results
        if isinstance(
            item,
            dict,
        )
    ]

    if sector_filter:
        filtered_results = [
            item
            for item in filtered_results
            if clean_text(
                item.get(
                    "sector"
                )
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
                item.get(
                    "signal"
                )
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
            "timeframe": (
                timeframe
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
            "total": len(
                results
            ),
        }
    )


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

        if (
            isinstance(
                cached_detail,
                dict,
            )
            and cached_detail
        ):
            return jsonify(
                {
                    "success": True,
                    "stock": (
                        cached_detail
                    ),
                    "cached": True,
                }
            )

    try:
        (
            benchmark_candles,
            benchmark_symbol,
        ) = get_available_benchmark_history(
            access_token,
            timeframe,
        )

        sector_candles = (
            benchmark_candles
            if benchmark_candles
            else None
        )

        result = (
            research_engine
            .research_stock(
                access_token=(
                    access_token
                ),
                symbol=(
                    normalized_symbol
                ),
                timeframe=(
                    timeframe
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

        if isinstance(
            result,
            dict,
        ):
            result[
                "benchmark_symbol"
            ] = benchmark_symbol

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
        log_exception(
            logger,
            (
                "Stock detail research failed"
            ),
            exception=exception,
            symbol=(
                normalized_symbol
            ),
            timeframe=(
                timeframe
            ),
            component="app",
            error_code=(
                "STOCK_DETAIL_FAILED"
            ),
        )

        return jsonify(
            {
                "success": False,
                "error": (
                    str(exception)
                    or (
                        "Verified stock research "
                        "could not be completed."
                    )
                ),
                "symbol": (
                    normalized_symbol
                ),
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
            "scanner": (
                get_scan_status()
            ),
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
            "timeframe": (
                timeframe
            ),
            "scanner": (
                get_scan_status()
            ),
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
            "total": len(
                sectors
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
            "fundamental_configured": bool(
                os.getenv(
                    "FMP_API_KEY"
                )
            ),
            "cache": cache_health,
            "scanner": (
                get_scan_status()
            ),
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
        "Unable to start scheduler",
        exception=(
            scheduler_exception
        ),
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
