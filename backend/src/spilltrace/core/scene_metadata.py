"""What a supplied SAR file says about itself — read, never assumed.

The upload-first investigation starts from a file, not from a map.  Before a case exists
the analyst needs to see *where* the scene is, *when* it was acquired and *what* it
contains, and every one of those facts has a different trust level:

* **Location** is a measurement when the file carries a map CRS, and absent otherwise.
* **Acquisition time** is almost never inside a bare GeoTIFF.  It may be recoverable from
  a TIFF date tag or from a Sentinel-1 product name in the filename; when it is not, the
  platform says so and the analyst must state it.  A TIFF ``DateTime`` tag records when
  the *file* was written, which is not when the satellite passed — so it is reported with
  that caveat rather than silently promoted to an acquisition time.
* **Units** (σ0 in dB or linear power) are decided from the pixels, with the reason.

Everything here is pure: bytes or arrays in, plain data out.  The HTTP layer decides what
to store and what to show.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

#: The longest side of a quicklook PNG.  Large enough to read a slick on a map, small
#: enough to ship inline with the inspection response.
QUICKLOOK_MAX_SIDE = 1024

#: Percentiles used to stretch backscatter for display.  Display only — the pipeline
#: never sees the stretched values.
DISPLAY_PERCENTILES = (2.0, 98.0)

# Sentinel-1 product / GRD-measurement naming, e.g.
#   S1A_IW_GRDH_1SDV_20260812T011200_20260812T011225_054321_069ABC_1A2B
#   s1a-iw-grd-vv-20260812t011200-20260812t011225-054321-069abc-001.tiff
_S1_PRODUCT = re.compile(
    r"(?P<mission>S1[ABCD])_(?P<mode>IW|EW|SM|WV)_(?P<type>GRD[HMF]?|SLC|RAW|OCN)_"
    r"(?P<level>\d)(?P<class>[SA])(?P<pol>SH|SV|DH|DV|HH|VV|HV|VH)_"
    r"(?P<start>\d{8}T\d{6})_(?P<stop>\d{8}T\d{6})",
    re.IGNORECASE,
)
_S1_MEASUREMENT = re.compile(
    r"(?P<mission>s1[abcd])-(?P<mode>iw|ew|sm|wv)\d?-(?P<type>grd|slc)-(?P<pol>vv|vh|hh|hv)-"
    r"(?P<start>\d{8}t\d{6})-(?P<stop>\d{8}t\d{6})",
    re.IGNORECASE,
)
# A bare compact timestamp anywhere in the name: 20260812T011200 / 20260812_011200.
_COMPACT_STAMP = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})[T_-]?(\d{2})(\d{2})(\d{2})(?!\d)")
# TIFF DateTime (tag 306) format: "YYYY:MM:DD HH:MM:SS".
_TIFF_DATETIME = re.compile(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")

#: Tags that some SAR toolchains (SNAP, GDAL SAR drivers, ASF HyP3) write with the
#: acquisition start time.  Checked before the generic TIFF DateTime tag.
_ACQUISITION_TAG_KEYS = (
    "ACQUISITION_START_TIME",
    "FIRST_LINE_TIME",
    "ACQUISITION_TIME",
    "SENSING_START",
    "START_TIME",
    "first_line_time",
    "acquisition_start_utc",
)

_POLARISATION_CODES = {
    "SV": ["VV"],
    "SH": ["HH"],
    "DV": ["VV", "VH"],
    "DH": ["HH", "HV"],
    "VV": ["VV"],
    "VH": ["VH"],
    "HH": ["HH"],
    "HV": ["HV"],
}


@dataclass(frozen=True, slots=True)
class AcquisitionTime:
    """An acquisition time and exactly where it came from."""

    value: datetime | None
    source: str | None  # "filename" | "tiff_tag" | "file_timestamp_tag" | None
    detail: str
    is_acquisition: bool  # False when the only time found describes the file, not the pass
    stop: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProductHints:
    """Facts recoverable from a Sentinel-1 style product name."""

    mission: str | None = None
    mode: str | None = None
    product_type: str | None = None
    polarizations: list[str] = field(default_factory=list)
    product_name: str | None = None


def _parse_compact(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp.upper(), "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def product_hints(filename: str) -> ProductHints:
    """Mission, mode, product type and polarisation from a Sentinel-1 name, if present."""
    match = _S1_PRODUCT.search(filename)
    if match:
        return ProductHints(
            mission=f"Sentinel-{match['mission'][1:].upper()}",
            mode=match["mode"].upper(),
            product_type=match["type"].upper(),
            polarizations=list(_POLARISATION_CODES.get(match["pol"].upper(), [])),
            product_name=match.group(0).upper(),
        )
    match = _S1_MEASUREMENT.search(filename)
    if match:
        return ProductHints(
            mission=f"Sentinel-{match['mission'][1:].upper()}",
            mode=match["mode"].upper(),
            product_type=match["type"].upper(),
            polarizations=[match["pol"].upper()],
            product_name=match.group(0).lower(),
        )
    return ProductHints()


def extract_acquisition_time(filename: str, tags: dict[str, str] | None) -> AcquisitionTime:
    """Find the acquisition time a file carries, preferring the most specific source.

    Order: a Sentinel-1 product name (start *and* stop time) → an explicit acquisition tag
    → a compact timestamp in the filename → the TIFF ``DateTime`` tag, which is reported
    but flagged as a *file* timestamp.  Nothing found is a valid, stated outcome.
    """
    tags = tags or {}

    for pattern in (_S1_PRODUCT, _S1_MEASUREMENT):
        match = pattern.search(filename)
        if match:
            start = _parse_compact(match["start"])
            stop = _parse_compact(match["stop"])
            if start is not None:
                return AcquisitionTime(
                    value=start,
                    stop=stop,
                    source="filename",
                    detail=(
                        "read from the Sentinel-1 product name in the filename "
                        f"({match.group(0)})"
                    ),
                    is_acquisition=True,
                )

    lowered = {key.lower(): value for key, value in tags.items()}
    for key in _ACQUISITION_TAG_KEYS:
        value = lowered.get(key.lower())
        if not value:
            continue
        parsed = _parse_any(value)
        if parsed is not None:
            return AcquisitionTime(
                value=parsed,
                source="tiff_tag",
                detail=f"read from the '{key}' metadata tag",
                is_acquisition=True,
            )

    match = _COMPACT_STAMP.search(filename)
    if match:
        try:
            parsed = datetime(*(int(part) for part in match.groups()), tzinfo=UTC)
        except ValueError:
            parsed = None
        if parsed is not None:
            return AcquisitionTime(
                value=parsed,
                source="filename",
                detail=f"read from a timestamp in the filename ({match.group(0)})",
                is_acquisition=True,
            )

    file_stamp = lowered.get("tifftag_datetime")
    if file_stamp:
        parsed = _parse_any(file_stamp)
        if parsed is not None:
            return AcquisitionTime(
                value=parsed,
                source="file_timestamp_tag",
                detail=(
                    "the TIFF DateTime tag records when the file was written, not when the "
                    "satellite acquired the scene; confirm or replace it"
                ),
                is_acquisition=False,
            )

    return AcquisitionTime(
        value=None,
        source=None,
        detail=(
            "the file carries no acquisition time (no Sentinel-1 product name, no "
            "acquisition tag); state it before running the investigation"
        ),
        is_acquisition=False,
    )


def _parse_any(value: str) -> datetime | None:
    text = value.strip()
    match = _TIFF_DATETIME.match(text)
    if match:
        try:
            return datetime(*(int(part) for part in match.groups()), tzinfo=UTC)
        except ValueError:
            return None
    compact = _COMPACT_STAMP.search(text)
    candidates = [text.replace("Z", "+00:00")]
    if compact:
        candidates.append("{}-{}-{}T{}:{}:{}+00:00".format(*compact.groups()))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def band_statistics(array: np.ndarray) -> dict[str, float | int | None]:
    """Min / max / mean / display percentiles over finite pixels."""
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return {
            "min": None,
            "max": None,
            "mean": None,
            "p2": None,
            "p98": None,
            "valid_fraction": 0.0,
        }
    # Percentiles on a stride keep this O(1 MB) even for a 4096² raster.
    sample = finite[:: max(1, finite.size // 1_000_000)]
    low, high = np.percentile(sample, DISPLAY_PERCENTILES)
    return {
        "min": round(float(finite.min()), 4),
        "max": round(float(finite.max()), 4),
        "mean": round(float(finite.mean()), 4),
        "p2": round(float(low), 4),
        "p98": round(float(high), 4),
        "valid_fraction": round(float(finite.size) / float(array.size), 4),
    }


def to_display_db(array: np.ndarray, units: str) -> np.ndarray:
    """σ0 in dB for display; linear input is converted, invalid pixels become NaN."""
    values = np.asarray(array, dtype=np.float32)
    if units == "db":
        return np.where(np.isfinite(values), values, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(values > 1e-8, 10.0 * np.log10(values), np.nan).astype(np.float32)


def downsample(array: np.ndarray, max_side: int = QUICKLOOK_MAX_SIDE) -> np.ndarray:
    """Block-average an array so its longest side is at most ``max_side``."""
    height, width = array.shape
    factor = max(1, -(-max(height, width) // max_side))
    if factor == 1:
        return array
    trimmed = array[: height - height % factor, : width - width % factor]
    blocks = trimmed.reshape(trimmed.shape[0] // factor, factor, trimmed.shape[1] // factor, factor)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN blocks stay NaN
        return np.nanmean(blocks, axis=(1, 3)).astype(np.float32)


def render_quicklook(array: np.ndarray, units: str) -> tuple[bytes, dict[str, Any]]:
    """A greyscale PNG of the first band, percentile-stretched in dB.

    Returns the PNG bytes and the stretch that was applied, so the UI can say what the
    grey levels mean.  No-data pixels are transparent.
    """
    from rasterio.errors import NotGeoreferencedWarning
    from rasterio.io import MemoryFile

    display = downsample(to_display_db(array, units))
    finite = display[np.isfinite(display)]
    if finite.size:
        low, high = (float(v) for v in np.percentile(finite, DISPLAY_PERCENTILES))
    else:
        low, high = -25.0, 0.0
    if high - low < 1e-6:
        high = low + 1.0
    scaled = np.clip((display - low) / (high - low), 0.0, 1.0)
    grey = np.nan_to_num(scaled * 255.0, nan=0.0).astype(np.uint8)
    alpha = np.where(np.isfinite(display), 255, 0).astype(np.uint8)
    rgba = np.stack([grey, grey, grey, alpha])

    height, width = grey.shape
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with MemoryFile() as memfile:
            with memfile.open(
                driver="PNG", height=height, width=width, count=4, dtype="uint8"
            ) as dataset:
                dataset.write(rgba)
            png = bytes(memfile.read())
    return png, {
        "band": 1,
        "units": "dB",
        "stretch_min_db": round(low, 2),
        "stretch_max_db": round(high, 2),
        "percentiles": list(DISPLAY_PERCENTILES),
        "width": int(width),
        "height": int(height),
    }


def pixel_size_m(bounds: tuple[float, float, float, float], width: int, height: int) -> list[float]:
    """Approximate ground pixel size of an EPSG:4326 raster, in metres [x, y]."""
    west, south, east, north = bounds
    mid_lat = (south + north) / 2.0
    metres_per_deg_lat = 111_320.0
    metres_per_deg_lon = metres_per_deg_lat * float(np.cos(np.radians(mid_lat)))
    return [
        round((east - west) / max(1, width) * metres_per_deg_lon, 2),
        round((north - south) / max(1, height) * metres_per_deg_lat, 2),
    ]


__all__ = [
    "QUICKLOOK_MAX_SIDE",
    "AcquisitionTime",
    "ProductHints",
    "band_statistics",
    "downsample",
    "extract_acquisition_time",
    "pixel_size_m",
    "product_hints",
    "render_quicklook",
    "to_display_db",
]
