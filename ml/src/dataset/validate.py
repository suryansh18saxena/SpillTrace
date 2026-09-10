"""Probe a dataset file and fail loudly on a mismatch (AD-09, P10-002).

The publisher states the images are 2048×2048×2 GeoTIFFs of Sentinel-1 σ0 in dB, and
says **nothing** about the pixel dtype or whether band 1 is VV or VH.  Assuming either
one is how a pipeline ends up training on channels in the wrong order, which costs
accuracy in a way that never raises an exception and never looks like a bug.

So this module opens a file, reports what is actually there, and refuses to continue when
it disagrees with the configured expectation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DatasetValidationError(RuntimeError):
    """The data on disk is not the data the configuration describes."""


@dataclass(frozen=True)
class RasterProbe:
    path: str
    band_count: int
    height: int
    width: int
    dtype: str
    band_descriptions: tuple[str, ...]
    crs: str | None
    nodata: float | None
    value_min: float
    value_max: float

    @property
    def looks_like_db(self) -> bool:
        """σ0 in dB is negative over the ocean; linear σ0 is a small positive power."""
        return self.value_min < 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "band_count": self.band_count,
            "shape": [self.height, self.width],
            "dtype": self.dtype,
            "band_descriptions": list(self.band_descriptions),
            "crs": self.crs,
            "nodata": self.nodata,
            "value_range": [round(self.value_min, 4), round(self.value_max, 4)],
            "looks_like_db": self.looks_like_db,
        }


def probe_raster(path: str | Path) -> RasterProbe:
    import rasterio

    with rasterio.open(str(path)) as dataset:
        sample = dataset.read(1, out_shape=(min(dataset.height, 512), min(dataset.width, 512)))
        return RasterProbe(
            path=str(path),
            band_count=int(dataset.count),
            height=int(dataset.height),
            width=int(dataset.width),
            dtype=str(dataset.dtypes[0]),
            band_descriptions=tuple(d or "" for d in dataset.descriptions),
            crs=str(dataset.crs) if dataset.crs else None,
            nodata=dataset.nodata,
            value_min=float(sample.min()),
            value_max=float(sample.max()),
        )


def validate_image(
    path: str | Path,
    *,
    expected_bands: int = 2,
    expected_dtype: str | None = None,
    expect_db: bool = True,
) -> RasterProbe:
    """Probe one image and raise with the observed values when it disagrees."""
    probe = probe_raster(path)
    problems: list[str] = []
    if probe.band_count != expected_bands:
        problems.append(f"expected {expected_bands} bands, found {probe.band_count}")
    if expected_dtype is not None and probe.dtype != expected_dtype:
        problems.append(f"expected dtype {expected_dtype}, found {probe.dtype}")
    if expect_db and not probe.looks_like_db:
        problems.append(
            f"values in [{probe.value_min:.4f}, {probe.value_max:.4f}] do not look like dB "
            "(dB backscatter over water is negative). The images may be linear σ0."
        )
    if problems:
        raise DatasetValidationError(
            f"{path}: " + "; ".join(problems) + f". Observed: {probe.to_dict()}"
        )
    return probe


def validate_mask(path: str | Path) -> RasterProbe:
    """Masks are single-band with foreground 1 and background 0."""
    probe = probe_raster(path)
    problems: list[str] = []
    if probe.band_count != 1:
        problems.append(f"expected 1 band, found {probe.band_count}")
    if probe.value_min < 0.0 or probe.value_max > 1.0:
        problems.append(f"values in [{probe.value_min}, {probe.value_max}] are not a 0/1 mask")
    if problems:
        raise DatasetValidationError(
            f"{path}: " + "; ".join(problems) + f". Observed: {probe.to_dict()}"
        )
    return probe


def report_band_order(probe: RasterProbe, expected: tuple[str, ...]) -> dict[str, Any]:
    """State what we assumed about band order, since the publisher did not say.

    This never raises: the file carries no evidence either way.  It records the
    assumption so the manifest, and anyone reading a result, can see it was one.
    """
    described = tuple(d for d in probe.band_descriptions if d)
    return {
        "assumed_band_order": list(expected),
        "file_band_descriptions": list(described),
        "confirmed_by_file": bool(described) and len(described) == len(expected),
        "note": (
            "The dataset publisher does not state which band is VV. The order above is "
            "an assumption unless 'confirmed_by_file' is true."
        ),
    }


__all__ = [
    "DatasetValidationError",
    "RasterProbe",
    "probe_raster",
    "report_band_order",
    "validate_image",
    "validate_mask",
]
