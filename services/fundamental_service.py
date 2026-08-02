from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any

import requests

from services.cache_service import (
    CacheService,
    get_cache_service,
)
from utils.helpers import (
    build_cache_key,
    clean_text,
    normalize_symbol,
    normalize_timeframe,
    safe_float,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_api_call,
    log_exception,
)
from utils.validators import (
    validate_fundamental_data,
)


logger = get_logger(
    "services.fundamental_service"
)


class FundamentalDataError(RuntimeError):
    """Base error for fundamental-data failures."""


class FundamentalConfigurationError(
    FundamentalDataError
):
    """Raised when the fundamental API is not configured."""


class FundamentalDataUnavailableError(
    FundamentalDataError
):
    """Raised when verified company data is unavailable."""


class FundamentalService:
    """
    Verified fundamental-data service.

    Data source:
    Financial Modeling Prep stable API.

    The service never invents missing values. A missing field remains
    None and is handled by validation/scoring rules.
    """

    BASE_URL = (
        "https://financialmodelingprep.com/stable"
    )

    REQUEST_TIMEOUT_SECONDS = 30
    CACHE_SECONDS = 12 * 60 * 60
    ERROR_CACHE_SECONDS = 15 * 60

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cache_service: CacheService | None = None,
    ) -> None:
        self.api_key = clean_text(
            api_key
            or os.getenv("FMP_API_KEY", "")
        )

        self.cache_service = (
            cache_service
            or get_cache_service()
        )

        self._request_lock = threading.RLock()

        self._session = requests.Session()

        self._session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": (
                    "Eagle-Smart-Scanner/1.0"
                ),
            }
        )

    # ==========================================================
    # CONFIGURATION
    # ==========================================================

    def configuration_status(
        self,
    ) -> dict[str, Any]:
        return {
            "configured": bool(self.api_key),
            "provider": (
                "Financial Modeling Prep"
            ),
            "missing_fields": (
                []
                if self.api_key
                else ["FMP_API_KEY"]
            ),
            "checked_at": (
                utc_now().isoformat()
            ),
        }

    def validate_configuration(
        self,
    ) -> None:
        if not self.api_key:
            raise FundamentalConfigurationError(
                "FMP_API_KEY is not configured."
            )

    # ==========================================================
    # SYMBOL HANDLING
    # ==========================================================

    @staticmethod
    def to_provider_symbol(
        symbol: Any,
    ) -> str:
        normalized_symbol = normalize_symbol(
            symbol
        )

        if not normalized_symbol:
            return ""

        return f"{normalized_symbol}.NS"

    # ==========================================================
    # REQUEST HELPERS
    # ==========================================================

    def _request(
        self,
        endpoint: str,
        *,
        symbol: str,
        period: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self.validate_configuration()

        provider_symbol = (
            self.to_provider_symbol(symbol)
        )

        if not provider_symbol:
            raise ValueError(
                "A valid stock symbol is required."
            )

        normalized_endpoint = clean_text(
            endpoint
        ).strip("/")

        url = (
            f"{self.BASE_URL}/"
            f"{normalized_endpoint}"
        )

        params: dict[str, Any] = {
            "symbol": provider_symbol,
            "apikey": self.api_key,
        }

        if period:
            params["period"] = period

        if limit is not None:
            params["limit"] = max(
                1,
                int(limit),
            )

        started_at = utc_now()

        try:
            response = self._session.get(
                url,
                params=params,
                timeout=(
                    self.REQUEST_TIMEOUT_SECONDS
                ),
            )

            duration_ms = (
                utc_now() - started_at
            ).total_seconds() * 1000

            response.raise_for_status()

            payload = response.json()

            log_api_call(
                logger,
                service=(
                    "fundamental_service"
                ),
                endpoint=normalized_endpoint,
                status="success",
                duration_ms=duration_ms,
                symbol=normalize_symbol(
                    symbol
                ),
            )

            if isinstance(payload, list):
                return [
                    item
                    for item in payload
                    if isinstance(item, dict)
                ]

            if isinstance(payload, dict):
                error_message = clean_text(
                    payload.get(
                        "Error Message"
                    )
                    or payload.get("error")
                    or payload.get("message")
                )

                if error_message:
                    raise (
                        FundamentalDataUnavailableError(
                            error_message
                        )
                    )

                return [payload]

            return []

        except (
            requests.RequestException,
            ValueError,
        ) as exception:
            log_exception(
                logger,
                (
                    "Fundamental API "
                    "request failed"
                ),
                exception=exception,
                symbol=normalize_symbol(
                    symbol
                ),
                component=(
                    "fundamental_service"
                ),
                error_code=(
                    "FUNDAMENTAL_API_FAILED"
                ),
                endpoint=normalized_endpoint,
            )

            raise (
                FundamentalDataUnavailableError(
                    (
                        "Fundamental data "
                        f"request failed for "
                        f"{normalize_symbol(symbol)}."
                    )
                )
            ) from exception

    @staticmethod
    def _first_record(
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not records:
            return {}

        return records[0]

    @staticmethod
    def _metric(
        records: list[dict[str, Any]],
        *field_names: str,
    ) -> float | None:
        for record in records:
            if not isinstance(record, dict):
                continue

            for field_name in field_names:
                value = safe_float(
                    record.get(field_name)
                )

                if value is not None:
                    return value

        return None

    @staticmethod
    def _percentage_value(
        value: Any,
    ) -> float | None:
        number = safe_float(value)

        if number is None:
            return None

        if -2.0 <= number <= 2.0:
            number *= 100

        return round(number, 2)

    @staticmethod
    def _growth_between(
        newest_value: Any,
        oldest_value: Any,
        years: int,
    ) -> float | None:
        newest = safe_float(newest_value)
        oldest = safe_float(oldest_value)

        if (
            newest is None
            or oldest is None
            or oldest <= 0
            or newest <= 0
            or years <= 0
        ):
            return None

        try:
            growth = (
                (
                    newest / oldest
                )
                ** (1 / years)
                - 1
            ) * 100

            return round(growth, 2)

        except (
            ValueError,
            ZeroDivisionError,
            OverflowError,
        ):
            return None

    # ==========================================================
    # RAW PROVIDER DATA
    # ==========================================================

    def _load_raw_data(
        self,
        symbol: str,
    ) -> dict[str, Any]:
        with self._request_lock:
            profile = self._request(
                "profile",
                symbol=symbol,
            )

            income_annual = self._request(
                "income-statement",
                symbol=symbol,
                period="annual",
                limit=5,
            )

            income_quarterly = self._request(
                "income-statement",
                symbol=symbol,
                period="quarter",
                limit=8,
            )

            cash_flow = self._request(
                "cash-flow-statement",
                symbol=symbol,
                period="annual",
                limit=5,
            )

            key_metrics = self._request(
                "key-metrics",
                symbol=symbol,
                period="annual",
                limit=5,
            )

            ratios = self._request(
                "ratios",
                symbol=symbol,
                period="annual",
                limit=5,
            )

            growth = self._request(
                "financial-growth",
                symbol=symbol,
                period="annual",
                limit=5,
            )

        return {
            "profile": profile,
            "income_annual": income_annual,
            "income_quarterly": (
                income_quarterly
            ),
            "cash_flow": cash_flow,
            "key_metrics": key_metrics,
            "ratios": ratios,
            "growth": growth,
        }

    # ==========================================================
    # METRIC CALCULATIONS
    # ==========================================================

    def _calculate_sales_growth(
        self,
        raw: dict[str, Any],
        timeframe: str,
    ) -> float | None:
        growth_records = raw["growth"]

        direct_growth = self._metric(
            growth_records,
            "revenueGrowth",
            "growthRevenue",
        )

        if direct_growth is not None:
            return self._percentage_value(
                direct_growth
            )

        income = raw["income_annual"]

        if len(income) < 2:
            return None

        years = {
            "15_30_days": 1,
            "3_month": 1,
            "6_month": 2,
            "1_year": 3,
            "3_year": 4,
        }.get(timeframe, 3)

        oldest_index = min(
            years,
            len(income) - 1,
        )

        return self._growth_between(
            income[0].get("revenue"),
            income[oldest_index].get(
                "revenue"
            ),
            oldest_index,
        )

    def _calculate_profit_growth(
        self,
        raw: dict[str, Any],
        timeframe: str,
    ) -> float | None:
        direct_growth = self._metric(
            raw["growth"],
            "netIncomeGrowth",
            "growthNetIncome",
        )

        if direct_growth is not None:
            return self._percentage_value(
                direct_growth
            )

        income = raw["income_annual"]

        if len(income) < 2:
            return None

        years = {
            "15_30_days": 1,
            "3_month": 1,
            "6_month": 2,
            "1_year": 3,
            "3_year": 4,
        }.get(timeframe, 3)

        oldest_index = min(
            years,
            len(income) - 1,
        )

        return self._growth_between(
            income[0].get("netIncome"),
            income[oldest_index].get(
                "netIncome"
            ),
            oldest_index,
        )

    def _calculate_eps_growth(
        self,
        raw: dict[str, Any],
        timeframe: str,
    ) -> float | None:
        direct_growth = self._metric(
            raw["growth"],
            "epsGrowth",
            "growthEPS",
            "epsgrowth",
        )

        if direct_growth is not None:
            return self._percentage_value(
                direct_growth
            )

        income = raw["income_annual"]

        if len(income) < 2:
            return None

        years = {
            "15_30_days": 1,
            "3_month": 1,
            "6_month": 2,
            "1_year": 3,
            "3_year": 4,
        }.get(timeframe, 3)

        oldest_index = min(
            years,
            len(income) - 1,
        )

        return self._growth_between(
            income[0].get("eps")
            or income[0].get("epsdiluted"),
            income[oldest_index].get(
                "eps"
            )
            or income[oldest_index].get(
                "epsdiluted"
            ),
            oldest_index,
        )

    def _calculate_valuation_score(
        self,
        pe_ratio: float | None,
        peg_ratio: float | None,
    ) -> float | None:
        if (
            pe_ratio is None
            and peg_ratio is None
        ):
            return None

        score = 50.0

        if pe_ratio is not None:
            if 0 < pe_ratio <= 15:
                score += 25
            elif pe_ratio <= 25:
                score += 18
            elif pe_ratio <= 40:
                score += 8
            elif pe_ratio > 60:
                score -= 15

        if peg_ratio is not None:
            if 0 < peg_ratio <= 1:
                score += 25
            elif peg_ratio <= 1.5:
                score += 15
            elif peg_ratio <= 2:
                score += 5
            elif peg_ratio > 3:
                score -= 15

        return round(
            max(0.0, min(100.0, score)),
            2,
        )

    def _normalize_fundamentals(
        self,
        symbol: str,
        timeframe: str,
        raw: dict[str, Any],
    ) -> dict[str, Any]:
        profile = self._first_record(
            raw["profile"]
        )

        roe = self._percentage_value(
            self._metric(
                raw["ratios"],
                "returnOnEquity",
                "returnOnEquityRatio",
            )
            or self._metric(
                raw["key_metrics"],
                "roe",
            )
        )

        roce = self._percentage_value(
            self._metric(
                raw["ratios"],
                "returnOnCapitalEmployed",
            )
            or self._metric(
                raw["key_metrics"],
                "roic",
                "returnOnInvestedCapital",
            )
        )

        debt_to_equity = self._metric(
            raw["ratios"],
            "debtEquityRatio",
            "debtToEquity",
        )

        if debt_to_equity is None:
            debt_to_equity = self._metric(
                raw["key_metrics"],
                "debtToEquity",
            )

        operating_cash_flow = self._metric(
            raw["cash_flow"],
            "operatingCashFlow",
            "netCashProvidedByOperatingActivities",
        )

        pe_ratio = self._metric(
            raw["ratios"],
            "priceEarningsRatio",
            "priceToEarningsRatio",
        )

        if pe_ratio is None:
            pe_ratio = self._metric(
                raw["key_metrics"],
                "peRatio",
            )

        peg_ratio = self._metric(
            raw["ratios"],
            "priceEarningsToGrowthRatio",
            "pegRatio",
        )

        if peg_ratio is None:
            peg_ratio = self._metric(
                raw["key_metrics"],
                "pegRatio",
            )

        result = {
            "symbol": normalize_symbol(
                symbol
            ),
            "provider_symbol": (
                self.to_provider_symbol(
                    symbol
                )
            ),
            "company_name": clean_text(
                profile.get("companyName")
                or profile.get("name")
            ),
            "sector": clean_text(
                profile.get("sector"),
                default="Unknown",
            ),
            "industry": clean_text(
                profile.get("industry"),
                default="Unknown",
            ),
            "market_cap": safe_float(
                profile.get("marketCap")
                or profile.get("mktCap")
            ),
            "sales_growth": (
                self._calculate_sales_growth(
                    raw,
                    timeframe,
                )
            ),
            "profit_growth": (
                self._calculate_profit_growth(
                    raw,
                    timeframe,
                )
            ),
            "eps_growth": (
                self._calculate_eps_growth(
                    raw,
                    timeframe,
                )
            ),
            "roe": roe,
            "roce": roce,
            "debt_to_equity": (
                round(debt_to_equity, 3)
                if debt_to_equity
                is not None
                else None
            ),
            "operating_cash_flow": (
                operating_cash_flow
            ),

            # FMP सामान्यतः Indian promoter holding
            # और promoter pledge नहीं देता।
            # इसलिए fake value बनाने के बजाय None रखा जाएगा।
            "promoter_holding": None,
            "promoter_pledge": None,

            "pe_ratio": (
                round(pe_ratio, 2)
                if pe_ratio is not None
                else None
            ),
            "peg_ratio": (
                round(peg_ratio, 2)
                if peg_ratio is not None
                else None
            ),
            "valuation_score": (
                self._calculate_valuation_score(
                    pe_ratio,
                    peg_ratio,
                )
            ),
            "timeframe": timeframe,
            "source": (
                "Financial Modeling Prep"
            ),
            "updated_at": (
                utc_now().isoformat()
            ),
            "verified": True,
        }

        available_fields = [
            field_name
            for field_name in (
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
            )
            if result.get(field_name)
            is not None
        ]

        result["available_filter_count"] = (
            len(available_fields)
        )

        result["available_filters"] = (
            available_fields
        )

        result["missing_filters"] = [
            field_name
            for field_name in (
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
            )
            if result.get(field_name)
            is None
        ]

        return result

    # ==========================================================
    # PUBLIC METHODS
    # ==========================================================

    def get_fundamentals(
        self,
        symbol: str,
        *,
        timeframe: str = "3_month",
        force_refresh: bool = False,
        require_complete: bool = False,
    ) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(
            symbol
        )

        normalized_timeframe = (
            normalize_timeframe(timeframe)
        )

        if not normalized_symbol:
            raise ValueError(
                "A valid stock symbol is required."
            )

        cache_key = build_cache_key(
            "fundamentals",
            normalized_symbol,
            normalized_timeframe,
            prefix="fundamental",
        )

        if not force_refresh:
            cached_data = (
                self.cache_service.get(
                    cache_key
                )
            )

            if isinstance(cached_data, dict):
                return cached_data

        error_cache_key = build_cache_key(
            "fundamental-error",
            normalized_symbol,
            prefix="fundamental",
        )

        if not force_refresh:
            cached_error = (
                self.cache_service.get(
                    error_cache_key
                )
            )

            if cached_error:
                raise (
                    FundamentalDataUnavailableError(
                        str(cached_error)
                    )
                )

        try:
            raw_data = self._load_raw_data(
                normalized_symbol
            )

            fundamentals = (
                self._normalize_fundamentals(
                    normalized_symbol,
                    normalized_timeframe,
                    raw_data,
                )
            )

            validation = (
                validate_fundamental_data(
                    fundamentals,
                    timeframe=(
                        normalized_timeframe
                    ),
                )
            )

            fundamentals[
                "validation_errors"
            ] = validation.errors

            fundamentals[
                "validation_warnings"
            ] = validation.warnings

            fundamentals[
                "validation_passed"
            ] = validation.is_valid

            if (
                require_complete
                and not validation.is_valid
            ):
                raise (
                    FundamentalDataUnavailableError(
                        "; ".join(
                            validation.errors
                        )
                    )
                )

            if (
                fundamentals[
                    "available_filter_count"
                ]
                < 5
            ):
                raise (
                    FundamentalDataUnavailableError(
                        (
                            "Insufficient verified "
                            "fundamental fields."
                        )
                    )
                )

            self.cache_service.set(
                cache_key,
                fundamentals,
                ttl_seconds=(
                    self.CACHE_SECONDS
                ),
            )

            return fundamentals

        except (
            FundamentalConfigurationError,
            FundamentalDataUnavailableError,
        ) as exception:
            self.cache_service.set(
                error_cache_key,
                str(exception),
                ttl_seconds=(
                    self.ERROR_CACHE_SECONDS
                ),
            )

            raise

        except Exception as exception:
            log_exception(
                logger,
                (
                    "Unable to build verified "
                    "fundamental data"
                ),
                exception=exception,
                symbol=normalized_symbol,
                timeframe=(
                    normalized_timeframe
                ),
                component=(
                    "fundamental_service"
                ),
                error_code=(
                    "FUNDAMENTAL_BUILD_FAILED"
                ),
            )

            raise (
                FundamentalDataUnavailableError(
                    (
                        "Verified fundamental data "
                        f"is unavailable for "
                        f"{normalized_symbol}."
                    )
                )
            ) from exception

    def get_bulk_fundamentals(
        self,
        symbols: list[str],
        *,
        timeframe: str = "3_month",
        force_refresh: bool = False,
    ) -> dict[str, dict[str, Any]]:
        results: dict[
            str,
            dict[str, Any],
        ] = {}

        for symbol in symbols:
            normalized_symbol = (
                normalize_symbol(symbol)
            )

            if not normalized_symbol:
                continue

            try:
                results[normalized_symbol] = (
                    self.get_fundamentals(
                        normalized_symbol,
                        timeframe=timeframe,
                        force_refresh=(
                            force_refresh
                        ),
                    )
                )

            except FundamentalDataError as exception:
                logger.warning(
                    (
                        "Fundamental data skipped "
                        "for %s: %s"
                    ),
                    normalized_symbol,
                    str(exception),
                    extra=build_log_extra(
                        component=(
                            "fundamental_service"
                        ),
                        symbol=(
                            normalized_symbol
                        ),
                        timeframe=(
                            normalize_timeframe(
                                timeframe
                            )
                        ),
                        event=(
                            "fundamental_skipped"
                        ),
                        status="rejected",
                    ),
                )

        return results

    def clear_symbol_cache(
        self,
        symbol: str,
    ) -> int:
        normalized_symbol = normalize_symbol(
            symbol
        )

        if not normalized_symbol:
            return 0

        deleted_count = 0

        for key in (
            self.cache_service.list_keys()
        ):
            if (
                normalized_symbol.casefold()
                in key.casefold()
            ):
                if self.cache_service.delete(
                    key
                ):
                    deleted_count += 1

        return deleted_count

    def health(
        self,
    ) -> dict[str, Any]:
        configuration = (
            self.configuration_status()
        )

        return {
            "service": (
                "Fundamental Service"
            ),
            "provider": (
                "Financial Modeling Prep"
            ),
            "status": (
                "configured"
                if configuration[
                    "configured"
                ]
                else "not_configured"
            ),
            "is_healthy": bool(
                configuration["configured"]
            ),
            "missing_fields": (
                configuration[
                    "missing_fields"
                ]
            ),
            "cache_seconds": (
                self.CACHE_SECONDS
            ),
            "checked_at": (
                utc_now().isoformat()
            ),
        }


_global_fundamental_service: (
    FundamentalService | None
) = None

_global_fundamental_lock = (
    threading.Lock()
)


def get_fundamental_service(
) -> FundamentalService:
    global _global_fundamental_service

    if (
        _global_fundamental_service
        is not None
    ):
        return _global_fundamental_service

    with _global_fundamental_lock:
        if (
            _global_fundamental_service
            is None
        ):
            _global_fundamental_service = (
                FundamentalService()
            )

    return _global_fundamental_service
