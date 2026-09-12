"""SAR preprocessing (FR-004, ML_PIPELINE §2, AD-12).

```
σ0 (linear) ──► 10·log10 ──► per-scene percentile clip ──► standardise ──► masked stack
```

Three decisions in here are load-bearing:

**The clip is per scene and it is recorded.**  There is no canonical fixed dB range in
the literature — papers clip by percentile — so a fixed pair would be an invention.  The
1st/99th percentile bounds are computed per scene and written into the run manifest,
which makes the transform reproducible and invertible when the report has to state what
a pixel value meant.

**No-data never enters a statistic.**  A GRD's zero-fill border is a large, perfectly
dark region.  Letting it into the percentile computation drags the low bound down and
makes every real slick look less anomalous than it is.

**A missing VH is recorded, never hidden.**  Single-polarisation scenes exist.  The
channel is duplicated so the model still receives the two channels it was built for, and
a note says so, in the manifest and in the detection row.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

#: ML_PIPELINE §2 / AD-12.
DEFAULT_CLIP_PERCENTILES: tuple[float, float] = (1.0, 99.0)

#: The order the model expects.  Written down because a silent channel swap between
#: training and inference is invisible and destroys accuracy.
CHANNEL_ORDER: tuple[str, str] = ("VV", "VH")

#: σ0 at or below this is not a measurement — it is fill, or a numerical zero.
MIN_VALID_SIGMA0 = 1e-8


@dataclass(frozen=True, slots=True)
class BandStatistics:
    """Everything needed to reproduce — or invert — one band's normalisation."""

    polarization: str
    clip_low_db: float
    clip_high_db: float
    mean_db: float
    std_db: float
    valid_fraction: float
    percentiles: tuple[float, float] = DEFAULT_CLIP_PERCENTILES
    source: str = "measured"

    def to_dict(self) -> dict[str, Any]:
        return {
            "polarization": self.polarization,
            "clip_low_db": round(self.clip_low_db, 4),
            "clip_high_db": round(self.clip_high_db, 4),
            "mean_db": round(self.mean_db, 4),
            "std_db": round(self.std_db, 4),
            "valid_fraction": round(self.valid_fraction, 6),
            "percentiles": list(self.percentiles),
            "source": self.source,
        }

    def invert(self, standardised: np.ndarray) -> np.ndarray:
        """Map standardised values back to clipped dB, for reporting."""
        return np.asarray(standardised, dtype=np.float32) * self.std_db + self.mean_db


@dataclass(frozen=True, slots=True)
class PreprocessedScene:
    """A model-ready stack plus the provenance of every transform applied to it."""

    array: np.ndarray  # (C, H, W) float32, standardised
    valid_mask: np.ndarray  # (H, W) bool
    bands: tuple[str, ...]
    statistics: tuple[BandStatistics, ...]
    notes: tuple[str, ...] = ()

    @property
    def height(self) -> int:
        return int(self.array.shape[1])

    @property
    def width(self) -> int:
        return int(self.array.shape[2])

    @property
    def channels(self) -> int:
        return int(self.array.shape[0])

    def to_manifest(self) -> dict[str, Any]:
        return {
            "bands": list(self.bands),
            "channel_order": list(CHANNEL_ORDER),
            "shape": [self.channels, self.height, self.width],
            "valid_fraction": round(float(self.valid_mask.mean()), 6),
            "normalisation": {
                "method": "per-scene percentile clip then standardise",
                "reference": "docs/DECISIONS.md AD-12",
                "bands": [stat.to_dict() for stat in self.statistics],
            },
            "notes": list(self.notes),
        }


def sigma0_to_db(
    sigma0: np.ndarray, *, nodata: float | None = 0.0, already_db: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """Convert linear σ0 to dB and report which pixels were measurements.

    Returns ``(db, valid)``.  Invalid pixels hold ``nan`` in ``db`` so no arithmetic can
    quietly consume them; callers select with ``valid``.

    ``already_db`` is for sources that publish σ0 *in dB* — several public training sets
    do.  Logging such a raster a second time would not merely distort it: dB values are
    negative, so ``values > MIN_VALID_SIGMA0`` rejects every pixel and the scene returns
    empty rather than wrong, which is much harder to notice.
    """
    values = np.asarray(sigma0, dtype=np.float64)
    if already_db:
        valid = np.isfinite(values)
        if nodata is not None:
            valid &= values != nodata
        db = np.full(values.shape, np.nan, dtype=np.float32)
        db[valid] = values[valid].astype(np.float32)
        return db, valid
    valid = np.isfinite(values) & (values > MIN_VALID_SIGMA0)
    if nodata is not None:
        valid &= values != nodata
    db = np.full(values.shape, np.nan, dtype=np.float32)
    if valid.any():
        db[valid] = (10.0 * np.log10(values[valid])).astype(np.float32)
    return db, valid


def percentile_clip_bounds(
    db: np.ndarray,
    valid: np.ndarray,
    *,
    percentiles: tuple[float, float] = DEFAULT_CLIP_PERCENTILES,
) -> tuple[float, float]:
    """Per-scene clip bounds from the dB histogram of valid pixels only."""
    low_p, high_p = percentiles
    if not (0.0 <= low_p < high_p <= 100.0):
        raise ValueError(
            f"Clip percentiles must satisfy 0 <= low < high <= 100, got {percentiles}."
        )
    sample = db[valid]
    sample = sample[np.isfinite(sample)]
    if sample.size == 0:
        # No measurement at all: a degenerate but legitimate outcome for an all-fill
        # window.  Returning a unit range keeps the transform total instead of raising.
        return 0.0, 1.0
    low = float(np.percentile(sample, low_p))
    high = float(np.percentile(sample, high_p))
    if high <= low:
        high = low + 1.0
    return low, high


def clip_and_standardise(
    db: np.ndarray,
    valid: np.ndarray,
    *,
    polarization: str,
    percentiles: tuple[float, float] = DEFAULT_CLIP_PERCENTILES,
    fill_value: float = 0.0,
) -> tuple[np.ndarray, BandStatistics]:
    """Clip to the per-scene percentile band, then standardise with the same statistics.

    Mean and standard deviation are taken **after** clipping so the two halves of the
    transform describe the same distribution; invalid pixels are filled with the post-
    standardisation mean (zero), which keeps them from biasing a convolution.
    """
    low, high = percentile_clip_bounds(db, valid, percentiles=percentiles)
    clipped = np.clip(np.nan_to_num(db, nan=low), low, high).astype(np.float32)

    sample = clipped[valid]
    if sample.size:
        mean = float(sample.mean())
        std = float(sample.std())
    else:
        mean, std = 0.0, 1.0
    if std < 1e-6:
        # A constant band carries no information; standardising by ~0 would explode it.
        std = 1.0

    standardised = ((clipped - mean) / std).astype(np.float32)
    standardised[~valid] = np.float32(fill_value)
    stats = BandStatistics(
        polarization=polarization,
        clip_low_db=low,
        clip_high_db=high,
        mean_db=mean,
        std_db=std,
        valid_fraction=float(valid.mean()) if valid.size else 0.0,
        percentiles=percentiles,
    )
    return standardised, stats


def preprocess_bands(
    bands: Mapping[str, np.ndarray],
    *,
    percentiles: tuple[float, float] = DEFAULT_CLIP_PERCENTILES,
    nodata: float | None = 0.0,
    channel_order: Sequence[str] = CHANNEL_ORDER,
    already_db: bool = False,
) -> PreprocessedScene:
    """Turn ``{"VV": σ0, "VH": σ0}`` into a standardised ``(C, H, W)`` stack.

    A missing channel is filled by duplicating one that is present, and the substitution
    is recorded in ``notes`` — a silently duplicated channel would look identical to a
    genuine dual-pol scene in every artifact downstream.
    """
    if not bands:
        raise ValueError("At least one polarisation is required.")

    available = {key.upper(): np.asarray(value) for key, value in bands.items()}
    shapes = {value.shape for value in available.values()}
    if len(shapes) != 1:
        raise ValueError(f"All bands must share one shape; got {sorted(shapes)}.")

    notes: list[str] = []
    if already_db:
        notes.append(
            "Bands were supplied as σ0 already in dB; the linear-to-dB conversion was skipped."
        )
    substitute = next((name for name in channel_order if name in available), next(iter(available)))

    channels: list[np.ndarray] = []
    statistics: list[BandStatistics] = []
    names: list[str] = []
    valid_all: np.ndarray | None = None

    for wanted in channel_order:
        source_name = wanted if wanted in available else substitute
        if source_name != wanted:
            notes.append(f"{wanted} unavailable; {source_name} duplicated")
        db, valid = sigma0_to_db(available[source_name], nodata=nodata, already_db=already_db)
        standardised, stats = clip_and_standardise(
            db, valid, polarization=wanted, percentiles=percentiles
        )
        if source_name != wanted:
            stats = BandStatistics(
                polarization=wanted,
                clip_low_db=stats.clip_low_db,
                clip_high_db=stats.clip_high_db,
                mean_db=stats.mean_db,
                std_db=stats.std_db,
                valid_fraction=stats.valid_fraction,
                percentiles=stats.percentiles,
                source=f"duplicated from {source_name}",
            )
        channels.append(standardised)
        statistics.append(stats)
        names.append(wanted)
        valid_all = valid if valid_all is None else (valid_all & valid)

    stack = np.stack(channels).astype(np.float32)
    mask = valid_all if valid_all is not None else np.ones(stack.shape[1:], dtype=bool)
    return PreprocessedScene(
        array=stack,
        valid_mask=mask,
        bands=tuple(names),
        statistics=tuple(statistics),
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------- raster IO
def read_sigma0_band(
    payload: bytes, *, max_dimension: int = 4096
) -> tuple[np.ndarray, tuple[float, float, float, float], dict[str, Any]]:
    """Read one measurement band, decimating on read.

    A GRD swath is ~25 000 × 16 000 pixels; loading one at full resolution costs 1.6 GB
    per band before any arithmetic, which this host does not have.  Reading with
    ``out_shape`` lets rasterio pull a **Cloud-Optimised GeoTIFF's overviews** instead of
    the full-resolution grid — which is the concrete payoff of downloading COG nodes
    rather than the SAFE archive (AD-08).

    Returns ``(array, bounds, meta)``.  ``meta['georeferenced']`` is False when the file
    carries no CRS — a real GRD is annotated with a GCP grid rather than a simple affine,
    and the caller must then take its bounds from the product footprint and say so.
    """
    from rasterio.enums import Resampling
    from rasterio.io import MemoryFile

    with MemoryFile(payload) as memfile, memfile.open() as dataset:
        height, width = int(dataset.height), int(dataset.width)
        decimation = max(1, -(-max(height, width) // max(1, max_dimension)))
        out_height = max(1, height // decimation)
        out_width = max(1, width // decimation)
        array = dataset.read(1, out_shape=(out_height, out_width), resampling=Resampling.average)
        crs = dataset.crs
        meta: dict[str, Any] = {
            "source_shape": [height, width],
            "read_shape": [out_height, out_width],
            "decimation": decimation,
            "crs": str(crs) if crs else None,
            "georeferenced": bool(crs),
            "nodata": dataset.nodata,
            "description": dataset.descriptions[0] if dataset.descriptions else None,
        }
        bounds = (
            float(dataset.bounds.left),
            float(dataset.bounds.bottom),
            float(dataset.bounds.right),
            float(dataset.bounds.top),
        )
    return np.asarray(array, dtype=np.float32), bounds, meta


__all__ = [
    "CHANNEL_ORDER",
    "DEFAULT_CLIP_PERCENTILES",
    "MIN_VALID_SIGMA0",
    "BandStatistics",
    "PreprocessedScene",
    "clip_and_standardise",
    "percentile_clip_bounds",
    "preprocess_bands",
    "read_sigma0_band",
    "sigma0_to_db",
]
