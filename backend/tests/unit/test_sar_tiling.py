"""Tiling, per-tile transforms and cosine-blended stitching.

The seam test is the important one: overlap-blending exists so that tile boundaries do
not appear as detection edges, and a blend that is subtly wrong shows up as a grid in
the probability raster and then as spurious polygon edges in the evidence.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest
from rasterio.transform import from_bounds

from spilltrace.ml.stitch import cosine_window, coverage_map, stitch_tiles
from spilltrace.ml.tiling import (
    DEFAULT_STRIDE,
    DEFAULT_TILE_SIZE,
    child_transform,
    pad_to_tile,
    tile_array,
    tile_offsets,
    tile_windows,
)


# --------------------------------------------------------------------------- offsets
def test_offsets_cover_the_axis_and_end_flush() -> None:
    offsets = tile_offsets(500, 128, 96)
    assert offsets[0] == 0
    assert offsets[-1] == 500 - 128
    assert all(b - a == 96 for a, b in pairwise(offsets) if b != offsets[-1])
    assert len(set(offsets)) == len(offsets)


def test_axis_shorter_than_a_tile_yields_one_offset() -> None:
    assert tile_offsets(50, 128, 96) == [0]


def test_stride_larger_than_tile_is_rejected() -> None:
    with pytest.raises(ValueError, match="leave gaps"):
        tile_windows(256, 256, tile_size=64, stride=128)


# --------------------------------------------------------------------------- tiling
def test_tile_array_shapes_and_dtype() -> None:
    array = np.arange(2 * 300 * 260, dtype=np.float32).reshape(2, 300, 260)
    tiles, windows = tile_array(array, tile_size=128, stride=96)
    assert tiles.shape[1:] == (2, 128, 128)
    assert tiles.shape[0] == len(windows)
    assert tiles.dtype == np.float32


def test_two_dimensional_input_gains_a_channel_axis() -> None:
    tiles, _ = tile_array(np.zeros((200, 200), dtype=np.float32), tile_size=64, stride=48)
    assert tiles.shape[1] == 1


def test_every_pixel_is_covered_by_at_least_one_tile() -> None:
    windows = tile_windows(300, 260, tile_size=128, stride=96)
    counts = coverage_map(windows, shape=(300, 260))
    assert counts.min() >= 1
    # Overlap is the entire point; a stride equal to the tile size would give max == 1.
    assert counts.max() > 1


def test_tiles_carry_their_own_affine_transform() -> None:
    transform = from_bounds(68.0, 21.0, 70.0, 23.0, width=256, height=256)
    _, windows = tile_array(
        np.zeros((2, 256, 256), dtype=np.float32),
        tile_size=128,
        stride=128,
        transform=tuple(transform)[:6],
    )
    for window in windows:
        expected = transform * (window.col_off, window.row_off)
        assert window.transform[2] == pytest.approx(expected[0])
        assert window.transform[5] == pytest.approx(expected[1])
        # Pixel size never changes when a transform is translated.
        assert window.transform[0] == pytest.approx(transform.a)
        assert window.transform[4] == pytest.approx(transform.e)


def test_child_transform_is_a_pure_translation() -> None:
    parent = (0.01, 0.0, 68.0, 0.0, -0.01, 23.0)
    child = child_transform(parent, row_off=10, col_off=20)
    assert child[2] == pytest.approx(68.0 + 0.01 * 20)
    assert child[5] == pytest.approx(23.0 - 0.01 * 10)


def test_small_rasters_are_padded_by_edge_replication_not_zeros() -> None:
    """Zero padding would invent the darkest possible region at the raster edge."""
    array = np.full((1, 10, 10), 3.0, dtype=np.float32)
    padded = pad_to_tile(array, 32)
    assert padded.shape == (1, 32, 32)
    assert float(padded.min()) == 3.0


# --------------------------------------------------------------------------- blending
def test_cosine_window_is_strictly_positive_everywhere() -> None:
    """A plain Hann window is zero at the edge, which divides by zero at raster borders."""
    window = cosine_window(32, 32)
    assert window.min() > 0.0
    assert window.max() == pytest.approx(window[16, 16], rel=1e-6)


def test_stitching_a_constant_field_returns_the_constant() -> None:
    windows = tile_windows(300, 260, tile_size=128, stride=96)
    tiles = np.full((len(windows), 128, 128), 0.42, dtype=np.float32)
    stitched = stitch_tiles(tiles, windows, shape=(300, 260))
    assert np.allclose(stitched, 0.42, atol=1e-5)


def test_stitching_reconstructs_a_gradient_without_seams() -> None:
    height, width = 300, 260
    field = np.tile(np.linspace(0.0, 1.0, width, dtype=np.float32), (height, 1))
    tiles, windows = tile_array(field, tile_size=128, stride=96)
    stitched = stitch_tiles(tiles[:, 0], windows, shape=(height, width))
    assert np.allclose(stitched, field, atol=1e-5)

    # A seam would show as a spike in the column-to-column difference at tile edges.
    gradient = np.abs(np.diff(stitched, axis=1))
    assert float(gradient.max()) < 2.0 * float(np.median(gradient))


def test_stitch_rejects_a_window_count_mismatch() -> None:
    windows = tile_windows(128, 128, tile_size=64, stride=64)
    with pytest.raises(ValueError, match="must correspond"):
        stitch_tiles(np.zeros((2, 64, 64), dtype=np.float32), windows, shape=(128, 128))


def test_unblended_stitch_is_available_for_comparison() -> None:
    windows = tile_windows(200, 200, tile_size=128, stride=96)
    tiles = np.full((len(windows), 128, 128), 1.0, dtype=np.float32)
    plain = stitch_tiles(tiles, windows, shape=(200, 200), blend=False)
    assert np.allclose(plain, 1.0)


def test_defaults_match_the_documented_cpu_configuration() -> None:
    assert (DEFAULT_TILE_SIZE, DEFAULT_STRIDE) == (128, 96)
