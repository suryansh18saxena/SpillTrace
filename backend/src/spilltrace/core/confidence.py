"""``detection_confidence`` — one number, one definition, written down.

**Definition.**  ``detection_confidence`` is the **area-weighted mean predicted
probability over the retained polygons**:

```
        Σ_i  area_i · mean_probability_i
conf =  ───────────────────────────────
                 Σ_i  area_i
```

where ``i`` ranges over the polygons that survived masking and the minimum-area filter,
``area_i`` is the geodesic area in km², and ``mean_probability_i`` is the mean of the
model's output over that polygon's pixels.

**Why area weighting.**  A plain mean over polygons lets a 200 m² fragment count as much
as a 40 km² trail.  Weighting by area makes the number describe the detection an analyst
is actually looking at.

**What it is not.**  It is a *model-internal* quantity: how confident the segmentation
was, on its own output, at the stated threshold.  It says nothing about whether the dark
patch is oil rather than a look-alike — that is ``verification_confidence`` — and nothing
about where the oil came from — that is ``origin_confidence``.  The three are reported
side by side and **never multiplied** (AD-28): a product of three unrelated confidences
is not a probability of anything, and it always reads lower than any of its parts, which
would understate evidence rather than qualify it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

DETECTION_CONFIDENCE_DEFINITION = (
    "Area-weighted mean predicted probability over the retained detection polygons, at "
    "the stated threshold. A model-internal quantity: it is never combined with "
    "verification or origin confidence."
)


class HasAreaAndProbability(Protocol):
    @property
    def area_km2(self) -> float: ...

    @property
    def mean_probability(self) -> float: ...


@dataclass(frozen=True, slots=True)
class ConfidenceComponent:
    area_km2: float
    mean_probability: float


def detection_confidence(components: Sequence[HasAreaAndProbability]) -> float:
    """Area-weighted mean probability, clamped to ``[0, 1]``.

    An empty sequence yields ``0.0``: no polygon was retained, so there is nothing to be
    confident about.  Zero-area components fall back to an unweighted mean rather than
    dividing by zero — that happens when every polygon is smaller than one pixel of
    geodesic area, and the honest answer is still their mean.
    """
    if not components:
        return 0.0
    weights = [max(0.0, float(c.area_km2)) for c in components]
    values = [min(1.0, max(0.0, float(c.mean_probability))) for c in components]
    total = sum(weights)
    if total <= 0.0:
        return round(sum(values) / len(values), 4)
    weighted = sum(w * v for w, v in zip(weights, values, strict=True))
    return round(min(1.0, max(0.0, weighted / total)), 4)


def confidence_manifest(threshold: float) -> dict[str, Any]:
    """The block written into a detection's run manifest beside the number."""
    return {
        "detection_confidence": {
            "definition": DETECTION_CONFIDENCE_DEFINITION,
            "threshold": threshold,
            "combined_with_other_confidences": False,
            "reference": "docs/DECISIONS.md AD-28",
        }
    }


__all__ = [
    "DETECTION_CONFIDENCE_DEFINITION",
    "ConfidenceComponent",
    "HasAreaAndProbability",
    "confidence_manifest",
    "detection_confidence",
]
