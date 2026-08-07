from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pytz

from config import Config
from services.stock_ranker import RankedStock


logger = logging.getLogger(__name__)


INDIA_TZ = pytz.timezone(
    Config.MARKET_TIMEZONE
)


# ============================================================
# MODE
# ============================================================

def _normalize_mode(
    mode: str | None,
) -> str:
    return Config.normalize_trading_mode(
        mode
        or Config.DEFAULT_TRADING_MODE
    )


# ============================================================
# FILE PATHS
# ============================================================

def _mode_file_path(
    base_file: str,
    mode: str,
) -> str:
    """
    Convert:

        current_candidates.json

    into:

        current_candidates_swing.json
        current_candidates_intraday.json
    """

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    path = Path(
        base_file
    )

    suffix = (
        path.suffix
        or ".json"
    )

    stem = (
        path.stem
        if path.suffix
        else path.name
    )

    final_name = (
        f"{stem}_"
        f"{normalized_mode}"
        f"{suffix}"
    )

    return str(
        path.with_name(
            final_name
        )
    )


def get_current_file(
    mode: str,
) -> str:
    return _mode_file_path(
        Config.CURRENT_DAY_FILE,
        mode,
    )


def get_previous_file(
    mode: str,
) -> str:
    return _mode_file_path(
        Config.PREVIOUS_DAY_FILE,
        mode,
    )


def get_common_file(
    mode: str,
) -> str:
    return _mode_file_path(
        Config.COMMON_STOCKS_FILE,
        mode,
    )


# ============================================================
# TIME
# ============================================================

def _now_ist() -> datetime:
    return datetime.now(
        INDIA_TZ
    )


def _today_string() -> str:
    return (
        _now_ist()
        .strftime(
            "%Y-%m-%d"
        )
    )


# ============================================================
# DIRECTORY
# ============================================================

def _ensure_data_dir() -> None:
    os.makedirs(
        Config.DATA_DIR,
        exist_ok=True,
    )


# ============================================================
# NORMALIZE STOCK
# ============================================================

def _stock_to_dict(
    stock: RankedStock | dict,
) -> dict:

    if isinstance(
        stock,
        RankedStock,
    ):
        data = asdict(
            stock
        )

    else:
        data = dict(
            stock
        )

    symbol = str(
        data.get(
            "symbol",
            ""
        )
    ).strip().upper()

    company_name = str(
        data.get(
            "company_name",
            symbol,
        )
    ).strip()

    sector = str(
        data.get(
            "sector",
            ""
        )
    ).strip()

    try:
        score = float(
            data.get(
                "score",
                data.get(
                    "current_score",
                    0.0,
                ),
            )
            or 0.0
        )

    except (
        TypeError,
        ValueError,
    ):
        score = 0.0

    return {
        "symbol": symbol,

        "company_name": (
            company_name
            or symbol
        ),

        "sector": sector,

        "score": round(
            score,
            2,
        ),
    }


def _prepare_candidates(
    stocks: Iterable[
        RankedStock | dict
    ],
) -> list[dict]:

    output: list[
        dict
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

        symbol = (
            data["symbol"]
        )

        if not symbol:
            continue

        if (
            symbol
            in seen_symbols
        ):
            continue

        seen_symbols.add(
            symbol
        )

        output.append(
            data
        )

    return output


# ============================================================
# JSON
# ============================================================

def _write_json(
    file_path: str,
    payload: dict,
) -> None:

    _ensure_data_dir()

    temp_path = (
        file_path
        + ".tmp"
    )

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


def _read_json(
    file_path: str,
) -> dict | None:

    if not os.path.exists(
        file_path
    ):
        return None

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
            "Unable to read file: %s",
            file_path,
        )

        return None


# ============================================================
# PAYLOAD VALIDATION
# ============================================================

def _payload_stocks(
    payload: dict | None,
) -> list[dict]:

    if not isinstance(
        payload,
        dict,
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

    return _prepare_candidates(
        stocks
    )


# ============================================================
# CURRENT DAY
# ============================================================

def save_current_day_candidates(
    stocks: Iterable[
        RankedStock | dict
    ],
    *,
    mode: str | None = None,
) -> list[dict]:

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

        "count": len(
            candidates
        ),

        "stocks": (
            candidates
        ),
    }

    _write_json(
        get_current_file(
            normalized_mode
        ),
        payload,
    )

    logger.info(
        (
            "Saved %s current-day "
            "candidates for %s."
        ),
        len(
            candidates
        ),
        normalized_mode,
    )

    return candidates


def get_current_day_candidates(
    *,
    mode: str | None = None,
) -> list[dict]:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    payload = _read_json(
        get_current_file(
            normalized_mode
        )
    )

    return _payload_stocks(
        payload
    )


# ============================================================
# PREVIOUS DAY
# ============================================================

def get_previous_day_candidates(
    *,
    mode: str | None = None,
) -> list[dict]:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    payload = _read_json(
        get_previous_file(
            normalized_mode
        )
    )

    return _payload_stocks(
        payload
    )


def archive_current_as_previous(
    *,
    mode: str | None = None,
) -> bool:

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
                "No current candidate "
                "file available for %s."
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
            "Archived %s current "
            "candidates as previous."
        ),
        normalized_mode,
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
    Archive the last saved current candidate list only when
    its stored trading date differs from today's IST date.

    This means Friday can correctly become the previous list
    when the next scan happens Monday.
    """

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    payload = _read_json(
        get_current_file(
            normalized_mode
        )
    )

    if not payload:
        return False

    stored_date = str(
        payload.get(
            "date",
            ""
        )
    ).strip()

    if not stored_date:
        return False

    today = (
        _today_string()
    )

    if (
        stored_date
        == today
    ):
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
                "Trading-day rollover "
                "completed for %s | "
                "%s -> %s"
            ),
            normalized_mode,
            stored_date,
            today,
        )

    return archived


# ============================================================
# COMMON CALCULATION
# ============================================================

def calculate_common_stocks(
    previous_stocks: Iterable[
        RankedStock | dict
    ],
    current_stocks: Iterable[
        RankedStock | dict
    ],
) -> list[dict]:

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
        item["symbol"]: item
        for item
        in previous
    }

    common: list[
        dict
    ] = []

    for current_item in current:

        symbol = (
            current_item[
                "symbol"
            ]
        )

        previous_item = (
            previous_by_symbol.get(
                symbol
            )
        )

        if previous_item is None:
            continue

        previous_score = float(
            previous_item.get(
                "score",
                0.0,
            )
            or 0.0
        )

        current_score = float(
            current_item.get(
                "score",
                0.0,
            )
            or 0.0
        )

        average_score = (
            previous_score
            + current_score
        ) / 2.0

        common.append(
            {
                "symbol": (
                    symbol
                ),

                "company_name": (
                    current_item.get(
                        "company_name"
                    )
                    or previous_item.get(
                        "company_name"
                    )
                    or symbol
                ),

                "sector": (
                    current_item.get(
                        "sector"
                    )
                    or previous_item.get(
                        "sector"
                    )
                    or ""
                ),

                "previous_score": (
                    round(
                        previous_score,
                        2,
                    )
                ),

                "current_score": (
                    round(
                        current_score,
                        2,
                    )
                ),

                "average_rank_score": (
                    round(
                        average_score,
                        2,
                    )
                ),
            }
        )

    common.sort(
        key=lambda item: (
            -float(
                item[
                    "average_rank_score"
                ]
            ),
            -float(
                item[
                    "current_score"
                ]
            ),
            item[
                "symbol"
            ],
        )
    )

    return common


# ============================================================
# SAVE COMMON
# ============================================================

def save_common_stocks(
    stocks: Iterable[
        dict
    ],
    *,
    mode: str | None = None,
) -> list[dict]:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    common = [
        dict(
            stock
        )
        for stock
        in stocks
    ]

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

    _write_json(
        get_common_file(
            normalized_mode
        ),
        payload,
    )

    logger.info(
        (
            "Saved %s common stocks "
            "for %s."
        ),
        len(
            common
        ),
        normalized_mode,
    )

    return common


# ============================================================
# GET COMMON
# ============================================================

def get_common_stocks(
    *,
    mode: str | None = None,
) -> list[dict]:

    normalized_mode = (
        _normalize_mode(
            mode
        )
    )

    payload = _read_json(
        get_common_file(
            normalized_mode
        )
    )

    if not payload:
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

    return [
        dict(
            stock
        )
        for stock
        in stocks
        if isinstance(
            stock,
            dict,
        )
    ]


# ============================================================
# BUILD COMMON
# ============================================================

def build_and_save_common_stocks(
    *,
    mode: str | None = None,
) -> list[dict]:

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
                "Previous-day candidate "
                "list unavailable for %s."
            ),
            normalized_mode,
        )

        return save_common_stocks(
            [],
            mode=(
                normalized_mode
            ),
        )

    if not current:

        logger.warning(
            (
                "Current-day candidate "
                "list unavailable for %s."
            ),
            normalized_mode,
        )

        return save_common_stocks(
            [],
            mode=(
                normalized_mode
            ),
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

    return save_common_stocks(
        common,
        mode=(
            normalized_mode
        ),
    )


# ============================================================
# COMMON SYMBOLS
# ============================================================

def get_common_symbols(
    *,
    mode: str | None = None,
) -> list[str]:

    return [
        str(
            item.get(
                "symbol",
                ""
            )
        )
        .strip()
        .upper()

        for item
        in get_common_stocks(
            mode=mode
        )

        if item.get(
            "symbol"
        )
    ]
