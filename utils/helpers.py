from __future__ import annotations

import hashlib
import math
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")

SUPPORTED_TIMEFRAMES = {
    "15_30_days": {
        "label": "15–30 Days",
        "holding_period": "15–30 Days",
        "history_days": 220,
        "candle_resolution": "D",
    },
    "3_month": {
        "label": "3 Months",
        "holding_period": "Up to 3 Months",
        "history_days": 365,
        "candle_resolution": "D",
    },
    "6_month": {
        "label": "6 Months",
        "holding_period": "Up to 6 Months",
        "history_days": 550,
        "candle_resolution": "D",
    },
    "1_year": {
        "label": "1 Year",
        "holding_period": "Up to 1 Year",
        "history_days": 900,
        "candle_resolution": "D",
    },
    "3_year": {
        "label": "3 Years",
        "holding_period": "Up to 3 Years",
        "history_days": 1600,
        "candle_resolution": "D",
    },
}

TIMEFRAME_ALIASES = {
    "swing": "15_30_days",
    "15_day": "15_30_days",
    "15_days": "15_30_days",
    "15-30-days": "15_30_days",
    "15_30_day": "15_30_days",
    "1_month": "15_30_days",
    "3month": "3_month",
    "3_months": "3_month",
    "quarterly": "3_month",
    "quarter": "3_month",
    "6month": "6_month",
    "6_months": "6_month",
    "half_year": "6_month",
    "half_yearly": "6_month",
    "1year": "1_year",
    "1_years": "1_year",
    "yearly": "1_year",
    "annual": "1_year",
    "3year": "3_year",
    "3_years": "3_year",
    "long_term": "3_year",
}

SIGNAL_PRIORITY = {
    "STRONG BUY": 2,
    "BUY": 1,
    "NO TRADE": 0,
    "REJECTED": -1,
}

INVALID_TEXT_VALUES = {
    "",
    "nan",
    "none",
    "null",
    "undefined",
    "n/a",
    "na",
    "-",
    "--",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ist_now() -> datetime:
    return datetime.now(IST)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def ensure_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(IST)


def format_datetime(
    value: datetime | None,
    *,
    timezone_name: str = "Asia/Kolkata",
    date_format: str = "%d %b %Y, %I:%M:%S %p",
) -> str:
    if value is None:
        return "-"

    try:
        target_timezone = ZoneInfo(timezone_name)

        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(target_timezone).strftime(
            date_format
        )

    except Exception:
        return "-"


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value

    text = clean_text(value)

    if not text:
        return None

    normalized_text = text.replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(normalized_text)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed

    except ValueError:
        pass

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
    )

    for date_format in formats:
        try:
            parsed = datetime.strptime(
                text,
                date_format,
            )

            return parsed.replace(
                tzinfo=timezone.utc
            )

        except ValueError:
            continue

    return None


def clean_text(
    value: Any,
    *,
    default: str = "",
    max_length: int | None = None,
) -> str:
    if value is None:
        return default

    text = str(value).strip()

    if text.casefold() in INVALID_TEXT_VALUES:
        return default

    text = " ".join(text.split())

    if max_length is not None:
        text = text[: max(0, int(max_length))]

    return text


def slugify(value: Any) -> str:
    text = clean_text(value).casefold()

    text = re.sub(
        r"[^a-z0-9]+",
        "-",
        text,
    )

    return text.strip("-")


def normalize_symbol(value: Any) -> str:
    symbol = clean_text(value).upper()

    symbol = symbol.replace("NSE:", "")
    symbol = symbol.replace("BSE:", "")
    symbol = symbol.replace(".NS", "")
    symbol = symbol.replace(".BO", "")
    symbol = symbol.replace("-EQ", "")
    symbol = symbol.strip()

    return symbol


def to_fyers_symbol(
    value: Any,
    *,
    exchange: str = "NSE",
    series: str = "EQ",
) -> str:
    symbol = normalize_symbol(value)

    if not symbol:
        return ""

    return (
        f"{clean_text(exchange, default='NSE').upper()}:"
        f"{symbol}-"
        f"{clean_text(series, default='EQ').upper()}"
    )


def normalize_timeframe(
    value: Any,
    *,
    default: str = "3_month",
) -> str:
    timeframe = clean_text(value).casefold()

    timeframe = timeframe.replace(" ", "_")
    timeframe = timeframe.replace("-", "_")

    if timeframe in SUPPORTED_TIMEFRAMES:
        return timeframe

    if timeframe in TIMEFRAME_ALIASES:
        return TIMEFRAME_ALIASES[timeframe]

    return (
        default
        if default in SUPPORTED_TIMEFRAMES
        else "3_month"
    )


def get_timeframe_config(
    value: Any,
) -> dict[str, Any]:
    timeframe = normalize_timeframe(value)

    return {
        "key": timeframe,
        **SUPPORTED_TIMEFRAMES[timeframe],
    }


def get_holding_period(
    timeframe: Any,
) -> str:
    return str(
        get_timeframe_config(
            timeframe
        )["holding_period"]
    )


def safe_float(
    value: Any,
    *,
    default: float | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value is None:
        return default

    if isinstance(value, bool):
        return default

    try:
        if isinstance(value, str):
            normalized = value.strip()

            if normalized.casefold() in INVALID_TEXT_VALUES:
                return default

            normalized = normalized.replace(",", "")
            normalized = normalized.replace("%", "")
            normalized = normalized.replace("₹", "")
            normalized = normalized.strip()

            number = float(
                Decimal(normalized)
            )
        else:
            number = float(value)

    except (
        ValueError,
        TypeError,
        InvalidOperation,
        OverflowError,
    ):
        return default

    if not math.isfinite(number):
        return default

    if minimum is not None:
        number = max(number, minimum)

    if maximum is not None:
        number = min(number, maximum)

    return number


def safe_int(
    value: Any,
    *,
    default: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    number = safe_float(
        value,
        default=None,
    )

    if number is None:
        return default

    integer = int(number)

    if minimum is not None:
        integer = max(integer, minimum)

    if maximum is not None:
        integer = min(integer, maximum)

    return integer


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(
        minimum,
        min(maximum, value),
    )


def round_price(
    value: Any,
    *,
    digits: int = 2,
) -> float | None:
    number = safe_float(value)

    if number is None:
        return None

    return round(
        number,
        max(0, int(digits)),
    )


def format_price(
    value: Any,
    *,
    currency_symbol: str = "₹",
    digits: int = 2,
) -> str:
    number = safe_float(value)

    if number is None:
        return "-"

    return (
        f"{currency_symbol}"
        f"{number:,.{max(0, int(digits))}f}"
    )


def format_percentage(
    value: Any,
    *,
    digits: int = 2,
    include_sign: bool = False,
) -> str:
    number = safe_float(value)

    if number is None:
        return "-"

    sign_format = "+" if include_sign else ""

    return (
        f"{number:{sign_format}.{max(0, int(digits))}f}%"
    )


def percentage_change(
    current_value: Any,
    previous_value: Any,
) -> float | None:
    current = safe_float(current_value)
    previous = safe_float(previous_value)

    if current is None or previous in {
        None,
        0.0,
    }:
        return None

    return round(
        ((current - previous) / previous) * 100,
        4,
    )


def calculate_risk_reward(
    entry_price: Any,
    stop_loss: Any,
    target_price: Any,
) -> float | None:
    entry = safe_float(entry_price)
    stop = safe_float(stop_loss)
    target = safe_float(target_price)

    if None in {
        entry,
        stop,
        target,
    }:
        return None

    risk = entry - stop
    reward = target - entry

    if risk <= 0 or reward <= 0:
        return None

    return round(
        reward / risk,
        2,
    )


def calculate_expected_return(
    entry_price: Any,
    target_price: Any,
) -> float | None:
    entry = safe_float(entry_price)
    target = safe_float(target_price)

    if entry is None or target is None or entry <= 0:
        return None

    return round(
        ((target - entry) / entry) * 100,
        2,
    )


def calculate_stop_loss_percent(
    entry_price: Any,
    stop_loss: Any,
) -> float | None:
    entry = safe_float(entry_price)
    stop = safe_float(stop_loss)

    if entry is None or stop is None or entry <= 0:
        return None

    return round(
        ((entry - stop) / entry) * 100,
        2,
    )


def average(
    values: Iterable[Any],
) -> float | None:
    valid_values = [
        number
        for item in values
        if (
            number := safe_float(item)
        ) is not None
    ]

    if not valid_values:
        return None

    return sum(valid_values) / len(valid_values)


def weighted_average(
    values: Sequence[tuple[Any, Any]],
) -> float | None:
    weighted_total = 0.0
    total_weight = 0.0

    for raw_value, raw_weight in values:
        value = safe_float(raw_value)
        weight = safe_float(raw_weight)

        if value is None or weight is None:
            continue

        if weight <= 0:
            continue

        weighted_total += value * weight
        total_weight += weight

    if total_weight <= 0:
        return None

    return weighted_total / total_weight


def normalize_score(
    value: Any,
    *,
    minimum: float = 0.0,
    maximum: float = 100.0,
) -> float:
    score = safe_float(
        value,
        default=minimum,
    )

    if score is None:
        score = minimum

    return round(
        clamp(
            score,
            minimum,
            maximum,
        ),
        2,
    )


def normalize_signal(value: Any) -> str:
    signal = clean_text(value).upper()

    aliases = {
        "STRONGBUY": "STRONG BUY",
        "STRONG_BUY": "STRONG BUY",
        "BUY": "BUY",
        "WATCH": "NO TRADE",
        "WATCHLIST": "NO TRADE",
        "HOLD": "NO TRADE",
        "NEUTRAL": "NO TRADE",
        "SELL": "NO TRADE",
        "REJECT": "REJECTED",
        "REJECTED": "REJECTED",
    }

    return aliases.get(
        signal,
        signal if signal else "NO TRADE",
    )


def is_buy_signal(value: Any) -> bool:
    return normalize_signal(value) in {
        "BUY",
        "STRONG BUY",
    }


def signal_sort_key(
    result: dict[str, Any],
) -> tuple[int, float, float]:
    signal = normalize_signal(
        result.get("signal")
    )

    probability = safe_float(
        result.get("move_up_probability"),
        default=0.0,
    ) or 0.0

    score = safe_float(
        result.get("overall_score"),
        default=0.0,
    ) or 0.0

    return (
        SIGNAL_PRIORITY.get(signal, -2),
        probability,
        score,
    )


def sort_scan_results(
    results: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        list(results),
        key=signal_sort_key,
        reverse=True,
    )


def filter_buy_results(
    results: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    valid_results = [
        item
        for item in results
        if is_buy_signal(
            item.get("signal")
        )
    ]

    return sort_scan_results(valid_results)


def generate_request_id(
    prefix: str = "req",
) -> str:
    timestamp = utc_now().strftime(
        "%Y%m%d%H%M%S"
    )

    random_part = secrets.token_hex(4)

    return f"{prefix}-{timestamp}-{random_part}"


def stable_hash(
    value: Any,
    *,
    length: int = 16,
) -> str:
    encoded_value = str(value).encode(
        "utf-8",
        errors="ignore",
    )

    digest = hashlib.sha256(
        encoded_value
    ).hexdigest()

    safe_length = max(
        4,
        min(int(length), len(digest)),
    )

    return digest[:safe_length]


def build_cache_key(
    *parts: Any,
    prefix: str = "eagle",
) -> str:
    normalized_parts = [
        clean_text(
            part,
            default="none",
        ).casefold()
        for part in parts
    ]

    joined = ":".join(normalized_parts)

    return f"{prefix}:{stable_hash(joined, length=24)}"


def chunked(
    items: Sequence[Any],
    size: int,
) -> list[list[Any]]:
    safe_size = max(1, int(size))

    return [
        list(
            items[index:index + safe_size]
        )
        for index in range(
            0,
            len(items),
            safe_size,
        )
    ]


def unique_items(
    values: Iterable[Any],
) -> list[Any]:
    seen: set[Any] = set()
    unique: list[Any] = []

    for value in values:
        try:
            marker = value
            already_seen = marker in seen
        except TypeError:
            marker = repr(value)
            already_seen = marker in seen

        if already_seen:
            continue

        seen.add(marker)
        unique.append(value)

    return unique


def mask_secret(
    value: Any,
    *,
    visible_start: int = 3,
    visible_end: int = 2,
) -> str:
    secret_value = clean_text(value)

    if not secret_value:
        return ""

    start = max(0, int(visible_start))
    end = max(0, int(visible_end))

    if len(secret_value) <= start + end:
        return "*" * len(secret_value)

    masked_length = len(secret_value) - start - end

    return (
        secret_value[:start]
        + ("*" * masked_length)
        + secret_value[-end:]
    )


def build_stock_result(
    *,
    company_name: Any,
    sector: Any,
    current_price: Any,
    entry_price: Any,
    stop_loss: Any,
    target_price: Any,
    move_up_probability: Any,
    timeframe: Any,
    signal: Any,
    overall_score: Any = None,
    symbol: Any = None,
    updated_at: datetime | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_timeframe = normalize_timeframe(
        timeframe
    )

    normalized_signal = normalize_signal(
        signal
    )

    result = {
        "stock_name": clean_text(
            company_name,
            default="Unknown",
        ),
        "sector": clean_text(
            sector,
            default="Unknown",
        ),
        "current_price": round_price(
            current_price
        ),
        "entry_price": round_price(
            entry_price
        ),
        "stop_loss": round_price(
            stop_loss
        ),
        "target_price": round_price(
            target_price
        ),
        "move_up_probability": normalize_score(
            move_up_probability
        ),
        "holding_period": get_holding_period(
            normalized_timeframe
        ),
        "timeframe": normalized_timeframe,
        "signal": normalized_signal,
        "overall_score": normalize_score(
            overall_score
        ),
        "updated_at": (
            updated_at or utc_now()
        ).isoformat(),
        "risk_reward": calculate_risk_reward(
            entry_price,
            stop_loss,
            target_price,
        ),
        "expected_return": calculate_expected_return(
            entry_price,
            target_price,
        ),
        "details": details or {},
    }

    normalized_symbol = normalize_symbol(symbol)

    if normalized_symbol:
        result["symbol"] = normalized_symbol

    return result
