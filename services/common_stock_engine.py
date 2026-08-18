from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict
from datetime import datetime
from typing import Any, Iterable

import pytz

from config import Config
from services.stock_ranker import RankedStock
from utils.helpers import (
    clean_text,
    normalize_symbol,
    safe_float,
)


logger = logging.getLogger(
    "services.common_stock_engine"
)


INDIA_TZ = pytz.timezone(
    Config.MARKET_TIMEZONE
)


# ============================================================
# GLOBAL FILE LOCK
# ============================================================


_file_lock = threading.RLock()


# ============================================================
# MODE
# ============================================================


def _normalize_mode(
    mode: str | None,
) -> str:
    """
    Normalize scanner mode.

    Expected modes:
        intraday
        btst
        swing
    """

    normalized = (
        Config.normalize_trading_mode(
            mode
            or Config.DEFAULT_TRADING_MODE
        )
    )

    supported_modes = set(
        getattr(
            Config,
            "SUPPORTED_TRADING_MODES",
            (),
        )
    )

    if (
        supported_modes
        and normalized
        not in supported_modes
    ):

        raise ValueError(
            (
                "Unsupported trading mode: "
                f"{normalized}"
            )
        )

    return normalized


# ============================================================
# FILE PATHS
# ============================================================


def get_current_file(
    mode: str,
) -> str:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    return (
        Config.get_current_day_file(
            normalized_mode
        )
    )


def get_previous_file(
    mode: str,
) -> str:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    return (
        Config.get_previous_day_file(
            normalized_mode
        )
    )


def get_common_file(
    mode: str,
) -> str:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    return (
        Config.get_common_stocks_file(
            normalized_mode
        )
    )


# ============================================================
# TIME
# ============================================================


def _now_ist(
) -> datetime:

    return datetime.now(
        INDIA_TZ
    )


def _today_string(
) -> str:

    return (
        _now_ist()
        .strftime(
            "%Y-%m-%d"
        )
    )


# ============================================================
# DIRECTORY
# ============================================================


def _ensure_data_dir(
) -> None:

    os.makedirs(
        Config.DATA_DIR,
        exist_ok=True,
    )


# ============================================================
# SAFE FLOAT
# ============================================================


def _number(
    value: Any,
    default: float = 0.0,
) -> float:

    result = safe_float(
        value,
        default=default,
    )

    return float(
        result
        if result is not None
        else default
    )


# ============================================================
# NORMALIZE STOCK
# ============================================================


def _stock_to_dict(
    stock: RankedStock | dict[str, Any],
) -> dict[str, Any]:
    """
    Convert RankedStock/dict into safe
    common candidate format.
    """

    if isinstance(
        stock,
        RankedStock,
    ):

        data = asdict(
            stock
        )

    elif isinstance(
        stock,
        dict,
    ):

        data = dict(
            stock
        )

    else:

        raise TypeError(
            (
                "Candidate must be "
                "RankedStock or dict."
            )
        )

    symbol = normalize_symbol(
        data.get(
            "symbol"
        )
    )

    if not symbol:

        return {}

    company_name = clean_text(
        data.get(
            "company_name"
        )
        or symbol
    )

    sector = clean_text(
        data.get(
            "sector"
        )
    )

    mode = clean_text(
        data.get(
            "mode"
        )
    )

    score = _number(
        data.get(
            "score",
            data.get(
                "current_score",
                0.0,
            ),
        )
    )

    output = {
        "symbol": (
            symbol
        ),

        "company_name": (
            company_name
            or symbol
        ),

        "sector": (
            sector
        ),

        "score": round(
            score,
            2,
        ),
    }

    if mode:

        output[
            "mode"
        ] = mode

    # Optional ranking fields.
    optional_fields = (
        "momentum_score",
        "trend_score",
        "volume_score",
        "rsi_score",
        "relative_strength_score",
        "macd_score",
        "supertrend_score",
        "vwap_score",
        "breakout_score",
        "multi_timeframe_score",
        "signal",
        "strong_buy",
    )

    for field in optional_fields:

        if field not in data:
            continue

        output[
            field
        ] = data[
            field
        ]

    return output


# ============================================================
# PREPARE CANDIDATES
# ============================================================


def _prepare_candidates(
    stocks: Iterable[
        RankedStock
        | dict[str, Any]
    ],
) -> list[
    dict[str, Any]
]:
    """
    Normalize list and remove duplicate symbols.
    """

    output: list[
        dict[str, Any]
    ] = []

    seen_symbols: set[
        str
    ] = set()

    for stock in stocks:

        try:

            data = (
                _stock_to_dict(
                    stock
                )
            )

        except Exception:

            continue

        if not data:

            continue

        symbol = normalize_symbol(
            data.get(
                "symbol"
            )
        )

        if not symbol:

            continue

        if symbol in seen_symbols:

            continue

        seen_symbols.add(
            symbol
        )

        data[
            "symbol"
        ] = symbol

        output.append(
            data
        )

    return output


# ============================================================
# JSON WRITE
# ============================================================


def _write_json(
    file_path: str,
    payload: dict[str, Any],
) -> None:
    """
    Atomic JSON write.
    """

    _ensure_data_dir()

    directory = os.path.dirname(
        file_path
    )

    if directory:

        os.makedirs(
            directory,
            exist_ok=True,
        )

    temp_path = (
        file_path
        + ".tmp"
    )

    with _file_lock:

        with open(
            temp_path,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                payload,
                file,
                indent=2,
                ensure_ascii=False,
            )

            file.flush()

            os.fsync(
                file.fileno()
            )

        os.replace(
            temp_path,
            file_path,
        )


# ============================================================
# JSON READ
# ============================================================


def _read_json(
    file_path: str,
) -> dict[str, Any] | None:

    if not os.path.exists(
        file_path
    ):

        return None

    with _file_lock:

        try:

            with open(
                file_path,
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(
                    file
                )

            if not isinstance(
                data,
                dict,
            ):

                return None

            return data

        except Exception:

            logger.exception(
                (
                    "Unable to read "
                    "common-stock file: %s"
                ),
                file_path,
            )

            return None


# ============================================================
# VALIDATE PAYLOAD MODE
# ============================================================


def _payload_matches_mode(
    payload: dict[str, Any] | None,
    mode: str,
) -> bool:

    if not isinstance(
        payload,
        dict,
    ):

        return False

    payload_mode = clean_text(
        payload.get(
            "mode"
        )
    )

    if not payload_mode:

        # Backward compatibility with
        # older stored files.
        return True

    try:

        payload_mode = (
            _normalize_mode(
                payload_mode
            )
        )

    except Exception:

        return False

    return (
        payload_mode
        == _normalize_mode(
            mode
        )
    )


# ============================================================
# PAYLOAD STOCKS
# ============================================================


def _payload_stocks(
    payload: dict[str, Any] | None,
    *,
    mode: str | None = None,
) -> list[
    dict[str, Any]
]:

    if not isinstance(
        payload,
        dict,
    ):

        return []

    if (
        mode is not None
        and not _payload_matches_mode(
            payload,
            mode,
        )
    ):

        return []

    stocks = payload.get(
        "stocks",
        [],
    )

    if not isinstance(
        stocks,
        list,
    ):

        return []

    return (
        _prepare_candidates(
            stocks
        )
    )


# ============================================================
# SAVE CURRENT DAY
# ============================================================


def save_current_day_candidates(
    stocks: Iterable[
        RankedStock
        | dict[str, Any]
    ],
    *,
    mode: str | None = None,
) -> list[
    dict[str, Any]
]:
    """
    Save today's mode-specific candidates.

    Intraday / BTST / Swing are stored separately.
    """

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    candidates = (
        _prepare_candidates(
            stocks
        )
    )

    payload = {
        "date": (
            _today_string()
        ),

        "mode": (
            normalized_mode
        ),

        "generated_at": (
            _now_ist()
            .isoformat()
        ),

        "count": (
            len(
                candidates
            )
        ),

        "stocks": (
            candidates
        ),
    }

    file_path = (
        get_current_file(
            normalized_mode
        )
    )

    _write_json(
        file_path,
        payload,
    )

    logger.info(
        (
            "Saved current candidates | "
            "mode=%s | count=%s"
        ),
        normalized_mode,
        len(
            candidates
        ),
    )

    return candidates


# ============================================================
# GET CURRENT DAY
# ============================================================


def get_current_day_candidates(
    *,
    mode: str | None = None,
) -> list[
    dict[str, Any]
]:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    payload = (
        _read_json(
            get_current_file(
                normalized_mode
            )
        )
    )

    return (
        _payload_stocks(
            payload,
            mode=(
                normalized_mode
            ),
        )
    )


# ============================================================
# GET PREVIOUS DAY
# ============================================================


def get_previous_day_candidates(
    *,
    mode: str | None = None,
) -> list[
    dict[str, Any]
]:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    payload = (
        _read_json(
            get_previous_file(
                normalized_mode
            )
        )
    )

    return (
        _payload_stocks(
            payload,
            mode=(
                normalized_mode
            ),
        )
    )


# ============================================================
# ARCHIVE CURRENT -> PREVIOUS
# ============================================================


def archive_current_as_previous(
    *,
    mode: str | None = None,
) -> bool:
    """
    Archive last available current file
    to previous file for same mode.

    This preserves Friday data for Monday,
    or last trading-day data after a holiday.
    """

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    current_file = (
        get_current_file(
            normalized_mode
        )
    )

    payload = (
        _read_json(
            current_file
        )
    )

    if not payload:

        logger.warning(
            (
                "No current candidates "
                "to archive | mode=%s"
            ),
            normalized_mode,
        )

        return False

    if not _payload_matches_mode(
        payload,
        normalized_mode,
    ):

        logger.error(
            (
                "Current candidate file "
                "mode mismatch | mode=%s"
            ),
            normalized_mode,
        )

        return False

    previous_file = (
        get_previous_file(
            normalized_mode
        )
    )

    _write_json(
        previous_file,
        payload,
    )

    logger.info(
        (
            "Archived current -> previous | "
            "mode=%s | date=%s"
        ),
        normalized_mode,
        payload.get(
            "date"
        ),
    )

    return True


# ============================================================
# DATE ROLLOVER
# ============================================================


def rollover_if_new_day(
    *,
    mode: str | None = None,
) -> bool:
    """
    On the first scan of a new IST date:

        old current -> previous

    Example:
        Friday current
            ↓
        Monday first scan
            ↓
        Friday becomes previous

    Therefore weekends/holidays work naturally.
    """

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    payload = (
        _read_json(
            get_current_file(
                normalized_mode
            )
        )
    )

    if not payload:

        return False

    if not _payload_matches_mode(
        payload,
        normalized_mode,
    ):

        logger.error(
            (
                "Current file mode mismatch "
                "during rollover | mode=%s"
            ),
            normalized_mode,
        )

        return False

    stored_date = clean_text(
        payload.get(
            "date"
        )
    )

    if not stored_date:

        return False

    today = (
        _today_string()
    )

    if stored_date == today:

        return False

    archived = (
        archive_current_as_previous(
            mode=(
                normalized_mode
            )
        )
    )

    if archived:

        logger.info(
            (
                "Trading date rollover | "
                "mode=%s | %s -> %s"
            ),
            normalized_mode,
            stored_date,
            today,
        )

    return archived


# ============================================================
# CALCULATE COMMON STOCKS
# ============================================================


def calculate_common_stocks(
    previous_stocks: Iterable[
        RankedStock
        | dict[str, Any]
    ],
    current_stocks: Iterable[
        RankedStock
        | dict[str, Any]
    ],
) -> list[
    dict[str, Any]
]:
    """
    Previous candidate universe
                ∩
    Current candidate universe
                ↓
    Common stocks
    """

    previous = (
        _prepare_candidates(
            previous_stocks
        )
    )

    current = (
        _prepare_candidates(
            current_stocks
        )
    )

    previous_by_symbol = {
        item[
            "symbol"
        ]: item

        for item in previous
    }

    common: list[
        dict[str, Any]
    ] = []

    for current_item in current:

        symbol = (
            current_item[
                "symbol"
            ]
        )

        previous_item = (
            previous_by_symbol
            .get(
                symbol
            )
        )

        if previous_item is None:

            continue

        previous_score = (
            _number(
                previous_item.get(
                    "score"
                )
            )
        )

        current_score = (
            _number(
                current_item.get(
                    "score"
                )
            )
        )

        average_score = (
            previous_score
            + current_score
        ) / 2.0

        current_sector = clean_text(
            current_item.get(
                "sector"
            )
        )

        previous_sector = clean_text(
            previous_item.get(
                "sector"
            )
        )

        row = {
            "symbol": (
                symbol
            ),

            "company_name": (
                clean_text(
                    current_item.get(
                        "company_name"
                    )
                    or previous_item.get(
                        "company_name"
                    )
                    or symbol
                )
            ),

            "sector": (
                current_sector
                or previous_sector
            ),

            "previous_score": round(
                previous_score,
                2,
            ),

            "current_score": round(
                current_score,
                2,
            ),

            "average_rank_score": round(
                average_score,
                2,
            ),
        }

        # Preserve useful current ranking data.
        optional_fields = (
            "mode",
            "momentum_score",
            "trend_score",
            "volume_score",
            "rsi_score",
            "relative_strength_score",
            "macd_score",
            "supertrend_score",
            "vwap_score",
            "breakout_score",
            "multi_timeframe_score",
        )

        for field in optional_fields:

            if field in current_item:

                row[
                    field
                ] = (
                    current_item[
                        field
                    ]
                )

        common.append(
            row
        )

    common.sort(
        key=lambda item: (
            -_number(
                item.get(
                    "average_rank_score"
                )
            ),

            -_number(
                item.get(
                    "current_score"
                )
            ),

            clean_text(
                item.get(
                    "symbol"
                )
            ),
        )
    )

    return common


# ============================================================
# SAVE COMMON STOCKS
# ============================================================


def save_common_stocks(
    stocks: Iterable[
        dict[str, Any]
    ],
    *,
    mode: str | None = None,
) -> list[
    dict[str, Any]
]:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    common: list[
        dict[str, Any]
    ] = []

    seen_symbols: set[
        str
    ] = set()

    for stock in stocks:

        if not isinstance(
            stock,
            dict,
        ):

            continue

        data = dict(
            stock
        )

        symbol = normalize_symbol(
            data.get(
                "symbol"
            )
        )

        if not symbol:

            continue

        if symbol in seen_symbols:

            continue

        seen_symbols.add(
            symbol
        )

        data[
            "symbol"
        ] = symbol

        data[
            "mode"
        ] = normalized_mode

        common.append(
            data
        )

    payload = {
        "date": (
            _today_string()
        ),

        "mode": (
            normalized_mode
        ),

        "generated_at": (
            _now_ist()
            .isoformat()
        ),

        "count": (
            len(
                common
            )
        ),

        "stocks": (
            common
        ),
    }

    file_path = (
        get_common_file(
            normalized_mode
        )
    )

    _write_json(
        file_path,
        payload,
    )

    logger.info(
        (
            "Saved common stocks | "
            "mode=%s | count=%s"
        ),
        normalized_mode,
        len(
            common
        ),
    )

    return common


# ============================================================
# GET COMMON STOCKS
# ============================================================


def get_common_stocks(
    *,
    mode: str | None = None,
) -> list[
    dict[str, Any]
]:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    payload = (
        _read_json(
            get_common_file(
                normalized_mode
            )
        )
    )

    if not payload:

        return []

    if not _payload_matches_mode(
        payload,
        normalized_mode,
    ):

        return []

    stocks = payload.get(
        "stocks",
        [],
    )

    if not isinstance(
        stocks,
        list,
    ):

        return []

    output: list[
        dict[str, Any]
    ] = []

    seen_symbols: set[
        str
    ] = set()

    for stock in stocks:

        if not isinstance(
            stock,
            dict,
        ):

            continue

        data = dict(
            stock
        )

        symbol = normalize_symbol(
            data.get(
                "symbol"
            )
        )

        if not symbol:

            continue

        if symbol in seen_symbols:

            continue

        seen_symbols.add(
            symbol
        )

        data[
            "symbol"
        ] = symbol

        data[
            "mode"
        ] = normalized_mode

        output.append(
            data
        )

    return output


# ============================================================
# BUILD + SAVE COMMON
# ============================================================


def build_and_save_common_stocks(
    *,
    mode: str | None = None,
) -> list[
    dict[str, Any]
]:
    """
    Read mode-specific previous/current files,
    calculate intersection and save common stocks.
    """

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    previous = (
        get_previous_day_candidates(
            mode=(
                normalized_mode
            )
        )
    )

    current = (
        get_current_day_candidates(
            mode=(
                normalized_mode
            )
        )
    )

    if not previous:

        logger.warning(
            (
                "Previous candidate list "
                "unavailable | mode=%s"
            ),
            normalized_mode,
        )

        return (
            save_common_stocks(
                [],
                mode=(
                    normalized_mode
                ),
            )
        )

    if not current:

        logger.warning(
            (
                "Current candidate list "
                "unavailable | mode=%s"
            ),
            normalized_mode,
        )

        return (
            save_common_stocks(
                [],
                mode=(
                    normalized_mode
                ),
            )
        )

    common = (
        calculate_common_stocks(
            previous_stocks=(
                previous
            ),
            current_stocks=(
                current
            ),
        )
    )

    return (
        save_common_stocks(
            common,
            mode=(
                normalized_mode
            ),
        )
    )


# ============================================================
# COMMON SYMBOLS
# ============================================================


def get_common_symbols(
    *,
    mode: str | None = None,
) -> list[str]:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    symbols: list[
        str
    ] = []

    seen_symbols: set[
        str
    ] = set()

    for item in (
        get_common_stocks(
            mode=(
                normalized_mode
            )
        )
    ):

        symbol = normalize_symbol(
            item.get(
                "symbol"
            )
        )

        if not symbol:

            continue

        if symbol in seen_symbols:

            continue

        seen_symbols.add(
            symbol
        )

        symbols.append(
            symbol
        )

    return symbols


# ============================================================
# STATUS
# ============================================================


def common_stock_status(
    *,
    mode: str | None = None,
) -> dict[str, Any]:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    current = (
        get_current_day_candidates(
            mode=(
                normalized_mode
            )
        )
    )

    previous = (
        get_previous_day_candidates(
            mode=(
                normalized_mode
            )
        )
    )

    common = (
        get_common_stocks(
            mode=(
                normalized_mode
            )
        )
    )

    return {
        "service": (
            "Common Stock Engine"
        ),

        "mode": (
            normalized_mode
        ),

        "current_count": (
            len(
                current
            )
        ),

        "previous_count": (
            len(
                previous
            )
        ),

        "common_count": (
            len(
                common
            )
        ),

        "current_file": (
            get_current_file(
                normalized_mode
            )
        ),

        "previous_file": (
            get_previous_file(
                normalized_mode
            )
        ),

        "common_file": (
            get_common_file(
                normalized_mode
            )
        ),

        "technical_only": True,

        "updated_at": (
            _now_ist()
            .isoformat()
        ),
    }
