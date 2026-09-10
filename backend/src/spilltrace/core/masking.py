"""Turning a probability raster into a mask (FR-005, ML_PIPELINE §9).

```
probability ──► hysteresis threshold ──► morphological open/close ──► min-area filter
```

Every parameter here is configurable **and recorded**, because each one can delete a real
detection:

* a single high threshold cuts thin slicks into dashes — the low arm of a hysteresis
  threshold keeps a weak pixel when it is connected to a confident one, which is what
  keeps a tapering discharge trail whole;
* an undocumented ``opening`` erases a genuine one-pixel-wide trail entirely, and the
  case would never show that it had been there;
* a ``min_area`` chosen for one pixel size silently changes meaning at another.

So the configuration travels into the run manifest, and the counts removed at each step
are reported alongside the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import ndimage

#: A confident oil pixel.  Also the threshold reported with every detection.
DEFAULT_THRESHOLD = 0.5
#: The hysteresis floor: a pixel this probable is kept only when it touches a confident
#: one.  Below it, nothing is kept at all.
DEFAULT_HYSTERESIS_LOW = 0.35
DEFAULT_OPENING_RADIUS = 1
DEFAULT_CLOSING_RADIUS = 2
DEFAULT_MIN_AREA_PX = 64

#: Eight-connectivity throughout: a slick one pixel wide that steps diagonally is one
#: slick, and four-connectivity would split it into a string of fragments.
_CONNECTIVITY = ndimage.generate_binary_structure(2, 2)


@dataclass(frozen=True, slots=True)
class MaskConfig:
    threshold: float = DEFAULT_THRESHOLD
    hysteresis_low: float = DEFAULT_HYSTERESIS_LOW
    opening_radius_px: int = DEFAULT_OPENING_RADIUS
    closing_radius_px: int = DEFAULT_CLOSING_RADIUS
    min_area_px: int = DEFAULT_MIN_AREA_PX
    fill_holes: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.hysteresis_low <= self.threshold <= 1.0:
            raise ValueError(
                "Require 0 <= hysteresis_low <= threshold <= 1, got "
                f"low={self.hysteresis_low}, threshold={self.threshold}."
            )
        if min(self.opening_radius_px, self.closing_radius_px, self.min_area_px) < 0:
            raise ValueError("Morphology radii and min_area_px must be non-negative.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "hysteresis_low": self.hysteresis_low,
            "opening_radius_px": self.opening_radius_px,
            "closing_radius_px": self.closing_radius_px,
            "min_area_px": self.min_area_px,
            "fill_holes": self.fill_holes,
            "connectivity": 8,
        }


@dataclass(frozen=True, slots=True)
class MaskResult:
    mask: np.ndarray
    labels: np.ndarray
    component_count: int
    pixel_count: int
    config: MaskConfig
    stages: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "component_count": self.component_count,
            "pixel_count": self.pixel_count,
            "pixels_after_stage": dict(self.stages),
        }


def disk(radius: int) -> np.ndarray:
    """A digital disk structuring element; radius 0 is a no-op single pixel."""
    if radius <= 0:
        return np.ones((1, 1), dtype=bool)
    rows, cols = np.ogrid[-radius : radius + 1, -radius : radius + 1]
    return (rows**2 + cols**2) <= radius**2 + 1e-9


def hysteresis_threshold(probability: np.ndarray, *, high: float, low: float) -> np.ndarray:
    """Keep every component of ``probability >= low`` that contains a ``>= high`` pixel."""
    values = np.asarray(probability, dtype=np.float32)
    strong = values >= high
    weak = values >= low
    if not strong.any():
        return np.zeros(values.shape, dtype=bool)
    if low >= high:
        return strong

    labels, count = ndimage.label(weak, structure=_CONNECTIVITY)
    if count == 0:
        return np.zeros(values.shape, dtype=bool)
    keep = np.zeros(count + 1, dtype=bool)
    keep[np.unique(labels[strong])] = True
    keep[0] = False
    return keep[labels]


def morphological_clean(
    mask: np.ndarray,
    *,
    opening_radius: int = DEFAULT_OPENING_RADIUS,
    closing_radius: int = DEFAULT_CLOSING_RADIUS,
    fill_holes: bool = True,
) -> np.ndarray:
    """Open to drop speckle, close to bridge gaps, then optionally fill interior holes.

    Opening comes first on purpose: closing first would weld isolated speckle into
    blobs large enough to survive the opening that follows.
    """
    cleaned = np.asarray(mask, dtype=bool)
    pad = max(opening_radius, closing_radius)
    if pad > 0:
        # Edge-replicate before the morphology and crop after.  scipy treats everything
        # outside the array as background, which erodes a ring off any slick that
        # reaches the swath edge — precisely the case where truncation has already cost
        # accuracy.  Replication says "the sea continues", which is true, and it still
        # removes an isolated border pixel because the replication is one-dimensional.
        cleaned = np.pad(cleaned, pad, mode="edge")
    if opening_radius > 0:
        cleaned = ndimage.binary_opening(cleaned, structure=disk(opening_radius))
    if closing_radius > 0:
        cleaned = ndimage.binary_closing(cleaned, structure=disk(closing_radius))
    if pad > 0:
        cleaned = cleaned[pad:-pad, pad:-pad]
    if fill_holes:
        cleaned = ndimage.binary_fill_holes(cleaned)
    return np.asarray(cleaned, dtype=bool)


def filter_small_components(
    mask: np.ndarray, *, min_area_px: int
) -> tuple[np.ndarray, np.ndarray, int]:
    """Drop components below ``min_area_px``; returns ``(mask, labels, count)``."""
    labels, count = ndimage.label(np.asarray(mask, dtype=bool), structure=_CONNECTIVITY)
    if count == 0:
        return np.zeros(mask.shape, dtype=bool), labels.astype(np.int32), 0
    if min_area_px <= 1:
        return np.asarray(mask, dtype=bool), labels.astype(np.int32), count

    sizes = np.bincount(labels.ravel(), minlength=count + 1)
    keep = sizes >= min_area_px
    keep[0] = False
    filtered = keep[labels]
    # Relabel so component ids stay contiguous, which keeps downstream indexing simple.
    relabelled, remaining = ndimage.label(filtered, structure=_CONNECTIVITY)
    return filtered, relabelled.astype(np.int32), int(remaining)


def build_mask(
    probability: np.ndarray,
    config: MaskConfig | None = None,
    *,
    valid_mask: np.ndarray | None = None,
) -> MaskResult:
    """Full threshold → morphology → area filter, reporting what each stage removed."""
    config = config or MaskConfig()
    values = np.asarray(probability, dtype=np.float32)
    if valid_mask is not None:
        values = np.where(np.asarray(valid_mask, dtype=bool), values, 0.0).astype(np.float32)

    thresholded = hysteresis_threshold(values, high=config.threshold, low=config.hysteresis_low)
    cleaned = morphological_clean(
        thresholded,
        opening_radius=config.opening_radius_px,
        closing_radius=config.closing_radius_px,
        fill_holes=config.fill_holes,
    )
    filtered, labels, count = filter_small_components(cleaned, min_area_px=config.min_area_px)

    return MaskResult(
        mask=filtered,
        labels=labels,
        component_count=count,
        pixel_count=int(filtered.sum()),
        config=config,
        stages={
            "above_threshold": int((values >= config.threshold).sum()),
            "after_hysteresis": int(thresholded.sum()),
            "after_morphology": int(cleaned.sum()),
            "after_min_area": int(filtered.sum()),
        },
    )


__all__ = [
    "DEFAULT_CLOSING_RADIUS",
    "DEFAULT_HYSTERESIS_LOW",
    "DEFAULT_MIN_AREA_PX",
    "DEFAULT_OPENING_RADIUS",
    "DEFAULT_THRESHOLD",
    "MaskConfig",
    "MaskResult",
    "build_mask",
    "disk",
    "filter_small_components",
    "hysteresis_threshold",
    "morphological_clean",
]
