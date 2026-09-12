"""GeoTIFF helpers.

Rasters are written as Cloud-Optimised GeoTIFFs so the API can serve map tiles by
range-reading overviews instead of pulling the whole file out of object storage.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import rasterio
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

WGS84 = "EPSG:4326"


def write_geotiff(
    array: np.ndarray,
    *,
    bounds: tuple[float, float, float, float],
    crs: str = WGS84,
    nodata: float | None = None,
    dtype: str | None = None,
    band_descriptions: tuple[str, ...] = (),
    tags: dict[str, str] | None = None,
) -> bytes:
    """Serialise a 2-D or 3-D array to an in-memory GeoTIFF.

    ``bounds`` is ``(min_x, min_y, max_x, max_y)``; the array's first row is assumed to
    be the northern edge, which is the convention every raster reader expects.
    """
    if array.ndim == 2:
        array = array[np.newaxis, :, :]
    if array.ndim != 3:
        raise ValueError(f"Expected a 2-D or 3-D array, got {array.ndim} dimensions.")

    count, height, width = array.shape
    transform = from_bounds(*bounds, width=width, height=height)
    out_dtype = dtype or str(array.dtype)

    profile: dict[str, Any] = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": count,
        "dtype": out_dtype,
        "crs": crs,
        "transform": transform,
        "compress": "deflate",
        "predictor": 2 if out_dtype.startswith(("int", "uint")) else 3,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    if nodata is not None:
        profile["nodata"] = nodata

    with MemoryFile() as memfile:
        with memfile.open(**profile) as dataset:
            dataset.write(array.astype(out_dtype))
            for index, description in enumerate(band_descriptions[:count], start=1):
                dataset.set_band_description(index, description)
            if tags:
                dataset.update_tags(**tags)
            # Overviews make map tiling cheap; without them every tile request would
            # decode the full-resolution raster.
            factors = [f for f in (2, 4, 8, 16) if min(height, width) // f >= 32]
            if factors:
                dataset.build_overviews(factors, rasterio.enums.Resampling.average)
        return bytes(memfile.read())


def read_geotiff(data: bytes) -> tuple[np.ndarray, dict[str, Any]]:
    """Read an in-memory GeoTIFF back into ``(array, metadata)``."""
    with MemoryFile(data) as memfile, memfile.open() as dataset:
        array = dataset.read()
        meta = {
            "crs": str(dataset.crs),
            "transform": tuple(dataset.transform)[:6],
            "bounds": tuple(dataset.bounds),
            "count": dataset.count,
            "dtype": str(dataset.dtypes[0]),
            "nodata": dataset.nodata,
            "width": dataset.width,
            "height": dataset.height,
            "descriptions": tuple(d or "" for d in dataset.descriptions),
            "tags": dataset.tags(),
        }
    return array, meta


def array_to_png(
    array: np.ndarray,
    *,
    colormap: str = "probability",
    vmin: float = 0.0,
    vmax: float = 1.0,
) -> bytes:
    """Render a single-band float array to an RGBA PNG for map display.

    The ``probability`` ramp deliberately avoids a red-means-guilty reading: it runs from
    transparent through blue-green to amber, so a high oil probability reads as
    *stronger signal*, not as an accusation.
    """
    normalised = np.clip((array - vmin) / max(1e-9, (vmax - vmin)), 0.0, 1.0)
    height, width = normalised.shape
    rgba = np.zeros((4, height, width), dtype=np.uint8)

    if colormap == "probability":
        stops = np.array(
            [
                [0.0, 12, 74, 110],
                [0.35, 14, 116, 144],
                [0.6, 21, 150, 120],
                [0.8, 202, 138, 4],
                [1.0, 245, 158, 11],
            ]
        )
    elif colormap == "confidence":
        # The design system's validated one-hue ordinal ramp (warm grey → amber →
        # gold, `--confidence-1/2/3`), so the map reads like every other score.
        stops = np.array(
            [
                [0.0, 114, 108, 97],
                [0.5, 191, 138, 51],
                [1.0, 242, 194, 76],
            ]
        )
    else:  # greyscale
        stops = np.array([[0.0, 0, 0, 0], [1.0, 255, 255, 255]])

    for channel in range(3):
        rgba[channel] = np.interp(normalised, stops[:, 0], stops[:, channel + 1]).astype(np.uint8)
    # Fade out low probabilities rather than painting the whole scene.
    if colormap == "confidence":
        alpha = np.clip((normalised - 0.05) / 0.55, 0.0, 1.0)
        rgba[3] = (alpha * 220).astype(np.uint8)
    else:
        rgba[3] = (np.clip(normalised * 2.2, 0.0, 1.0) * 235).astype(np.uint8)

    # A PNG carries no CRS by design; rasterio warns about that, which is noise here.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with MemoryFile() as memfile:
            with memfile.open(
                driver="PNG", height=height, width=width, count=4, dtype="uint8"
            ) as dataset:
                dataset.write(rgba)
            return bytes(memfile.read())


def raster_bounds_geojson(bounds: tuple[float, float, float, float]) -> dict[str, Any]:
    min_x, min_y, max_x, max_y = bounds
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min_x, min_y],
                [max_x, min_y],
                [max_x, max_y],
                [min_x, max_y],
                [min_x, min_y],
            ]
        ],
    }


__all__ = ["WGS84", "array_to_png", "raster_bounds_geojson", "read_geotiff", "write_geotiff"]
