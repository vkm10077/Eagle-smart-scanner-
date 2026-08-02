from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.helpers import (
    normalize_score,
    normalize_symbol,
    normalize_timeframe,
    safe_float,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_exception,
)


logger = get_logger("scanners.fundamental_scanner")


class FundamentalScannerError(RuntimeError):
    """Raised when fundamental analysis cannot be completed."""


@dataclass
class FundamentalFilterResult:
    name: str
    label: str
    passed: bool
    score: float
    weight: float
    value: Any = None
    reason: str = ""
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "passed": self.passed,
            "score": round(self.score, 2),
            "weight": round(self.weight, 2),
            "value": self.value,
            "reason": self.reason,
            "available": self.available,
        }


@dataclass
class FundamentalScanResult:
    symbol: str
    timeframe: str
    score: float
    passed_count: int
    available_filter_count: int
    total_filters: int
    strong_fundamentals: bool
    filters: list[FundamentalFilterResult] = field(
        default_factory=list
    )
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "score": round(self.score, 2),
            "passed_count": self.passed_count,
            "available_filter_count": (
                self.available_filter_count
            ),
            "total_filters": self.total_filters,
            "strong_fundamentals": (
                self.strong_fundamentals
            ),
            "filters": [
                item.to_dict()
                for item in self.filters
            ],
            "generated_at": self.generated_at,
        }


class FundamentalScanner:
    """
    Top-10 fundamental filter scanner.

    Filters:
    1. Sales growth
    2. Profit growth
    3. EPS growth
    4. ROE
    5. ROCE
    6. Debt-to-equity
    7. Operating cash flow
    8. Promoter holding
    9. Promoter pledge
    10. Valuation score

    Missing values are never converted into fake zero values.
    """

    FILTER_LABELS = {
        "SALES_GROWTH": "Sales Growth",
        "PROFIT_GROWTH": "Profit Growth",
        "EPS_GROWTH": "EPS Growth",
        "ROE": "Return on Equity",
        "ROCE": "Return on Capital Employed",
        "DEBT_TO_EQUITY": "Debt-to-Equity",
        "OPERATING_CASHFLOW": "Operating Cash Flow",
        "PROMOTER_HOLDING": "Promoter Holding",
        "PROMOTER_PLEDGE": "Promoter Pledge",
        "VALUATION": "Valuation",
    }

    FIELD_MAP = {
        "SALES_GROWTH": "sales_growth",
        "PROFIT_GROWTH": "profit_growth",
        "EPS_GROWTH": "eps_growth",
        "ROE": "roe",
        "ROCE": "roce",
        "DEBT_TO_EQUITY": "debt_to_equity",
        "OPERATING_CASHFLOW": "operating_cash_flow",
        "PROMOTER_HOLDING": "promoter_holding",
        "PROMOTER_PLEDGE": "promoter_pledge",
        "VALUATION": "valuation_score",
    }

    TIMEFRAME_WEIGHTS = {
        "15_30_days": {
            "SALES_GROWTH": 8,
            "PROFIT_GROWTH": 10,
            "EPS_GROWTH": 10,
            "ROE": 8,
            "ROCE": 8,
            "DEBT_TO_EQUITY": 10,
            "OPERATING_CASHFLOW": 10,
            "PROMOTER_HOLDING": 10,
            "PROMOTER_PLEDGE": 10,
            "VALUATION": 16,
        },
        "3_month": {
            "SALES_GROWTH": 11,
            "PROFIT_GROWTH": 13,
            "EPS_GROWTH": 13,
            "ROE": 10,
            "ROCE": 10,
            "DEBT_TO_EQUITY": 9,
            "OPERATING_CASHFLOW": 9,
            "PROMOTER_HOLDING": 8,
            "PROMOTER_PLEDGE": 8,
            "VALUATION": 9,
        },
        "6_month": {
            "SALES_GROWTH": 12,
            "PROFIT_GROWTH": 14,
            "EPS_GROWTH": 13,
            "ROE": 11,
            "ROCE": 12,
            "DEBT_TO_EQUITY": 10,
            "OPERATING_CASHFLOW": 10,
            "PROMOTER_HOLDING": 7,
            "PROMOTER_PLEDGE": 6,
            "VALUATION": 5,
        },
        "1_year": {
            "SALES_GROWTH": 13,
            "PROFIT_GROWTH": 14,
            "EPS_GROWTH": 14,
            "ROE": 12,
            "ROCE": 13,
            "DEBT_TO_EQUITY": 11,
            "OPERATING_CASHFLOW": 11,
            "PROMOTER_HOLDING": 5,
            "PROMOTER_PLEDGE": 4,
            "VALUATION": 3,
        },
        "3_year": {
            "SALES_GROWTH": 14,
            "PROFIT_GROWTH": 15,
            "EPS_GROWTH": 15,
            "ROE": 13,
            "ROCE": 14,
            "DEBT_TO_EQUITY": 11,
            "OPERATING_CASHFLOW": 11,
            "PROMOTER_HOLDING": 3,
            "PROMOTER_PLEDGE": 2,
            "VALUATION": 2,
        },
    }

    MINIMUM_SCORE = {
        "15_30_days": 58.0,
        "3_month": 62.0,
        "6_month": 65.0,
        "1_year": 68.0,
        "3_year": 70.0,
    }

    MINIMUM_AVAILABLE_FILTERS = {
        "15_30_days": 5,
        "3_month": 6,
        "6_month": 6,
        "1_year": 7,
        "3_year": 7,
    }

    MINIMUM_PASSED_FILTERS = {
        "15_30_days": 4,
        "3_month": 5,
        "6_month": 5,
        "1_year": 5,
        "3_year": 6,
    }

    def _build_result(
        self,
        *,
        name: str,
        weight: float,
        value: Any,
        passed: bool,
        score: float,
        reason: str,
        available: bool = True,
    ) -> FundamentalFilterResult:
        return FundamentalFilterResult(
            name=name,
            label=self.FILTER_LABELS[name],
            passed=passed,
            score=normalize_score(score),
            weight=weight,
            value=value,
            reason=reason,
            available=available,
        )

    def _missing_result(
        self,
        name: str,
        weight: float,
    ) -> FundamentalFilterResult:
        return self._build_result(
            name=name,
            weight=weight,
            value=None,
            passed=False,
            score=0.0,
            reason=(
                "Verified data is unavailable. "
                "No estimated value was used."
            ),
            available=False,
        )

    @staticmethod
    def _growth_filter(
        value: float,
    ) -> tuple[bool, float, str]:
        if value >= 25:
            return (
                True,
                100.0,
                "Growth is above 25%.",
            )

        if value >= 15:
            return (
                True,
                85.0,
                "Growth is above 15%.",
            )

        if value >= 10:
            return (
                True,
                70.0,
                "Growth is above 10%.",
            )

        if value >= 5:
            return (
                False,
                45.0,
                "Growth is positive but below preferred level.",
            )

        if value >= 0:
            return (
                False,
                25.0,
                "Growth is weak.",
            )

        return (
            False,
            5.0,
            "Growth is negative.",
        )

    @staticmethod
    def _roe_filter(
        value: float,
    ) -> tuple[bool, float, str]:
        if value >= 25:
            return True, 100.0, "ROE is excellent."

        if value >= 20:
            return True, 90.0, "ROE is strong."

        if value >= 15:
            return True, 75.0, "ROE is acceptable."

        if value >= 10:
            return False, 45.0, "ROE is moderate."

        return False, 15.0, "ROE is weak."

    @staticmethod
    def _roce_filter(
        value: float,
    ) -> tuple[bool, float, str]:
        if value >= 25:
            return True, 100.0, "ROCE is excellent."

        if value >= 18:
            return True, 88.0, "ROCE is strong."

        if value >= 15:
            return True, 72.0, "ROCE is acceptable."

        if value >= 10:
            return False, 42.0, "ROCE is moderate."

        return False, 15.0, "ROCE is weak."

    @staticmethod
    def _debt_filter(
        value: float,
    ) -> tuple[bool, float, str]:
        if value < 0:
            return (
                False,
                0.0,
                "Debt-to-equity value is invalid.",
            )

        if value <= 0.2:
            return (
                True,
                100.0,
                "Company has very low debt.",
            )

        if value <= 0.5:
            return (
                True,
                88.0,
                "Debt level is comfortable.",
            )

        if value <= 1.0:
            return (
                True,
                68.0,
                "Debt level is manageable.",
            )

        if value <= 1.5:
            return (
                False,
                40.0,
                "Debt level is elevated.",
            )

        return (
            False,
            10.0,
            "Debt level is high.",
        )

    @staticmethod
    def _cashflow_filter(
        value: float,
    ) -> tuple[bool, float, str]:
        if value > 0:
            return (
                True,
                100.0,
                "Operating cash flow is positive.",
            )

        if value == 0:
            return (
                False,
                25.0,
                "Operating cash flow is zero.",
            )

        return (
            False,
            5.0,
            "Operating cash flow is negative.",
        )

    @staticmethod
    def _promoter_holding_filter(
        value: float,
    ) -> tuple[bool, float, str]:
        if not 0 <= value <= 100:
            return (
                False,
                0.0,
                "Promoter holding value is invalid.",
            )

        if value >= 60:
            return (
                True,
                100.0,
                "Promoter holding is above 60%.",
            )

        if value >= 50:
            return (
                True,
                85.0,
                "Promoter holding is above 50%.",
            )

        if value >= 40:
            return (
                True,
                68.0,
                "Promoter holding is acceptable.",
            )

        if value >= 25:
            return (
                False,
                40.0,
                "Promoter holding is relatively low.",
            )

        return (
            False,
            15.0,
            "Promoter holding is weak.",
        )

    @staticmethod
    def _promoter_pledge_filter(
        value: float,
    ) -> tuple[bool, float, str]:
        if not 0 <= value <= 100:
            return (
                False,
                0.0,
                "Promoter pledge value is invalid.",
            )

        if value == 0:
            return (
                True,
                100.0,
                "There is no promoter pledge.",
            )

        if value <= 5:
            return (
                True,
                82.0,
                "Promoter pledge is very low.",
            )

        if value <= 15:
            return (
                False,
                45.0,
                "Promoter pledge requires caution.",
            )

        return (
            False,
            5.0,
            "Promoter pledge is high.",
        )

    @staticmethod
    def _valuation_filter(
        value: float,
    ) -> tuple[bool, float, str]:
        score = normalize_score(value)

        if score >= 80:
            return (
                True,
                score,
                "Valuation is attractive.",
            )

        if score >= 65:
            return (
                True,
                score,
                "Valuation is reasonable.",
            )

        if score >= 50:
            return (
                False,
                score,
                "Valuation is neutral.",
            )

        return (
            False,
            score,
            "Valuation is expensive or weak.",
        )

    def _evaluate_filter(
        self,
        *,
        filter_name: str,
        value: float,
    ) -> tuple[bool, float, str]:
        if filter_name in {
            "SALES_GROWTH",
            "PROFIT_GROWTH",
            "EPS_GROWTH",
        }:
            return self._growth_filter(value)

        if filter_name == "ROE":
            return self._roe_filter(value)

        if filter_name == "ROCE":
            return self._roce_filter(value)

        if filter_name == "DEBT_TO_EQUITY":
            return self._debt_filter(value)

        if filter_name == "OPERATING_CASHFLOW":
            return self._cashflow_filter(value)

        if filter_name == "PROMOTER_HOLDING":
            return self._promoter_holding_filter(
                value
            )

        if filter_name == "PROMOTER_PLEDGE":
            return self._promoter_pledge_filter(
                value
            )

        if filter_name == "VALUATION":
            return self._valuation_filter(value)

        return (
            False,
            0.0,
            "Unknown fundamental filter.",
        )

    def scan(
        self,
        symbol: str,
        fundamentals: dict[str, Any],
        *,
        timeframe: str = "3_month",
    ) -> dict[str, Any]:
        normalized_symbol = normalize_symbol(symbol)

        normalized_timeframe = normalize_timeframe(
            timeframe
        )

        if not normalized_symbol:
            raise ValueError(
                "A valid stock symbol is required."
            )

        if not isinstance(fundamentals, dict):
            raise FundamentalScannerError(
                "Fundamental data is missing."
            )

        try:
            weights = self.TIMEFRAME_WEIGHTS[
                normalized_timeframe
            ]

            filter_results: list[
                FundamentalFilterResult
            ] = []

            for filter_name in self.FILTER_LABELS:
                field_name = self.FIELD_MAP[
                    filter_name
                ]

                raw_value = fundamentals.get(
                    field_name
                )

                value = safe_float(raw_value)

                weight = weights[filter_name]

                if value is None:
                    filter_results.append(
                        self._missing_result(
                            filter_name,
                            weight,
                        )
                    )
                    continue

                passed, score, reason = (
                    self._evaluate_filter(
                        filter_name=filter_name,
                        value=value,
                    )
                )

                display_value: Any = round(
                    value,
                    2,
                )

                if filter_name in {
                    "SALES_GROWTH",
                    "PROFIT_GROWTH",
                    "EPS_GROWTH",
                    "ROE",
                    "ROCE",
                    "PROMOTER_HOLDING",
                    "PROMOTER_PLEDGE",
                }:
                    display_value = {
                        "value": round(value, 2),
                        "unit": "%",
                    }

                filter_results.append(
                    self._build_result(
                        name=filter_name,
                        weight=weight,
                        value=display_value,
                        passed=passed,
                        score=score,
                        reason=reason,
                    )
                )

            available_results = [
                item
                for item in filter_results
                if item.available
            ]

            available_filter_count = len(
                available_results
            )

            passed_count = sum(
                1
                for item in available_results
                if item.passed
            )

            available_weight = sum(
                item.weight
                for item in available_results
            )

            weighted_score = (
                sum(
                    item.score * item.weight
                    for item in available_results
                )
                / available_weight
                if available_weight > 0
                else 0.0
            )

            minimum_available = (
                self.MINIMUM_AVAILABLE_FILTERS[
                    normalized_timeframe
                ]
            )

            minimum_passed = (
                self.MINIMUM_PASSED_FILTERS[
                    normalized_timeframe
                ]
            )

            minimum_score = (
                self.MINIMUM_SCORE[
                    normalized_timeframe
                ]
            )

            critical_quality_passed = all(
                (
                    fundamentals.get(
                        "debt_to_equity"
                    )
                    is None
                    or (
                        safe_float(
                            fundamentals.get(
                                "debt_to_equity"
                            )
                        )
                        or 0
                    )
                    <= 1.5,
                    fundamentals.get(
                        "operating_cash_flow"
                    )
                    is None
                    or (
                        safe_float(
                            fundamentals.get(
                                "operating_cash_flow"
                            )
                        )
                        or 0
                    )
                    > 0,
                    fundamentals.get(
                        "promoter_pledge"
                    )
                    is None
                    or (
                        safe_float(
                            fundamentals.get(
                                "promoter_pledge"
                            )
                        )
                        or 0
                    )
                    <= 15,
                )
            )

            strong_fundamentals = (
                available_filter_count
                >= minimum_available
                and passed_count
                >= minimum_passed
                and weighted_score
                >= minimum_score
                and critical_quality_passed
            )

            result = FundamentalScanResult(
                symbol=normalized_symbol,
                timeframe=normalized_timeframe,
                score=normalize_score(
                    weighted_score
                ),
                passed_count=passed_count,
                available_filter_count=(
                    available_filter_count
                ),
                total_filters=len(
                    filter_results
                ),
                strong_fundamentals=(
                    strong_fundamentals
                ),
                filters=filter_results,
                generated_at=utc_now().isoformat(),
            )

            logger.info(
                (
                    "Fundamental scan completed "
                    "for %s with score %.2f."
                ),
                normalized_symbol,
                weighted_score,
                extra=build_log_extra(
                    component=(
                        "fundamental_scanner"
                    ),
                    symbol=normalized_symbol,
                    timeframe=normalized_timeframe,
                    event=(
                        "fundamental_scan_completed"
                    ),
                    status=(
                        "success"
                        if strong_fundamentals
                        else "rejected"
                    ),
                    passed_count=passed_count,
                    available_filter_count=(
                        available_filter_count
                    ),
                ),
            )

            return result.to_dict()

        except FundamentalScannerError:
            raise

        except Exception as exception:
            log_exception(
                logger,
                "Fundamental scan failed",
                exception=exception,
                symbol=normalized_symbol,
                timeframe=normalized_timeframe,
                component=(
                    "fundamental_scanner"
                ),
                error_code=(
                    "FUNDAMENTAL_SCAN_FAILED"
                ),
            )

            raise FundamentalScannerError(
                (
                    "Fundamental analysis failed "
                    f"for {normalized_symbol}."
                )
            ) from exception


_global_fundamental_scanner: (
    FundamentalScanner | None
) = None


def get_fundamental_scanner(
) -> FundamentalScanner:
    global _global_fundamental_scanner

    if _global_fundamental_scanner is None:
        _global_fundamental_scanner = (
            FundamentalScanner()
        )

    return _global_fundamental_scanner
