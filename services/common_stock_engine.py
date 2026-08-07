from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from typing import Iterable

import pytz

from config import Config
from services.stock_ranker import RankedStock


logger = logging.getLogger(__name__)


INDIA_TZ = pytz.timezone(Config.MARKET_TIMEZONE)


def _ensure_data_dir() -> None:
    os.makedirs(
        Config.DATA_DIR,
        exist_ok=True,
    )


def _now_ist() -> datetime:
    return datetime.now(
        INDIA_TZ
    )


def _today_string() -> str:
    return _now_ist().strftime(
        "%Y-%m-%d"
    )


def _stock_to_dict(
    stock: RankedStock | dict,
) -> dict:
    if isinstance(
        stock,
        RankedStock,
    ):
        data = asdict(stock)
    else:
        data = dict(stock)

    symbol = str(
        data.get("symbol", "")
    ).strip().upper()

    sector = str(
        data.get("sector", "")
    ).strip()

    company_name = str(
        data.get(
            "company_name",
            symbol,
        )
    ).strip()

    score = float(
        data.get(
            "score",
            0.0,
        )
        or 0.0
    )

    return {
        "symbol": symbol,
        "company_name": company_name,
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
    output: list[dict] = []
    seen_symbols: set[str] = set()

    for stock in stocks:
        data = _stock_to_dict(
            stock
        )

        symbol = data["symbol"]

        if not symbol:
            continue

        if symbol in seen_symbols:
            continue

        seen_symbols.add(
            symbol
        )

        output.append(
            data
        )

    return output


def _write_json(
    file_path: str,
    payload: dict,
) -> None:
    _ensure_data_dir()

    temp_path = (
        file_path + ".tmp"
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


def save_current_day_candidates(
    stocks: Iterable[
        RankedStock | dict
    ],
) -> list[dict]:
    """
    Save today's Top Sector × Top Stock
    candidate universe.

    Maximum expected:
        10 sectors × 10 stocks = 100 stocks
    """

    candidates = (
        _prepare_candidates(
            stocks
        )
    )

    payload = {
        "date": _today_string(),
        "generated_at": (
            _now_ist().isoformat()
        ),
        "count": len(
            candidates
        ),
        "stocks": candidates,
    }

    _write_json(
        Config.CURRENT_DAY_FILE,
        payload,
    )

    logger.info(
        "Saved %s current-day candidates.",
        len(candidates),
    )

    return candidates


def get_current_day_candidates() -> list[dict]:
    payload = _read_json(
        Config.CURRENT_DAY_FILE
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

    return _prepare_candidates(
        stocks
    )


def get_previous_day_candidates() -> list[dict]:
    payload = _read_json(
        Config.PREVIOUS_DAY_FILE
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

    return _prepare_candidates(
        stocks
    )


def archive_current_as_previous() -> bool:
    """
    Move/copy the latest current-day
    candidate list into previous-day storage.

    This should be called once when a new
    trading day starts, BEFORE overwriting
    current-day candidates with the new day.
    """

    payload = _read_json(
        Config.CURRENT_DAY_FILE
    )

    if not payload:
        logger.warning(
            "No current-day candidate file "
            "available to archive."
        )
        return False

    _write_json(
        Config.PREVIOUS_DAY_FILE,
        payload,
    )

    logger.info(
        "Current candidates archived "
        "as previous day."
    )

    return True


def calculate_common_stocks(
    previous_stocks: Iterable[
        RankedStock | dict
    ],
    current_stocks: Iterable[
        RankedStock | dict
    ],
) -> list[dict]:
    """
    Previous Day ∩ Current Day

    Only symbols present in BOTH lists
    survive for final technical analysis.
    """

    previous = _prepare_candidates(
        previous_stocks
    )

    current = _prepare_candidates(
        current_stocks
    )

    previous_by_symbol = {
        item["symbol"]: item
        for item in previous
    }

    common: list[dict] = []

    for current_item in current:
        symbol = current_item[
            "symbol"
        ]

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
                "symbol": symbol,
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
        )

    common.sort(
        key=lambda item: (
            -item[
                "average_rank_score"
            ],
            -item[
                "current_score"
            ],
            item["symbol"],
        )
    )

    return common


def save_common_stocks(
    stocks: Iterable[dict],
) -> list[dict]:
    common = [
        dict(stock)
        for stock in stocks
    ]

    payload = {
        "date": _today_string(),
        "generated_at": (
            _now_ist().isoformat()
        ),
        "count": len(common),
        "stocks": common,
    }

    _write_json(
        Config.COMMON_STOCKS_FILE,
        payload,
    )

    logger.info(
        "Saved %s common stocks.",
        len(common),
    )

    return common


def get_common_stocks() -> list[dict]:
    payload = _read_json(
        Config.COMMON_STOCKS_FILE
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
        dict(stock)
        for stock in stocks
    ]


def build_and_save_common_stocks() -> list[dict]:
    """
    Read saved previous/current lists,
    calculate intersection,
    save it,
    and return it.
    """

    previous = (
        get_previous_day_candidates()
    )

    current = (
        get_current_day_candidates()
    )

    if not previous:
        logger.warning(
            "Previous-day candidate list "
            "is not available yet."
        )

        save_common_stocks(
            []
        )

        return []

    if not current:
        logger.warning(
            "Current-day candidate list "
            "is not available yet."
        )

        save_common_stocks(
            []
        )

        return []

    common = calculate_common_stocks(
        previous_stocks=previous,
        current_stocks=current,
    )

    return save_common_stocks(
        common
    )


def get_common_symbols() -> list[str]:
    return [
        str(
            item.get(
                "symbol",
                "",
            )
        ).strip().upper()
        for item in get_common_stocks()
        if item.get("symbol")
    ]
