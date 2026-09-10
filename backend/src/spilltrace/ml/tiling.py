"""Tiling with overlap, carrying each tile's own affine transform.

A 25 000 × 16 000 GRD does not fit in a CPU forward pass, so inference runs on tiles.
Two properties matter:

* **Overlap.** Tiles are cut at ``stride < tile_size`` so every interior pixel is seen by
  more than one tile and the seams can be blended away (see :mod:`spilltrace.ml.stitch`).
* **Each tile keeps its transform.** Georeferencing a prediction by re-deriving the
  affine from the tile index is the kind of arithmetic that is wrong once and then wrong
  everywhere; the transform travels with the tile instead.

Edge tiles are flushed against the right/bottom edge rather than zero-padded — padding a
GRD edge with zeros invents a very dark region, which is exactly what a dark-region
detector is looking for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

#: AD-11: 128² at stride 96 on CPU; 256² is roughly four times the compute.
DEFAULT_TILE_SIZE = 128
DEFAULT_STRIDE = 96

#: The identity affine, in rasterio's ``(a, b, c, d, e, f)`` order.
IDENTITY_TRANSFORM: tuple[float, float, float, float, float, float] = (
    1.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
)


@dataclass(frozen=True, slots=True)
class TileWindow:
    """Where a tile sits in the parent raster, and how it maps to the world."""

    index: int
    row_off: int
    col_off: int
    height: int
    width: int
    transform: tuple[float, float, float, float, float, float] = IDENTITY_TRANSFORM

    @property
    def row_slice(self) -> slice:
        return slice(self.row_off, self.row_off + self.height)

    @property
    def col_slice(self) -> slice:
        return slice(self.col_off, self.col_off + self.width)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "row_off": self.row_off,
            "col_off": self.col_off,
            "height": self.height,
            "width": self.width,
            "transform": list(self.transform),
        }


def tile_offsets(length: int, tile_size: int, stride: int) -> list[int]:
    """Start offsets along one axis, with the final tile flush against the edge."""
    if tile_size <= 0 or stride <= 0:
        raise ValueError("tile_size and stride must both be positive.")
    if length <= tile_size:
        return [0]
    offsets = list(range(0, length - tile_size + 1, stride))
    last = length - tile_size
    if offsets[-1] != last:
        offsets.append(last)
    return offsets


def child_transform(
    parent: tuple[float, float, float, float, float, float], row_off: int, col_off: int
) -> tuple[float, float, float, float, float, float]:
    """Translate an affine transform to a tile's origin."""
    a, b, c, d, e, f = parent
    return (a, b, c + a * col_off + b * row_off, d, e, f + d * col_off + e * row_off)


def tile_windows(
    height: int,
    width: int,
    *,
    tile_size: int = DEFAULT_TILE_SIZE,
    stride: int = DEFAULT_STRIDE,
    transform: tuple[float, float, float, float, float, float] = IDENTITY_TRANSFORM,
) -> list[TileWindow]:
    if stride > tile_size:
        raise ValueError(
            f"stride {stride} exceeds tile_size {tile_size}, which would leave gaps between tiles."
        )
    rows = tile_offsets(height, tile_size, stride)
    cols = tile_offsets(width, tile_size, stride)
    windows: list[TileWindow] = []
    index = 0
    for row_off in rows:
        for col_off in cols:
            windows.append(
                TileWindow(
                    index=index,
                    row_off=row_off,
                    col_off=col_off,
                    height=min(tile_size, height),
                    width=min(tile_size, width),
                    transform=child_transform(transform, row_off, col_off),
                )
            )
            index += 1
    return windows


def pad_to_tile(array: np.ndarray, tile_size: int) -> np.ndarray:
    """Grow a raster smaller than one tile by edge replication.

    Replication, not zero fill: an artificial dark border would be indistinguishable
    from a real damped surface to anything that looks for dark regions.
    """
    *lead, height, width = array.shape
    pad_rows = max(0, tile_size - height)
    pad_cols = max(0, tile_size - width)
    if not pad_rows and not pad_cols:
        return array
    pad_width = [(0, 0)] * len(lead) + [(0, pad_rows), (0, pad_cols)]
    return np.pad(array, pad_width, mode="edge")


def tile_array(
    array: np.ndarray,
    *,
    tile_size: int = DEFAULT_TILE_SIZE,
    stride: int = DEFAULT_STRIDE,
    transform: tuple[float, float, float, float, float, float] = IDENTITY_TRANSFORM,
) -> tuple[np.ndarray, list[TileWindow]]:
    """Cut ``(C, H, W)`` (or ``(H, W)``) into ``(N, C, tile, tile)`` plus its windows."""
    stack = array[np.newaxis, ...] if array.ndim == 2 else array
    if stack.ndim != 3:
        raise ValueError(f"Expected a 2-D or 3-D array, got {array.ndim} dimensions.")

    padded = pad_to_tile(stack, tile_size)
    _, height, width = padded.shape
    windows = tile_windows(height, width, tile_size=tile_size, stride=stride, transform=transform)
    tiles = np.stack([padded[:, window.row_slice, window.col_slice] for window in windows]).astype(
        np.float32
    )
    return tiles, windows


def tiled_shape(height: int, width: int, *, tile_size: int = DEFAULT_TILE_SIZE) -> tuple[int, int]:
    """The shape tiling actually operates on, after any edge padding."""
    return max(height, tile_size), max(width, tile_size)


__all__ = [
    "DEFAULT_STRIDE",
    "DEFAULT_TILE_SIZE",
    "IDENTITY_TRANSFORM",
    "TileWindow",
    "child_transform",
    "pad_to_tile",
    "tile_array",
    "tile_offsets",
    "tile_windows",
    "tiled_shape",
]
