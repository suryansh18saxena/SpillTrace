"""SAR preprocessing: dB conversion, per-scene clipping, standardisation, masking.

The properties tested here are the ones AD-12 and ML_PIPELINE §2 make claims about:
the clip bounds are *measured per scene* and recoverable from the manifest, no-data
never enters a statistic, and a missing polarisation is recorded rather than hidden.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from spilltrace.ml.preprocess import (
    CHANNEL_ORDER,
    DEFAULT_CLIP_PERCENTILES,
    clip_and_standardise,
    percentile_clip_bounds,
    preprocess_bands,
    read_sigma0_band,
    sigma0_to_db,
)

RNG = np.random.default_rng(20260910)


def _sea(shape: tuple[int, int] = (64, 64), level: float = 0.05) -> np.ndarray:
    """Gamma-speckled sea at a given σ0, as a GRD band actually looks."""
    return (level * RNG.gamma(shape=4.4, scale=1 / 4.4, size=shape)).astype(np.float32)


# --------------------------------------------------------------------------- dB
def test_sigma0_to_db_is_ten_log_ten() -> None:
    values = np.array([[1.0, 0.1, 0.01]], dtype=np.float32)
    db, valid = sigma0_to_db(values, nodata=None)
    assert valid.all()
    assert db[0, 0] == pytest.approx(0.0, abs=1e-5)
    assert db[0, 1] == pytest.approx(-10.0, abs=1e-4)
    assert db[0, 2] == pytest.approx(-20.0, abs=1e-4)


def test_zero_and_negative_sigma0_are_invalid_not_minus_infinity() -> None:
    values = np.array([[0.0, -1.0, 1e-12, 0.05]], dtype=np.float32)
    db, valid = sigma0_to_db(values)
    assert valid.tolist() == [[False, False, False, True]]
    # nan, not -inf: an infinity would poison every later mean.
    assert np.isnan(db[0, :3]).all()
    assert np.isfinite(db[0, 3])


def test_nodata_pixels_are_excluded_from_the_percentile() -> None:
    """A GRD's zero-fill border is a huge dark region; letting it in moves the bound."""
    band = _sea()
    band[:, :16] = 0.0  # fill border
    db, valid = sigma0_to_db(band)
    low, high = percentile_clip_bounds(db, valid)

    all_pixels = np.where(valid, db, -60.0)
    low_polluted = float(np.percentile(all_pixels, DEFAULT_CLIP_PERCENTILES[0]))
    assert low > low_polluted + 10.0
    assert low < high


# --------------------------------------------------------------------------- clipping
def test_clip_bounds_are_the_measured_percentiles() -> None:
    band = _sea()
    db, valid = sigma0_to_db(band)
    low, high = percentile_clip_bounds(db, valid, percentiles=(1.0, 99.0))
    sample = db[valid]
    assert low == pytest.approx(float(np.percentile(sample, 1.0)), abs=1e-4)
    assert high == pytest.approx(float(np.percentile(sample, 99.0)), abs=1e-4)


def test_standardised_band_has_zero_mean_unit_std_over_valid_pixels() -> None:
    db, valid = sigma0_to_db(_sea())
    standardised, stats = clip_and_standardise(db, valid, polarization="VV")
    assert standardised.dtype == np.float32
    assert float(standardised[valid].mean()) == pytest.approx(0.0, abs=1e-4)
    assert float(standardised[valid].std()) == pytest.approx(1.0, abs=1e-3)
    assert stats.clip_low_db < stats.mean_db < stats.clip_high_db


def test_statistics_round_trip_back_to_clipped_db() -> None:
    """AD-12 asks for an *invertible* transform, so the inverse is tested."""
    db, valid = sigma0_to_db(_sea())
    standardised, stats = clip_and_standardise(db, valid, polarization="VV")
    recovered = stats.invert(standardised)
    expected = np.clip(db, stats.clip_low_db, stats.clip_high_db)
    assert np.allclose(recovered[valid], expected[valid], atol=1e-3)


def test_degenerate_constant_band_does_not_explode() -> None:
    constant = np.full((32, 32), 0.05, dtype=np.float32)
    db, valid = sigma0_to_db(constant)
    standardised, stats = clip_and_standardise(db, valid, polarization="VV")
    assert np.isfinite(standardised).all()
    assert stats.std_db == 1.0


def test_all_invalid_band_yields_a_total_transform() -> None:
    empty = np.zeros((16, 16), dtype=np.float32)
    db, valid = sigma0_to_db(empty)
    assert not valid.any()
    standardised, stats = clip_and_standardise(db, valid, polarization="VV")
    assert np.isfinite(standardised).all()
    assert stats.valid_fraction == 0.0


def test_rejects_impossible_percentiles() -> None:
    db, valid = sigma0_to_db(_sea())
    with pytest.raises(ValueError, match="Clip percentiles"):
        percentile_clip_bounds(db, valid, percentiles=(99.0, 1.0))


# --------------------------------------------------------------------------- stacking
def test_dual_pol_stack_has_channels_in_the_declared_order() -> None:
    scene = preprocess_bands({"VV": _sea(level=0.05), "VH": _sea(level=0.006)})
    assert scene.bands == CHANNEL_ORDER
    assert scene.array.shape == (2, 64, 64)
    assert scene.array.dtype == np.float32
    # VH sits ~9 dB below VV; the *recorded* means must preserve that ordering even
    # though standardisation removes it from the arrays.
    vv, vh = scene.statistics
    assert vv.mean_db > vh.mean_db + 5.0


def test_missing_vh_duplicates_vv_and_says_so() -> None:
    scene = preprocess_bands({"VV": _sea()})
    assert scene.array.shape[0] == 2
    assert np.array_equal(scene.array[0], scene.array[1])
    assert scene.notes == ("VH unavailable; VV duplicated",)
    assert scene.statistics[1].source == "duplicated from VV"
    assert scene.to_manifest()["notes"] == ["VH unavailable; VV duplicated"]


def test_manifest_records_the_clip_bounds_that_were_used() -> None:
    scene = preprocess_bands({"VV": _sea(), "VH": _sea(level=0.006)})
    manifest = scene.to_manifest()
    assert manifest["normalisation"]["reference"] == "docs/DECISIONS.md AD-12"
    for band in manifest["normalisation"]["bands"]:
        assert band["percentiles"] == [1.0, 99.0]
        assert band["clip_low_db"] < band["clip_high_db"]
        assert math.isfinite(band["mean_db"]) and band["std_db"] > 0


def test_valid_mask_is_the_intersection_across_channels() -> None:
    vv = _sea()
    vh = _sea(level=0.006)
    vv[0, :] = 0.0
    vh[:, 0] = 0.0
    scene = preprocess_bands({"VV": vv, "VH": vh})
    assert not scene.valid_mask[0, :].any()
    assert not scene.valid_mask[:, 0].any()
    assert scene.valid_mask[1:, 1:].all()


def test_mismatched_band_shapes_are_rejected() -> None:
    with pytest.raises(ValueError, match="one shape"):
        preprocess_bands({"VV": _sea((32, 32)), "VH": _sea((16, 16))})


def test_empty_band_mapping_is_rejected() -> None:
    with pytest.raises(ValueError, match="At least one polarisation"):
        preprocess_bands({})


# --------------------------------------------------------------------------- raster IO
def test_read_sigma0_band_decimates_large_rasters() -> None:
    from spilltrace.core.raster import write_geotiff

    payload = write_geotiff(_sea((512, 512)), bounds=(68.0, 21.0, 70.0, 23.0), dtype="float32")
    array, bounds, meta = read_sigma0_band(payload, max_dimension=128)
    assert meta["decimation"] == 4
    assert array.shape == (128, 128)
    assert meta["georeferenced"] is True
    assert bounds == pytest.approx((68.0, 21.0, 70.0, 23.0))


def test_read_sigma0_band_leaves_small_rasters_alone() -> None:
    from spilltrace.core.raster import write_geotiff

    payload = write_geotiff(_sea((64, 64)), bounds=(68.0, 21.0, 70.0, 23.0), dtype="float32")
    array, _, meta = read_sigma0_band(payload, max_dimension=4096)
    assert meta["decimation"] == 1
    assert array.shape == (64, 64)
