"""Overlap-blended reassembly of per-tile predictions.

Averaging overlapping tiles with equal weight leaves a visible grid: a tile's prediction
is least reliable at its own border, where the receptive field ran out of context, and
those unreliable borders are exactly what a plain average keeps.  Weighting each tile by
a raised-cosine window pushes the influence to tile centres, and the seams disappear.

The window is ``sin²(π(i+½)/n)``, which is the usual raised cosine shifted by half a
pixel.  The shift matters: an unshifted Hann window is **zero** at the first and last
pixel, so a raster edge — covered by exactly one tile — would have zero total weight and
divide by zero.  This form is strictly positive everywhere, so every pixel is defined.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from spilltrace.ml.tiling import TileWindow

#: Below this the accumulated weight is numerically meaningless; treat as uncovered.
MIN_WEIGHT = 1e-8


def cosine_window(height: int, width: int) -> np.ndarray:
    """A separable raised-cosine blending window, strictly positive on every pixel."""
    if height <= 0 or width <= 0:
        raise ValueError("Window dimensions must be positive.")
    rows = np.sin(np.pi * (np.arange(height) + 0.5) / height) ** 2
    cols = np.sin(np.pi * (np.arange(width) + 0.5) / width) ** 2
    return np.outer(rows, cols).astype(np.float32)


def stitch_tiles(
    tiles: np.ndarray,
    windows: Sequence[TileWindow],
    *,
    shape: tuple[int, int],
    blend: bool = True,
    fill_value: float = 0.0,
) -> np.ndarray:
    """Blend ``(N, h, w)`` tile predictions back into one ``(H, W)`` raster."""
    stack = np.asarray(tiles, dtype=np.float32)
    if stack.ndim == 4 and stack.shape[1] == 1:
        stack = stack[:, 0]
    if stack.ndim != 3:
        raise ValueError(f"Expected tiles shaped (N, h, w), got {stack.shape}.")
    if len(windows) != stack.shape[0]:
        raise ValueError(
            f"Got {stack.shape[0]} tiles but {len(windows)} windows; they must correspond."
        )

    height, width = shape
    accumulator = np.zeros((height, width), dtype=np.float64)
    weights = np.zeros((height, width), dtype=np.float64)
    cache: dict[tuple[int, int], np.ndarray] = {}

    for tile, window in zip(stack, windows, strict=True):
        rows = slice(window.row_off, min(window.row_off + window.height, height))
        cols = slice(window.col_off, min(window.col_off + window.width, width))
        crop = tile[: rows.stop - rows.start, : cols.stop - cols.start]
        if crop.size == 0:
            continue
        if blend:
            key = (crop.shape[0], crop.shape[1])
            if key not in cache:
                cache[key] = cosine_window(*key)
            weight = cache[key]
        else:
            weight = np.ones(crop.shape, dtype=np.float32)
        accumulator[rows, cols] += crop * weight
        weights[rows, cols] += weight

    covered = weights > MIN_WEIGHT
    output = np.full((height, width), fill_value, dtype=np.float32)
    output[covered] = (accumulator[covered] / weights[covered]).astype(np.float32)
    return output


def coverage_map(windows: Sequence[TileWindow], *, shape: tuple[int, int]) -> np.ndarray:
    """How many tiles cover each pixel — a cheap check that tiling left no holes."""
    height, width = shape
    counts = np.zeros((height, width), dtype=np.int32)
    for window in windows:
        rows = slice(window.row_off, min(window.row_off + window.height, height))
        cols = slice(window.col_off, min(window.col_off + window.width, width))
        counts[rows, cols] += 1
    return counts


__all__ = ["MIN_WEIGHT", "cosine_window", "coverage_map", "stitch_tiles"]
