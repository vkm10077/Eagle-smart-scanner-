from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from utils.helpers import (
    normalize_score,
    normalize_signal,
    normalize_timeframe,
    safe_float,
    utc_now,
)
from utils.logger import (
    build_log_extra,
    get_logger,
    log_exception,
)


logger = get_logger("scanners.probability_engine")


class ProbabilityEngineError(RuntimeError):
    """Raised when probability calculation cannot be completed."""


@dataclass
class ProbabilityComponent:
    name: str
    score: float
    weight: float
    available: bool
    passed: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 2),
            "weight": round(self.weight, 2),
            "available": self.available,
            "passed": self.passed,
            "reason": self.reason,
        }


@dataclass
class ProbabilityResult:
    timeframe: str
    probability: float
    confidence_score: float
    overall_score: float
    signal: str
    available_weight: float
    total_weight: float
    data_completeness: float
    components: list[ProbabilityComponent] = field(
        default_factory=list
    )
    rejection_reasons: list[str] = field(
        default_factory=list
    )
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "move_up_probability": round(
                self.probability,
                2,
            ),
            "confidence_score": round(
                self.confidence_score,
                2,
            ),
            "overall_score": round(
                self.overall_score,
                2,
            ),
            "signal": self.signal,
            "available_weight": round(
                self.available_weight,
                2,
            ),
            "total_weight": round(
                self.total_weight,
                2,
            ),
            "data_completeness": round(
                self.data_completeness,
                2,
            ),
            "components": [
                item.to_dict()
                for item in self.components
            ],
            "rejection_reasons": list(
                self.rejection_reasons
            ),
            "generated_at": self.generated_at,
        }


class ProbabilityEngine:
    """
    Combines technical, fundamental, pattern and sector scores.

    The displayed probability is a weighted research score converted
    into a bounded probability estimate. It is not a guarantee.

    No missing component receives an invented score. Missing components
    reduce data completeness and can prevent BUY/STRONG BUY signals.
    """

    TIMEFRAME_WEIGHTS = {
        "15_30_days": {
            "technical": 45.0,
            "fundamental": 15.0,
            "pattern": 25.0,
            "sector": 15.0,
        },
        "3_month": {
            "technical": 35.0,
            "fundamental": 25.0,
            "pattern": 20.0,
            "sector": 20.0,
        },
        "6_month": {
            "technical": 25.0,
            "fundamental": 35.0,
            "pattern": 15.0,
            "sector": 25.0,
        },
        "1_year": {
            "technical": 20.0,
            "fundamental": 45.0,
            "pattern": 10.0,
            "sector": 25.0,
        },
        "3_year": {
            "technical": 15.0,
            "fundamental": 55.0,
            "pattern": 5.0,
            "sector": 25.0,
        },
    }

    BUY_THRESHOLDS = {
        "15_30_days": 74.0,
        "3_month": 75.0,
        "6_month": 76.0,
        "1_year": 77.0,
        "3_year": 78.0,
    }

    STRONG_BUY_THRESHOLDS = {
        "15_30_days": 84.0,
        "3_month": 85.0,
        "6_month": 86.0,
        "1_year": 87.0,
        "3_year": 88.0,
    }

    MINIMUM_COMPLETENESS = {
        "15_30_days": 75.0,
        "3_month": 80.0,
        "6_month": 80.0,
        "1_year": 85.0,
        "3_year": 85.0,
    }

    MINIMUM_COMPONENT_SCORE = {
        "technical": 60.0,
        "fundamental": 55.0,
        "pattern": 0.0,
        "sector": 55.0,
    }

    def _component_from_result(
        self,
        *,
        name: str,
        result: dict[str, Any] | None,
        weight: float,
    ) -> ProbabilityComponent:
        if not isinstance(result, dict):
            return ProbabilityComponent(
                name=name,
                score=0.0,
                weight=weight,
                available=False,
                passed=False,
                reason=(
                    f"Verified {name} result is unavailable."
                ),
            )

        score = safe_float(
            result.get("score"),
            default=None,
        )

        if score is None:
            return ProbabilityComponent(
                name=name,
                score=0.0,
                weight=weight,
                available=False,
                passed=False,
                reason=(
                    f"{name.title()} score is unavailable."
                ),
            )

        normalized_score = normalize_score(score)

        passed_field = {
            "technical": "bullish",
            "fundamental": "strong_fundamentals",
            "pattern": "bullish_pattern",
            "sector": "sector_bullish",
        }.get(name)

        passed = bool(
            result.get(passed_field)
        ) if passed_field else False

        minimum_score = self.MINIMUM_COMPONENT_SCORE.get(
            name,
            0.0,
        )

        if name == "pattern":
            passed = bool(
                result.get("confirmed_count", 0) > 0
            )

        reason = ""

        if passed:
            reason = (
                f"{name.title()} confirmation passed."
            )
        elif normalized_score < minimum_score:
            reason = (
                f"{name.title()} score is below "
                f"{minimum_score:.0f}."
            )
        else:
            reason = (
                f"{name.title()} confirmation is absent."
            )

        return ProbabilityComponent(
            name=name,
            score=normalized_score,
            weight=weight,
            available=True,
            passed=passed,
            reason=reason,
        )

    @staticmethod
    def _calculate_weighted_score(
        components: list[ProbabilityComponent],
    ) -> tuple[float, float, float]:
        available_components = [
            component
            for component in components
            if component.available
        ]

        available_weight = sum(
            component.weight
            for component in available_components
        )

        total_weight = sum(
            component.weight
            for component in components
        )

        if available_weight <= 0:
            return 0.0, 0.0, total_weight

        weighted_score = sum(
            component.score
            * component.weight
            for component in available_components
        ) / available_weight

        return (
            normalize_score(weighted_score),
            available_weight,
            total_weight,
        )

    @staticmethod
    def _calculate_completeness(
        available_weight: float,
        total_weight: float,
    ) -> float:
        if total_weight <= 0:
            return 0.0

        return normalize_score(
            available_weight
            / total_weight
            * 100
        )

    @staticmethod
    def _apply_confirmation_adjustments(
        score: float,
        components: list[ProbabilityComponent],
    ) -> float:
        adjusted_score = score

        passed_components = {
            component.name: component.passed
            for component in components
        }

        if (
            passed_components.get("technical")
            and passed_components.get("fundamental")
            and passed_components.get("sector")
        ):
            adjusted_score += 3.0

        if (
            passed_components.get("pattern")
            and passed_components.get("technical")
        ):
            adjusted_score += 2.0

        failed_critical = sum(
            1
            for component in components
            if (
                component.name
                in {
                    "technical",
                    "fundamental",
                    "sector",
                }
                and component.available
                and not component.passed
            )
        )

        adjusted_score -= failed_critical * 4.0

        return normalize_score(adjusted_score)

    @staticmethod
    def _probability_from_score(
        score: float,
        completeness: float,
    ) -> float:
        completeness_factor = (
            0.85
            + (
                completeness / 100
            ) * 0.15
        )

        probability = score * completeness_factor

        return normalize_score(
            probability,
            minimum=0.0,
            maximum=95.0,
        )

    def calculate(
        self,
        *,
        timeframe: str,
        technical_result: dict[str, Any] | None,
        fundamental_result: dict[str, Any] | None,
        pattern_result: dict[str, Any] | None,
        sector_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        normalized_timeframe = normalize_timeframe(
            timeframe
        )

        try:
            weights = self.TIMEFRAME_WEIGHTS[
                normalized_timeframe
            ]

            components = [
                self._component_from_result(
                    name="technical",
                    result=technical_result,
                    weight=weights["technical"],
                ),
                self._component_from_result(
                    name="fundamental",
                    result=fundamental_result,
                    weight=weights["fundamental"],
                ),
                self._component_from_result(
                    name="pattern",
                    result=pattern_result,
                    weight=weights["pattern"],
                ),
                self._component_from_result(
                    name="sector",
                    result=sector_result,
                    weight=weights["sector"],
                ),
            ]

            (
                weighted_score,
                available_weight,
                total_weight,
            ) = self._calculate_weighted_score(
                components
            )

            completeness = (
                self._calculate_completeness(
                    available_weight,
                    total_weight,
                )
            )

            adjusted_score = (
                self._apply_confirmation_adjustments(
                    weighted_score,
                    components,
                )
            )

            probability = (
                self._probability_from_score(
                    adjusted_score,
                    completeness,
                )
            )

            rejection_reasons: list[str] = []

            minimum_completeness = (
                self.MINIMUM_COMPLETENESS[
                    normalized_timeframe
                ]
            )

            if completeness < minimum_completeness:
                rejection_reasons.append(
                    (
                        "Verified data completeness is "
                        f"below {minimum_completeness:.0f}%."
                    )
                )

            component_map = {
                component.name: component
                for component in components
            }

            technical_component = component_map[
                "technical"
            ]

            fundamental_component = component_map[
                "fundamental"
            ]

            sector_component = component_map[
                "sector"
            ]

            if not technical_component.available:
                rejection_reasons.append(
                    "Technical result is unavailable."
                )
            elif not technical_component.passed:
                rejection_reasons.append(
                    "Technical confirmation failed."
                )

            if not fundamental_component.available:
                rejection_reasons.append(
                    "Fundamental result is unavailable."
                )
            elif (
                normalized_timeframe
                in {
                    "6_month",
                    "1_year",
                    "3_year",
                }
                and not fundamental_component.passed
            ):
                rejection_reasons.append(
                    "Fundamental confirmation failed."
                )

            if not sector_component.available:
                rejection_reasons.append(
                    "Sector result is unavailable."
                )
            elif not sector_component.passed:
                rejection_reasons.append(
                    "Sector confirmation failed."
                )

            buy_threshold = (
                self.BUY_THRESHOLDS[
                    normalized_timeframe
                ]
            )

            strong_buy_threshold = (
                self.STRONG_BUY_THRESHOLDS[
                    normalized_timeframe
                ]
            )

            signal = "NO TRADE"

            critical_pass = (
                technical_component.available
                and technical_component.passed
                and sector_component.available
                and sector_component.passed
            )

            if normalized_timeframe in {
                "6_month",
                "1_year",
                "3_year",
            }:
                critical_pass = (
                    critical_pass
                    and fundamental_component.available
                    and fundamental_component.passed
                )

            if (
                not rejection_reasons
                and critical_pass
                and probability
                >= strong_buy_threshold
            ):
                signal = "STRONG BUY"

            elif (
                not rejection_reasons
                and critical_pass
                and probability
                >= buy_threshold
            ):
                signal = "BUY"

            if (
                signal == "NO TRADE"
                and probability < buy_threshold
            ):
                rejection_reasons.append(
                    (
                        "Move-up probability is below "
                        f"{buy_threshold:.0f}%."
                    )
                )

            confidence_score = normalize_score(
                (
                    completeness * 0.45
                    + adjusted_score * 0.55
                )
            )

            result = ProbabilityResult(
                timeframe=normalized_timeframe,
                probability=probability,
                confidence_score=confidence_score,
                overall_score=adjusted_score,
                signal=normalize_signal(signal),
                available_weight=available_weight,
                total_weight=total_weight,
                data_completeness=completeness,
                components=components,
                rejection_reasons=list(
                    dict.fromkeys(
                        rejection_reasons
                    )
                ),
                generated_at=utc_now().isoformat(),
            )

            logger.info(
                (
                    "Probability calculated with "
                    "signal=%s and probability=%.2f."
                ),
                signal,
                probability,
                extra=build_log_extra(
                    component="probability_engine",
                    timeframe=normalized_timeframe,
                    event="probability_calculated",
                    status=(
                        "success"
                        if signal
                        in {
                            "BUY",
                            "STRONG BUY",
                        }
                        else "rejected"
                    ),
                    probability=probability,
                    overall_score=adjusted_score,
                    completeness=completeness,
                ),
            )

            return result.to_dict()

        except Exception as exception:
            log_exception(
                logger,
                "Probability calculation failed",
                exception=exception,
                timeframe=normalized_timeframe,
                component="probability_engine",
                error_code=(
                    "PROBABILITY_CALCULATION_FAILED"
                ),
            )

            raise ProbabilityEngineError(
                "Unable to calculate stock probability."
            ) from exception


_global_probability_engine: (
    ProbabilityEngine | None
) = None


def get_probability_engine(
) -> ProbabilityEngine:
    global _global_probability_engine

    if _global_probability_engine is None:
        _global_probability_engine = (
            ProbabilityEngine()
        )

    return _global_probability_engine
