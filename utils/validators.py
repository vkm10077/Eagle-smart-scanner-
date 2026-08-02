from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from utils.helpers import (
    clean_text,
    is_buy_signal,
    normalize_score,
    normalize_signal,
    normalize_symbol,
    normalize_timeframe,
    parse_datetime,
    safe_float,
    safe_int,
    utc_now,
)


ALLOWED_SIGNALS = {
    "BUY",
    "STRONG BUY",
    "NO TRADE",
    "REJECTED",
}

BUY_SIGNALS = {
    "BUY",
    "STRONG BUY",
}

MINIMUM_CANDLE_COUNT = {
    "15_30_days": 200,
    "3_month": 220,
    "6_month": 300,
    "1_year": 400,
    "3_year": 700,
}

MAX_DATA_AGE_MINUTES = {
    "quote": 15,
    "index": 15,
    "scan_result": 240,
    "daily_candle": 24 * 60,
    "fundamental": 45 * 24 * 60,
}

MINIMUM_RISK_REWARD = {
    "15_30_days": 1.80,
    "3_month": 2.00,
    "6_month": 2.20,
    "1_year": 2.40,
    "3_year": 2.50,
}

MINIMUM_PROBABILITY = {
    "15_30_days": 72.0,
    "3_month": 74.0,
    "6_month": 75.0,
    "1_year": 76.0,
    "3_year": 78.0,
}

MINIMUM_OVERALL_SCORE = {
    "15_30_days": 72.0,
    "3_month": 74.0,
    "6_month": 75.0,
    "1_year": 76.0,
    "3_year": 78.0,
}


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cleaned_data: dict[str, Any] = field(default_factory=dict)

    def add_error(self, message: str) -> None:
        normalized_message = clean_text(message)

        if normalized_message and normalized_message not in self.errors:
            self.errors.append(normalized_message)

        self.is_valid = False

    def add_warning(self, message: str) -> None:
        normalized_message = clean_text(message)

        if normalized_message and normalized_message not in self.warnings:
            self.warnings.append(normalized_message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "cleaned_data": dict(self.cleaned_data),
        }


def is_positive_number(value: Any) -> bool:
    number = safe_float(value)

    return number is not None and number > 0


def is_non_negative_number(value: Any) -> bool:
    number = safe_float(value)

    return number is not None and number >= 0


def is_valid_percentage(
    value: Any,
    *,
    minimum: float = -100.0,
    maximum: float = 1000.0,
) -> bool:
    number = safe_float(value)

    if number is None:
        return False

    return minimum <= number <= maximum


def is_valid_probability(value: Any) -> bool:
    number = safe_float(value)

    if number is None:
        return False

    return 0.0 <= number <= 100.0


def is_valid_price(value: Any) -> bool:
    price = safe_float(value)

    if price is None:
        return False

    return 0.01 <= price <= 10_000_000.0


def is_valid_volume(value: Any) -> bool:
    volume = safe_float(value)

    if volume is None:
        return False

    return volume >= 0


def is_valid_symbol(value: Any) -> bool:
    symbol = normalize_symbol(value)

    if not symbol:
        return False

    if len(symbol) > 40:
        return False

    allowed_characters = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&-_"
    )

    return all(
        character in allowed_characters
        for character in symbol
    )


def is_data_fresh(
    timestamp: Any,
    *,
    data_type: str = "quote",
    max_age_minutes: int | None = None,
    reference_time: datetime | None = None,
) -> bool:
    parsed_timestamp = parse_datetime(timestamp)

    if parsed_timestamp is None:
        return False

    if parsed_timestamp.tzinfo is None:
        parsed_timestamp = parsed_timestamp.replace(
            tzinfo=timezone.utc
        )

    now = reference_time or utc_now()

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    allowed_age = (
        max_age_minutes
        if max_age_minutes is not None
        else MAX_DATA_AGE_MINUTES.get(
            data_type,
            60,
        )
    )

    if parsed_timestamp > now + timedelta(minutes=5):
        return False

    age = now - parsed_timestamp

    return age <= timedelta(
        minutes=max(1, int(allowed_age))
    )


def validate_quote_data(
    quote: dict[str, Any] | None,
    *,
    require_fresh: bool = True,
) -> ValidationResult:
    result = ValidationResult(
        is_valid=True
    )

    if not isinstance(quote, dict):
        result.add_error(
            "Quote data is missing or invalid."
        )
        return result

    symbol = normalize_symbol(
        quote.get("symbol")
        or quote.get("n")
        or quote.get("ticker")
    )

    current_price = safe_float(
        quote.get("current_price")
        or quote.get("ltp")
        or quote.get("lp")
        or quote.get("last_price")
    )

    previous_close = safe_float(
        quote.get("previous_close")
        or quote.get("prev_close")
        or quote.get("close")
    )

    timestamp = (
        quote.get("timestamp")
        or quote.get("updated_at")
        or quote.get("exchange_timestamp")
    )

    if not is_valid_symbol(symbol):
        result.add_error(
            "Quote contains an invalid stock symbol."
        )

    if not is_valid_price(current_price):
        result.add_error(
            "Quote contains an invalid current price."
        )

    if previous_close is not None and not is_valid_price(
        previous_close
    ):
        result.add_warning(
            "Previous close is invalid."
        )

    if require_fresh and not is_data_fresh(
        timestamp,
        data_type="quote",
    ):
        result.add_error(
            "Quote data is stale."
        )

    result.cleaned_data = {
        "symbol": symbol,
        "current_price": current_price,
        "previous_close": previous_close,
        "timestamp": (
            parse_datetime(timestamp).isoformat()
            if parse_datetime(timestamp)
            else None
        ),
        "volume": safe_float(
            quote.get("volume")
            or quote.get("vol")
        ),
        "open": safe_float(
            quote.get("open")
            or quote.get("o")
        ),
        "high": safe_float(
            quote.get("high")
            or quote.get("h")
        ),
        "low": safe_float(
            quote.get("low")
            or quote.get("l")
        ),
    }

    return result


def validate_candle(
    candle: Any,
) -> tuple[bool, dict[str, Any] | None]:
    if isinstance(candle, dict):
        timestamp = (
            candle.get("timestamp")
            or candle.get("time")
            or candle.get("date")
        )
        open_price = candle.get("open")
        high_price = candle.get("high")
        low_price = candle.get("low")
        close_price = candle.get("close")
        volume = candle.get("volume")

    elif isinstance(candle, (list, tuple)) and len(candle) >= 6:
        timestamp = candle[0]
        open_price = candle[1]
        high_price = candle[2]
        low_price = candle[3]
        close_price = candle[4]
        volume = candle[5]

    else:
        return False, None

    open_number = safe_float(open_price)
    high_number = safe_float(high_price)
    low_number = safe_float(low_price)
    close_number = safe_float(close_price)
    volume_number = safe_float(
        volume,
        default=0.0,
    )

    if any(
        value is None
        for value in (
            open_number,
            high_number,
            low_number,
            close_number,
            volume_number,
        )
    ):
        return False, None

    if min(
        open_number,
        high_number,
        low_number,
        close_number,
    ) <= 0:
        return False, None

    if high_number < max(
        open_number,
        close_number,
        low_number,
    ):
        return False, None

    if low_number > min(
        open_number,
        close_number,
        high_number,
    ):
        return False, None

    if volume_number < 0:
        return False, None

    parsed_timestamp = parse_datetime(timestamp)

    if parsed_timestamp is None:
        timestamp_number = safe_int(timestamp)

        if timestamp_number is not None:
            try:
                parsed_timestamp = datetime.fromtimestamp(
                    timestamp_number,
                    tz=timezone.utc,
                )
            except (
                ValueError,
                OSError,
                OverflowError,
            ):
                parsed_timestamp = None

    if parsed_timestamp is None:
        return False, None

    return True, {
        "timestamp": parsed_timestamp.isoformat(),
        "open": open_number,
        "high": high_number,
        "low": low_number,
        "close": close_number,
        "volume": volume_number,
    }


def validate_candle_series(
    candles: Iterable[Any] | None,
    *,
    timeframe: Any,
) -> ValidationResult:
    result = ValidationResult(
        is_valid=True
    )

    normalized_timeframe = normalize_timeframe(
        timeframe
    )

    if candles is None:
        result.add_error(
            "Historical candle data is missing."
        )
        return result

    valid_candles: list[dict[str, Any]] = []
    invalid_count = 0

    for candle in candles:
        is_valid, cleaned_candle = validate_candle(
            candle
        )

        if not is_valid or cleaned_candle is None:
            invalid_count += 1
            continue

        valid_candles.append(cleaned_candle)

    valid_candles.sort(
        key=lambda item: item["timestamp"]
    )

    unique_candles: list[dict[str, Any]] = []
    seen_timestamps: set[str] = set()

    for candle in valid_candles:
        timestamp = candle["timestamp"]

        if timestamp in seen_timestamps:
            continue

        seen_timestamps.add(timestamp)
        unique_candles.append(candle)

    minimum_required = MINIMUM_CANDLE_COUNT.get(
        normalized_timeframe,
        220,
    )

    if len(unique_candles) < minimum_required:
        result.add_error(
            (
                f"Only {len(unique_candles)} valid candles are "
                f"available; at least {minimum_required} are required."
            )
        )

    if invalid_count > 0:
        result.add_warning(
            f"{invalid_count} invalid candles were removed."
        )

    if unique_candles:
        latest_timestamp = unique_candles[-1]["timestamp"]

        if not is_data_fresh(
            latest_timestamp,
            data_type="daily_candle",
        ):
            result.add_error(
                "Historical candle data is stale."
            )

    result.cleaned_data = {
        "timeframe": normalized_timeframe,
        "candles": unique_candles,
        "valid_count": len(unique_candles),
        "invalid_count": invalid_count,
    }

    return result


def validate_fundamental_data(
    fundamentals: dict[str, Any] | None,
    *,
    timeframe: Any,
) -> ValidationResult:
    result = ValidationResult(
        is_valid=True
    )

    normalized_timeframe = normalize_timeframe(
        timeframe
    )

    if not isinstance(fundamentals, dict):
        result.add_error(
            "Fundamental data is missing."
        )
        return result

    expected_fields = {
        "sales_growth",
        "profit_growth",
        "eps_growth",
        "roe",
        "roce",
        "debt_to_equity",
        "operating_cash_flow",
        "promoter_holding",
        "promoter_pledge",
        "valuation_score",
    }

    cleaned_data: dict[str, Any] = {}
    valid_field_count = 0

    for field_name in expected_fields:
        value = safe_float(
            fundamentals.get(field_name)
        )

        cleaned_data[field_name] = value

        if value is not None:
            valid_field_count += 1

    minimum_fields = (
        5
        if normalized_timeframe == "15_30_days"
        else 8
    )

    if valid_field_count < minimum_fields:
        result.add_error(
            (
                f"Only {valid_field_count} fundamental fields are "
                f"available; at least {minimum_fields} are required."
            )
        )

    debt_to_equity = cleaned_data.get(
        "debt_to_equity"
    )

    promoter_pledge = cleaned_data.get(
        "promoter_pledge"
    )

    operating_cash_flow = cleaned_data.get(
        "operating_cash_flow"
    )

    if debt_to_equity is not None and debt_to_equity < 0:
        result.add_warning(
            "Debt-to-equity value is unusual."
        )

    if promoter_pledge is not None and not (
        0 <= promoter_pledge <= 100
    ):
        result.add_error(
            "Promoter pledge percentage is invalid."
        )

    if operating_cash_flow is not None and abs(
        operating_cash_flow
    ) > 10**15:
        result.add_warning(
            "Operating cash flow value appears abnormal."
        )

    updated_at = (
        fundamentals.get("updated_at")
        or fundamentals.get("timestamp")
        or fundamentals.get("as_of")
    )

    if updated_at and not is_data_fresh(
        updated_at,
        data_type="fundamental",
    ):
        result.add_warning(
            "Fundamental data may be older than the preferred limit."
        )

    cleaned_data["updated_at"] = (
        parse_datetime(updated_at).isoformat()
        if parse_datetime(updated_at)
        else None
    )

    cleaned_data["valid_field_count"] = valid_field_count
    cleaned_data["timeframe"] = normalized_timeframe

    result.cleaned_data = cleaned_data

    return result


def validate_trade_levels(
    *,
    current_price: Any,
    entry_price: Any,
    stop_loss: Any,
    target_price: Any,
    timeframe: Any,
) -> ValidationResult:
    result = ValidationResult(
        is_valid=True
    )

    normalized_timeframe = normalize_timeframe(
        timeframe
    )

    current = safe_float(current_price)
    entry = safe_float(entry_price)
    stop = safe_float(stop_loss)
    target = safe_float(target_price)

    for label, value in (
        ("Current price", current),
        ("Entry price", entry),
        ("Stop-loss", stop),
        ("Target price", target),
    ):
        if not is_valid_price(value):
            result.add_error(
                f"{label} is invalid."
            )

    if not result.is_valid:
        return result

    assert current is not None
    assert entry is not None
    assert stop is not None
    assert target is not None

    if stop >= entry:
        result.add_error(
            "Stop-loss must be below the entry price."
        )

    if target <= entry:
        result.add_error(
            "Target price must be above the entry price."
        )

    maximum_entry_distance = {
        "15_30_days": 5.0,
        "3_month": 7.0,
        "6_month": 10.0,
        "1_year": 12.0,
        "3_year": 15.0,
    }.get(
        normalized_timeframe,
        7.0,
    )

    entry_distance_percent = abs(
        entry - current
    ) / current * 100

    if entry_distance_percent > maximum_entry_distance:
        result.add_error(
            "Entry price is too far from the current market price."
        )

    risk = entry - stop
    reward = target - entry

    risk_reward = (
        reward / risk
        if risk > 0
        else None
    )

    minimum_risk_reward = MINIMUM_RISK_REWARD.get(
        normalized_timeframe,
        2.0,
    )

    if risk_reward is None or risk_reward < minimum_risk_reward:
        result.add_error(
            (
                f"Risk-reward is below the required "
                f"{minimum_risk_reward:.2f}."
            )
        )

    stop_loss_percent = (
        risk / entry * 100
        if entry > 0
        else None
    )

    maximum_stop_loss_percent = {
        "15_30_days": 8.0,
        "3_month": 10.0,
        "6_month": 14.0,
        "1_year": 18.0,
        "3_year": 25.0,
    }.get(
        normalized_timeframe,
        10.0,
    )

    if (
        stop_loss_percent is not None
        and stop_loss_percent > maximum_stop_loss_percent
    ):
        result.add_error(
            "Stop-loss distance is too wide for the selected timeframe."
        )

    result.cleaned_data = {
        "current_price": round(current, 2),
        "entry_price": round(entry, 2),
        "stop_loss": round(stop, 2),
        "target_price": round(target, 2),
        "risk_reward": (
            round(risk_reward, 2)
            if risk_reward is not None
            else None
        ),
        "entry_distance_percent": round(
            entry_distance_percent,
            2,
        ),
        "stop_loss_percent": (
            round(stop_loss_percent, 2)
            if stop_loss_percent is not None
            else None
        ),
        "timeframe": normalized_timeframe,
    }

    return result


def validate_scan_result(
    scan_result: dict[str, Any] | None,
    *,
    require_buy_signal: bool = True,
    require_fresh: bool = True,
) -> ValidationResult:
    result = ValidationResult(
        is_valid=True
    )

    if not isinstance(scan_result, dict):
        result.add_error(
            "Scan result is missing or invalid."
        )
        return result

    timeframe = normalize_timeframe(
        scan_result.get("timeframe")
    )

    signal = normalize_signal(
        scan_result.get("signal")
    )

    symbol = normalize_symbol(
        scan_result.get("symbol")
    )

    stock_name = clean_text(
        scan_result.get("stock_name")
        or scan_result.get("company_name")
    )

    sector = clean_text(
        scan_result.get("sector"),
        default="Unknown",
    )

    probability = normalize_score(
        scan_result.get("move_up_probability")
    )

    overall_score = normalize_score(
        scan_result.get("overall_score")
    )

    if not stock_name:
        result.add_error(
            "Stock name is missing."
        )

    if symbol and not is_valid_symbol(symbol):
        result.add_error(
            "Stock symbol is invalid."
        )

    if signal not in ALLOWED_SIGNALS:
        result.add_error(
            "Signal value is invalid."
        )

    if require_buy_signal and not is_buy_signal(signal):
        result.add_error(
            "Result is not a BUY or STRONG BUY signal."
        )

    minimum_probability = MINIMUM_PROBABILITY.get(
        timeframe,
        74.0,
    )

    minimum_overall_score = MINIMUM_OVERALL_SCORE.get(
        timeframe,
        74.0,
    )

    if probability < minimum_probability:
        result.add_error(
            (
                f"Move-up probability is below "
                f"{minimum_probability:.0f}%."
            )
        )

    if overall_score < minimum_overall_score:
        result.add_error(
            (
                f"Overall score is below "
                f"{minimum_overall_score:.0f}."
            )
        )

    trade_validation = validate_trade_levels(
        current_price=scan_result.get(
            "current_price"
        ),
        entry_price=scan_result.get(
            "entry_price"
        ),
        stop_loss=scan_result.get(
            "stop_loss"
        ),
        target_price=scan_result.get(
            "target_price"
        ),
        timeframe=timeframe,
    )

    for error in trade_validation.errors:
        result.add_error(error)

    for warning in trade_validation.warnings:
        result.add_warning(warning)

    updated_at = (
        scan_result.get("updated_at")
        or scan_result.get("generated_at")
        or scan_result.get("timestamp")
    )

    if require_fresh and not is_data_fresh(
        updated_at,
        data_type="scan_result",
    ):
        result.add_error(
            "Scan result is stale."
        )

    result.cleaned_data = {
        **scan_result,
        "stock_name": stock_name,
        "sector": sector,
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": signal,
        "move_up_probability": probability,
        "overall_score": overall_score,
        "updated_at": (
            parse_datetime(updated_at).isoformat()
            if parse_datetime(updated_at)
            else None
        ),
        **trade_validation.cleaned_data,
    }

    return result


def filter_valid_scan_results(
    results: Iterable[dict[str, Any]] | None,
    *,
    require_buy_signal: bool = True,
    require_fresh: bool = True,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    if results is None:
        return [], []

    valid_results: list[dict[str, Any]] = []
    rejected_results: list[dict[str, Any]] = []

    seen_keys: set[tuple[str, str]] = set()

    for raw_result in results:
        validation = validate_scan_result(
            raw_result,
            require_buy_signal=require_buy_signal,
            require_fresh=require_fresh,
        )

        cleaned_result = validation.cleaned_data

        duplicate_key = (
            normalize_symbol(
                cleaned_result.get("symbol")
            )
            or clean_text(
                cleaned_result.get("stock_name")
            ).casefold(),
            normalize_timeframe(
                cleaned_result.get("timeframe")
            ),
        )

        if duplicate_key in seen_keys:
            validation.add_error(
                "Duplicate stock result was rejected."
            )

        if validation.is_valid:
            seen_keys.add(duplicate_key)
            valid_results.append(cleaned_result)
        else:
            rejected_results.append(
                {
                    "result": raw_result,
                    "errors": validation.errors,
                    "warnings": validation.warnings,
                }
            )

    return valid_results, rejected_results
