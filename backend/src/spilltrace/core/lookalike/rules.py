"""Verification rules.

Each rule is a small, named, independently testable function that reports what it
observed, what it compared against, and a sentence a human can read.  The rule set is
data, not control flow, so adding evidence types does not mean rewriting the engine.

Every threshold here traces to a citation in ``docs/DECISIONS.md`` AD-15/AD-16.  Where
the literature gives a range rather than a number, the rule scores continuously across
it instead of pretending a hard boundary exists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from spilltrace.core.lookalike.features import SlickFeatures

# --- wind response (SAR oil-spill meta-analysis, GIScience & Remote Sensing 2021,
#     Table 6; corroborated by Najoui et al. 2018: 95% of 3,903 slicks fell in
#     2.09-8.33 m/s across 1,333 scenes) ---
WIND_GLASSY_MAX_MS = 2.0  # below: no Bragg waves to damp; a dark patch means nothing
WIND_LOOKALIKE_PEAK_MAX_MS = 4.0  # 2-4: detectable, but look-alikes peak here
WIND_OPTIMAL_MIN_MS = 4.0
WIND_OPTIMAL_MAX_MS = 10.0
WIND_THIN_DISPERSED_MAX_MS = 12.0  # 10-12: only thick slicks survive
# above 12: slicks broken up and dispersed

#: Oil trails from a moving vessel are long and irregular; low-wind patches are smooth.
COMPLEXITY_OIL_MIN = 1.6
ELONGATION_OIL_MIN = 2.0
#: Slicks below this are usually too small to attribute; above it, more likely natural.
AREA_MIN_KM2 = 0.5
AREA_LARGE_KM2 = 1500.0
#: Oil suppresses backscatter strongly; a few dB of contrast is more likely sea state.
CONTRAST_STRONG_DB = 6.0
CONTRAST_WEAK_DB = 2.0
#: Oil damps uniformly, so its relative variance is lower than the surrounding sea.
POWER_RATIO_OIL_MAX = 0.9


@dataclass(slots=True)
class RuleResult:
    rule_id: str
    label: str
    #: -1.0 (strong evidence against oil) … +1.0 (strong evidence for oil)
    evidence: float
    weight: float
    message: str
    observed: Any = None
    threshold: Any = None
    applicable: bool = True
    veto: bool = False  # a physical impossibility, not merely negative evidence

    @property
    def passed(self) -> bool:
        return self.evidence > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "label": self.label,
            "evidence": round(self.evidence, 4),
            "weight": self.weight,
            "passed": self.passed,
            "applicable": self.applicable,
            "veto": self.veto,
            "observed": self.observed,
            "threshold": self.threshold,
            "message": self.message,
        }


Rule = Callable[[SlickFeatures], RuleResult]


def _not_applicable(rule_id: str, label: str, weight: float, why: str) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        label=label,
        evidence=0.0,
        weight=weight,
        message=why,
        applicable=False,
    )


# --------------------------------------------------------------------------- rules
def rule_wind_window(features: SlickFeatures) -> RuleResult:
    """The single most useful physical discriminator (AD-15)."""
    weight = 0.30
    wind = features.wind_speed_ms
    if wind is None:
        return _not_applicable(
            "wind_window",
            "Wind conditions",
            weight,
            "No wind measurement was available for the acquisition time and location, so "
            "the wind check could not be applied.",
        )

    threshold = {
        "glassy_below_ms": WIND_GLASSY_MAX_MS,
        "optimal_ms": [WIND_OPTIMAL_MIN_MS, WIND_OPTIMAL_MAX_MS],
        "dispersed_above_ms": WIND_THIN_DISPERSED_MAX_MS,
    }

    if wind < WIND_GLASSY_MAX_MS:
        return RuleResult(
            "wind_window",
            "Wind conditions",
            -1.0,
            weight,
            f"Wind was {wind:.1f} m/s. Below {WIND_GLASSY_MAX_MS:.0f} m/s the sea surface "
            "is glassy: there are no short waves for oil to damp, so a dark SAR patch "
            "cannot be attributed to oil.",
            observed=wind,
            threshold=threshold,
            veto=True,
        )
    if wind > WIND_THIN_DISPERSED_MAX_MS:
        return RuleResult(
            "wind_window",
            "Wind conditions",
            -0.8,
            weight,
            f"Wind was {wind:.1f} m/s. Above {WIND_THIN_DISPERSED_MAX_MS:.0f} m/s slicks "
            "are broken up and dispersed, so a detection here is unlikely to be oil.",
            observed=wind,
            threshold=threshold,
            veto=True,
        )
    if WIND_OPTIMAL_MIN_MS <= wind <= WIND_OPTIMAL_MAX_MS:
        return RuleResult(
            "wind_window",
            "Wind conditions",
            1.0,
            weight,
            f"Wind was {wind:.1f} m/s, inside the {WIND_OPTIMAL_MIN_MS:.0f}-"
            f"{WIND_OPTIMAL_MAX_MS:.0f} m/s window in which SAR oil detection is most "
            "reliable.",
            observed=wind,
            threshold=threshold,
        )
    if wind < WIND_OPTIMAL_MIN_MS:
        return RuleResult(
            "wind_window",
            "Wind conditions",
            -0.3,
            weight,
            f"Wind was {wind:.1f} m/s. Between {WIND_GLASSY_MAX_MS:.0f} and "
            f"{WIND_LOOKALIKE_PEAK_MAX_MS:.0f} m/s oil is detectable, but this is also "
            "where natural look-alike features are most common.",
            observed=wind,
            threshold=threshold,
        )
    return RuleResult(
        "wind_window",
        "Wind conditions",
        0.2,
        weight,
        f"Wind was {wind:.1f} m/s. Between {WIND_OPTIMAL_MAX_MS:.0f} and "
        f"{WIND_THIN_DISPERSED_MAX_MS:.0f} m/s thin films disperse, so recall is low - "
        "but a feature that survives these conditions is more likely to be genuine.",
        observed=wind,
        threshold=threshold,
    )


def rule_shape_complexity(features: SlickFeatures) -> RuleResult:
    weight = 0.13
    complexity = features.complexity
    if complexity >= COMPLEXITY_OIL_MIN:
        return RuleResult(
            "shape_complexity",
            "Boundary irregularity",
            0.8,
            weight,
            f"Boundary complexity is {complexity:.2f} (a circle scores 1.0). An irregular, "
            "drawn-out boundary is characteristic of oil spreading and weathering, and "
            "argues against a smooth low-wind patch.",
            observed=round(complexity, 3),
            threshold=COMPLEXITY_OIL_MIN,
        )
    return RuleResult(
        "shape_complexity",
        "Boundary irregularity",
        -0.5,
        weight,
        f"Boundary complexity is {complexity:.2f}, close to a smooth rounded shape. "
        "Low-wind zones and biogenic films typically look like this.",
        observed=round(complexity, 3),
        threshold=COMPLEXITY_OIL_MIN,
    )


def rule_elongation(features: SlickFeatures) -> RuleResult:
    weight = 0.10
    elongation = features.elongation
    if elongation >= ELONGATION_OIL_MIN:
        return RuleResult(
            "elongation",
            "Elongation",
            0.8,
            weight,
            f"The feature is {elongation:.1f} times longer than it is wide. A pronounced "
            "linear form is typical of a discharge trailing behind a moving vessel.",
            observed=round(elongation, 3),
            threshold=ELONGATION_OIL_MIN,
        )
    return RuleResult(
        "elongation",
        "Elongation",
        -0.3,
        weight,
        f"The feature is {elongation:.1f} times longer than it is wide, so it is close to "
        "equidimensional. That is more consistent with a natural surface feature than "
        "with a vessel discharge.",
        observed=round(elongation, 3),
        threshold=ELONGATION_OIL_MIN,
    )


def rule_area(features: SlickFeatures) -> RuleResult:
    weight = 0.07
    area = features.area_km2
    if area < AREA_MIN_KM2:
        return RuleResult(
            "area",
            "Detected area",
            -0.4,
            weight,
            f"The feature covers {area:.2f} km², which is at the limit of what can be "
            "reliably distinguished from speckle at Sentinel-1 GRD resolution.",
            observed=round(area, 3),
            threshold=AREA_MIN_KM2,
        )
    if area > AREA_LARGE_KM2:
        return RuleResult(
            "area",
            "Detected area",
            -0.4,
            weight,
            f"The feature covers {area:,.0f} km². Features this large are more often "
            "meteorological or oceanographic than a single discharge.",
            observed=round(area, 1),
            threshold=AREA_LARGE_KM2,
        )
    return RuleResult(
        "area",
        "Detected area",
        0.5,
        weight,
        f"The feature covers {area:.1f} km², a plausible size for an operational discharge.",
        observed=round(area, 3),
        threshold=[AREA_MIN_KM2, AREA_LARGE_KM2],
    )


def rule_contrast(features: SlickFeatures) -> RuleResult:
    weight = 0.25
    contrast = features.contrast_db
    if contrast is None:
        return _not_applicable(
            "contrast",
            "Backscatter contrast",
            weight,
            "The source SAR imagery was not available, so backscatter contrast could not "
            "be measured.",
        )
    if contrast >= CONTRAST_STRONG_DB:
        return RuleResult(
            "contrast",
            "Backscatter contrast",
            1.0,
            weight,
            f"The feature is {contrast:.1f} dB darker than the surrounding sea. Strong "
            "damping of this kind is characteristic of a surface film.",
            observed=round(contrast, 2),
            threshold=CONTRAST_STRONG_DB,
        )
    if contrast >= CONTRAST_WEAK_DB:
        return RuleResult(
            "contrast",
            "Backscatter contrast",
            0.2,
            weight,
            f"The feature is {contrast:.1f} dB darker than the surrounding sea. That is a "
            "modest difference which sea-state variation alone can produce.",
            observed=round(contrast, 2),
            threshold=CONTRAST_WEAK_DB,
        )
    # Below ~2 dB there is essentially no damping signature to explain: whatever the
    # shape looks like, this is not a dark feature.  Treated as a veto rather than
    # negative evidence, so a convincing outline cannot out-vote the physics.
    return RuleResult(
        "contrast",
        "Backscatter contrast",
        -1.0,
        weight,
        f"The feature is only {contrast:.1f} dB darker than the surrounding sea. Below "
        f"{CONTRAST_WEAK_DB:.0f} dB there is no meaningful damping signature, so the "
        "feature is not distinguishable from normal sea-surface variation.",
        observed=round(contrast, 2),
        threshold=CONTRAST_WEAK_DB,
        veto=True,
    )


def rule_power_ratio(features: SlickFeatures) -> RuleResult:
    weight = 0.10
    ratio = features.power_to_mean_ratio
    if ratio is None:
        return _not_applicable(
            "power_ratio",
            "Relative backscatter variance",
            weight,
            "The source SAR imagery was not available, so the power-to-mean ratio could "
            "not be computed.",
        )
    if ratio <= POWER_RATIO_OIL_MAX:
        return RuleResult(
            "power_ratio",
            "Relative backscatter variance",
            0.7,
            weight,
            f"The feature's power-to-mean ratio relative to the background is {ratio:.2f}. "
            "Oil damps the surface uniformly, giving a lower relative variance than the "
            "surrounding sea.",
            observed=round(ratio, 3),
            threshold=POWER_RATIO_OIL_MAX,
        )
    return RuleResult(
        "power_ratio",
        "Relative backscatter variance",
        -0.4,
        weight,
        f"The feature's power-to-mean ratio relative to the background is {ratio:.2f}. "
        "A patch that is as variable as the sea around it is more consistent with a wind "
        "or current feature than with a uniform film.",
        observed=round(ratio, 3),
        threshold=POWER_RATIO_OIL_MAX,
    )


def rule_border_gradient(features: SlickFeatures) -> RuleResult:
    weight = 0.05
    gradient = features.gradient_mean
    if gradient is None:
        return _not_applicable(
            "border_gradient",
            "Edge sharpness",
            weight,
            "No probability raster was available, so edge sharpness could not be measured.",
        )
    # The threshold is scale-dependent, so this rule is deliberately given a small
    # weight and phrased as supporting rather than decisive evidence.
    if gradient >= 0.02:
        return RuleResult(
            "border_gradient",
            "Edge sharpness",
            0.5,
            weight,
            f"The boundary transition is sharp (mean gradient {gradient:.3f}). Oil films "
            "have a well-defined edge, whereas low-wind areas fade gradually.",
            observed=round(gradient, 5),
            threshold=0.02,
        )
    return RuleResult(
        "border_gradient",
        "Edge sharpness",
        -0.3,
        weight,
        f"The boundary transition is diffuse (mean gradient {gradient:.3f}), which is "
        "more typical of a wind-shadow area than of an oil film.",
        observed=round(gradient, 5),
        threshold=0.02,
    )


DEFAULT_RULES: tuple[Rule, ...] = (
    rule_wind_window,
    rule_contrast,
    rule_shape_complexity,
    rule_elongation,
    rule_power_ratio,
    rule_area,
    rule_border_gradient,
)


@dataclass(slots=True)
class RuleSet:
    rules: tuple[Rule, ...] = field(default=DEFAULT_RULES)

    def evaluate(self, features: SlickFeatures) -> list[RuleResult]:
        return [rule(features) for rule in self.rules]


__all__ = [
    "AREA_LARGE_KM2",
    "AREA_MIN_KM2",
    "COMPLEXITY_OIL_MIN",
    "CONTRAST_STRONG_DB",
    "CONTRAST_WEAK_DB",
    "DEFAULT_RULES",
    "ELONGATION_OIL_MIN",
    "POWER_RATIO_OIL_MAX",
    "WIND_GLASSY_MAX_MS",
    "WIND_OPTIMAL_MAX_MS",
    "WIND_OPTIMAL_MIN_MS",
    "WIND_THIN_DISPERSED_MAX_MS",
    "Rule",
    "RuleResult",
    "RuleSet",
]
