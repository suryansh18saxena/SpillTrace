"""Threshold, hysteresis, morphology and the minimum-area filter.

Each of these can delete a real detection, so each is tested for the specific failure it
is meant to prevent — and the configuration that produced a mask is asserted to be
recoverable from the result.
"""

from __future__ import annotations

import numpy as np
import pytest

from spilltrace.core.masking import (
    DEFAULT_HYSTERESIS_LOW,
    DEFAULT_THRESHOLD,
    MaskConfig,
    build_mask,
    disk,
    filter_small_components,
    hysteresis_threshold,
    morphological_clean,
)


def _tapering_trail() -> np.ndarray:
    """A slick that is confident at one end and fades at the other — the hard case."""
    grid = np.zeros((40, 60), dtype=np.float32)
    grid[19:22, 5:30] = 0.9
    grid[20, 30:52] = np.linspace(0.85, 0.38, 22, dtype=np.float32)
    return grid


# --------------------------------------------------------------------------- hysteresis
def test_hysteresis_keeps_a_weak_tail_attached_to_a_confident_head() -> None:
    grid = _tapering_trail()
    plain = grid >= 0.5
    hysteretic = hysteresis_threshold(grid, high=0.5, low=0.35)
    assert hysteretic.sum() > plain.sum()
    # The tail's far end is below 0.5 but connected, so it survives.
    assert hysteretic[20, 51]
    assert not plain[20, 51]


def test_hysteresis_drops_weak_regions_with_no_confident_pixel() -> None:
    grid = np.zeros((20, 20), dtype=np.float32)
    grid[2:5, 2:5] = 0.42  # weak and isolated
    grid[12:16, 12:16] = 0.8  # confident
    mask = hysteresis_threshold(grid, high=0.5, low=0.35)
    assert not mask[2:5, 2:5].any()
    assert mask[12:16, 12:16].all()


def test_hysteresis_with_no_confident_pixel_returns_nothing() -> None:
    grid = np.full((10, 10), 0.4, dtype=np.float32)
    assert not hysteresis_threshold(grid, high=0.5, low=0.35).any()


def test_hysteresis_uses_eight_connectivity() -> None:
    """A one-pixel trail that steps diagonally is one slick, not a string of fragments."""
    grid = np.zeros((10, 10), dtype=np.float32)
    for i in range(6):
        grid[i + 1, i + 1] = 0.4
    grid[1, 1] = 0.9
    mask = hysteresis_threshold(grid, high=0.5, low=0.35)
    assert mask.sum() == 6


# --------------------------------------------------------------------------- morphology
def test_opening_removes_isolated_speckle() -> None:
    mask = np.zeros((30, 30), dtype=bool)
    mask[5, 5] = True
    mask[10:20, 10:20] = True
    cleaned = morphological_clean(mask, opening_radius=1, closing_radius=0, fill_holes=False)
    assert not cleaned[5, 5]
    assert cleaned[15, 15]


def test_closing_bridges_a_one_pixel_break() -> None:
    mask = np.zeros((20, 30), dtype=bool)
    mask[9:12, 2:14] = True
    mask[9:12, 15:28] = True
    cleaned = morphological_clean(mask, opening_radius=0, closing_radius=2, fill_holes=False)
    assert cleaned[10, 14]


def test_fill_holes_closes_an_interior_gap() -> None:
    mask = np.zeros((20, 20), dtype=bool)
    mask[4:16, 4:16] = True
    mask[9:11, 9:11] = False
    assert morphological_clean(mask, opening_radius=0, closing_radius=0)[9, 9]


def test_zero_radius_morphology_is_a_no_op() -> None:
    mask = np.zeros((10, 10), dtype=bool)
    mask[5, 5] = True
    cleaned = morphological_clean(mask, opening_radius=0, closing_radius=0, fill_holes=False)
    assert np.array_equal(cleaned, mask)


def test_disk_is_a_disk() -> None:
    assert disk(0).shape == (1, 1)
    element = disk(2)
    assert element.shape == (5, 5)
    assert element[2, 2] and element[0, 2] and not element[0, 0]


# --------------------------------------------------------------------------- area filter
def test_min_area_filter_drops_small_components_and_relabels() -> None:
    mask = np.zeros((40, 40), dtype=bool)
    mask[2:4, 2:4] = True  # 4 px
    mask[10:20, 10:20] = True  # 100 px
    filtered, labels, count = filter_small_components(mask, min_area_px=64)
    assert count == 1
    assert not filtered[2:4, 2:4].any()
    assert labels.max() == 1


def test_min_area_filter_on_an_empty_mask_is_empty() -> None:
    filtered, labels, count = filter_small_components(np.zeros((8, 8), dtype=bool), min_area_px=10)
    assert count == 0
    assert not filtered.any()
    assert labels.max() == 0


# --------------------------------------------------------------------------- pipeline
def test_build_mask_reports_what_each_stage_removed() -> None:
    grid = _tapering_trail()
    result = build_mask(grid, MaskConfig(min_area_px=8))
    assert result.pixel_count > 0
    assert result.component_count == 1
    stages = result.stages
    assert stages["after_hysteresis"] >= stages["above_threshold"]
    assert stages["after_min_area"] == result.pixel_count
    assert result.to_dict()["config"]["threshold"] == DEFAULT_THRESHOLD
    assert result.to_dict()["config"]["hysteresis_low"] == DEFAULT_HYSTERESIS_LOW
    assert result.to_dict()["config"]["connectivity"] == 8


def test_build_mask_honours_the_valid_mask() -> None:
    grid = np.full((40, 40), 0.9, dtype=np.float32)
    valid = np.zeros((40, 40), dtype=bool)
    valid[10:25, 10:25] = True
    result = build_mask(grid, MaskConfig(min_area_px=1), valid_mask=valid)
    assert result.pixel_count > 0
    # Nothing outside the valid footprint may be detected, whatever the probability was.
    assert not result.mask[~valid].any()
    assert result.pixel_count >= 0.8 * int(valid.sum())


def test_closing_does_not_erode_a_slick_that_reaches_the_raster_edge() -> None:
    """A slick crossing the swath edge is already truncated; do not shave it further."""
    grid = np.zeros((40, 40), dtype=np.float32)
    grid[:, :12] = 0.9
    result = build_mask(grid, MaskConfig(min_area_px=1))
    assert result.mask[0, 0]
    assert result.mask[-1, 0]


def test_an_all_zero_probability_map_yields_an_empty_mask() -> None:
    result = build_mask(np.zeros((32, 32), dtype=np.float32))
    assert result.pixel_count == 0
    assert result.component_count == 0
    assert result.labels.max() == 0


def test_config_rejects_a_floor_above_the_threshold() -> None:
    with pytest.raises(ValueError, match="hysteresis_low"):
        MaskConfig(threshold=0.4, hysteresis_low=0.6)


def test_config_rejects_negative_morphology() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        MaskConfig(opening_radius_px=-1)


def test_masking_is_deterministic() -> None:
    grid = _tapering_trail()
    first = build_mask(grid, MaskConfig(min_area_px=8))
    second = build_mask(grid, MaskConfig(min_area_px=8))
    assert np.array_equal(first.mask, second.mask)
    assert first.stages == second.stages
