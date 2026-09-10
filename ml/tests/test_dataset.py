"""Loading, validation, splitting, tiling and augmentation — without PyTorch."""

from __future__ import annotations

import numpy as np
import pytest

from dataset.augment import AugmentConfig, augment, inject_speckle
from dataset.loader import discover_pairs, load_synthetic_pairs, normalise_db_image
from dataset.splits import load_splits, make_splits, resolve_splits, save_splits
from dataset.synthetic import generate_dataset, write_dataset
from dataset.tiles import build_tileset, tile_pair
from dataset.validate import (
    DatasetValidationError,
    probe_raster,
    report_band_order,
    validate_image,
    validate_mask,
)


# --------------------------------------------------------------------------- validate
def test_probe_reports_what_is_actually_in_the_file(tmp_path) -> None:
    write_dataset(tmp_path, generate_dataset(1, size=64, seed=1))
    probe = probe_raster(tmp_path / "0000.tif")
    assert probe.band_count == 2
    assert probe.dtype == "float32"
    assert probe.looks_like_db is True
    assert probe.to_dict()["shape"] == [64, 64]


def test_validation_fails_loudly_on_a_dtype_mismatch(tmp_path) -> None:
    write_dataset(tmp_path, generate_dataset(1, size=64, seed=1))
    with pytest.raises(DatasetValidationError, match="expected dtype uint16"):
        validate_image(tmp_path / "0000.tif", expected_dtype="uint16")


def test_validation_fails_loudly_on_a_band_count_mismatch(tmp_path) -> None:
    write_dataset(tmp_path, generate_dataset(1, size=64, seed=1))
    with pytest.raises(DatasetValidationError, match="expected 3 bands, found 2"):
        validate_image(tmp_path / "0000.tif", expected_bands=3)


def test_linear_sigma0_is_caught_rather_than_trained_on(tmp_path) -> None:
    """AD-09 leaves the units unstated; silently training on linear σ0 would be a bug."""
    import rasterio

    path = tmp_path / "linear.tif"
    with rasterio.open(
        str(path), "w", driver="GTiff", height=32, width=32, count=2, dtype="float32"
    ) as dataset:
        dataset.write(np.full((2, 32, 32), 0.05, dtype=np.float32))
    with pytest.raises(DatasetValidationError, match="do not look like dB"):
        validate_image(path)


def test_masks_must_be_single_band_and_binary(tmp_path) -> None:
    write_dataset(tmp_path, generate_dataset(1, size=64, seed=1))
    probe = validate_mask(tmp_path / "0000_segmentation.tif")
    assert probe.band_count == 1
    with pytest.raises(DatasetValidationError, match="expected 1 band"):
        validate_mask(tmp_path / "0000.tif")


def test_band_order_is_recorded_as_an_assumption(tmp_path) -> None:
    write_dataset(tmp_path, generate_dataset(1, size=64, seed=1))
    report = report_band_order(probe_raster(tmp_path / "0000.tif"), ("VV", "VH"))
    assert report["assumed_band_order"] == ["VV", "VH"]
    assert report["confirmed_by_file"] is False
    assert "assumption" in report["note"]


# --------------------------------------------------------------------------- loader
def test_pairs_are_discovered_in_the_published_layout(tmp_path) -> None:
    write_dataset(tmp_path, generate_dataset(3, size=64, seed=1))
    pairs = discover_pairs(tmp_path)
    assert len(pairs) == 3
    assert all(mask.name.endswith("_segmentation.tif") for _, _, mask in pairs)


def test_pairs_are_discovered_in_the_images_masks_layout(tmp_path) -> None:
    import rasterio

    (tmp_path / "images").mkdir()
    (tmp_path / "masks").mkdir()
    for directory, count in (("images", 2), ("masks", 1)):
        with rasterio.open(
            str(tmp_path / directory / "a.tif"),
            "w",
            driver="GTiff",
            height=8,
            width=8,
            count=count,
            dtype="float32",
        ) as dataset:
            dataset.write(np.zeros((count, 8, 8), dtype=np.float32))
    assert [name for name, _, _ in discover_pairs(tmp_path)] == ["a"]


def test_a_missing_directory_is_an_error(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_pairs(tmp_path / "nope")


def test_normalisation_matches_what_inference_will_do() -> None:
    rng = np.random.default_rng(0)
    image_db = rng.normal(-15.0, 3.0, size=(2, 64, 64)).astype(np.float32)
    normalised, statistics = normalise_db_image(image_db)
    assert normalised.shape == (2, 64, 64)
    assert float(normalised[0].mean()) == pytest.approx(0.0, abs=1e-4)
    assert float(normalised[0].std()) == pytest.approx(1.0, abs=1e-2)
    assert statistics[0]["percentiles"] == [1.0, 99.0]


def test_synthetic_pairs_load_normalised_and_named() -> None:
    pairs = load_synthetic_pairs(3, size=64, seed=1)
    assert len(pairs) == 3
    assert all(pair.name.startswith("synthetic-") for pair in pairs)
    assert pairs[0].image.shape == (2, 64, 64)
    assert set(np.unique(pairs[0].mask)) <= {0.0, 1.0}


# --------------------------------------------------------------------------- splits
def test_splits_are_disjoint_and_cover_everything() -> None:
    members = [f"image-{i:03d}" for i in range(40)]
    splits = make_splits(members, seed=1)
    combined = set(splits.train) | set(splits.val) | set(splits.test)
    assert combined == set(members)
    assert not set(splits.train) & set(splits.val)
    assert not set(splits.train) & set(splits.test)
    assert not set(splits.val) & set(splits.test)


def test_splits_are_reproducible_and_hashed() -> None:
    members = [f"image-{i:03d}" for i in range(40)]
    assert make_splits(members, seed=1).hash == make_splits(members, seed=1).hash
    assert make_splits(members, seed=1).hash != make_splits(members, seed=2).hash


def test_splits_are_made_at_image_level_not_tile_level() -> None:
    """P10-006: tiles from one image share speckle and slick; a tile split leaks."""
    splits = make_splits([f"image-{i:03d}" for i in range(30)], seed=3)
    assert splits.to_dict()["level"] == "image"
    assert "not the split used by the dataset's authors" in splits.to_dict()["note"]


def test_saved_splits_are_reused_rather_than_regenerated(tmp_path) -> None:
    members = [f"image-{i:03d}" for i in range(20)]
    first = resolve_splits(tmp_path, members, seed=1)
    second = resolve_splits(tmp_path, members, seed=999)
    assert first.hash == second.hash
    assert load_splits(tmp_path) is not None


def test_regeneration_requires_an_explicit_flag(tmp_path) -> None:
    members = [f"image-{i:03d}" for i in range(20)]
    first = resolve_splits(tmp_path, members, seed=1)
    regenerated = resolve_splits(tmp_path, members, seed=999, regenerate=True)
    assert first.hash != regenerated.hash


def test_new_images_against_a_saved_split_raise_rather_than_leak(tmp_path) -> None:
    save_splits(tmp_path, make_splits([f"image-{i:03d}" for i in range(10)], seed=1))
    with pytest.raises(ValueError, match="not in the saved split"):
        resolve_splits(tmp_path, [f"image-{i:03d}" for i in range(12)])


def test_an_empty_dataset_cannot_be_split() -> None:
    with pytest.raises(ValueError, match="empty dataset"):
        make_splits([])


# --------------------------------------------------------------------------- tiling
def test_tiles_stay_aligned_between_image_and_mask() -> None:
    image = np.zeros((2, 200, 200), dtype=np.float32)
    mask = np.zeros((200, 200), dtype=np.float32)
    image[:, 50:80, 50:80] = 5.0
    mask[50:80, 50:80] = 1.0
    image_tiles, mask_tiles = tile_pair(image, mask, patch_size=64, stride=48)
    assert image_tiles.shape[0] == mask_tiles.shape[0]
    for image_tile, mask_tile in zip(image_tiles, mask_tiles, strict=True):
        assert bool((image_tile[0] > 0).any()) == bool((mask_tile > 0).any())


def test_empty_tiles_are_subsampled_to_the_configured_fraction() -> None:
    pairs = []
    for index in range(4):
        image = np.zeros((2, 128, 128), dtype=np.float32)
        mask = np.zeros((128, 128), dtype=np.float32)
        mask[10:20, 10:20] = 1.0
        pairs.append((f"image-{index}", image, mask))

    everything = build_tileset(pairs, patch_size=32, stride=32, empty_tile_fraction=None)
    subsampled = build_tileset(pairs, patch_size=32, stride=32, empty_tile_fraction=0.35, seed=1)

    assert len(subsampled) < len(everything)
    assert subsampled.positive_fraction > everything.positive_fraction
    # Every positive tile survives; only empty ones are dropped.
    assert int(subsampled.positive_flags.sum()) == int(everything.positive_flags.sum())
    assert subsampled.to_dict()["positive_fraction"] == pytest.approx(0.65, abs=0.1)


def test_subsampling_is_deterministic() -> None:
    pairs = [
        (
            "a",
            np.zeros((2, 128, 128), dtype=np.float32),
            np.pad(np.ones((10, 10), dtype=np.float32), ((10, 108), (10, 108))),
        )
    ]
    first = build_tileset(pairs, patch_size=32, stride=32, seed=5)
    second = build_tileset(pairs, patch_size=32, stride=32, seed=5)
    assert first.sources == second.sources
    assert np.array_equal(first.masks, second.masks)


def test_no_pairs_is_an_error() -> None:
    with pytest.raises(ValueError, match="No image/mask pairs"):
        build_tileset([])


# --------------------------------------------------------------------------- augment
def test_augmentation_moves_image_and_mask_together() -> None:
    """Geometry only: speckle is off here so the comparison is about position."""
    image = np.zeros((2, 16, 16), dtype=np.float32)
    mask = np.zeros((16, 16), dtype=np.float32)
    image[:, 2:5, 2:5] = 9.0
    mask[2:5, 2:5] = 1.0
    config = AugmentConfig(speckle_probability=0.0)
    for seed in range(8):
        rng = np.random.default_rng(seed)
        out_image, out_mask = augment(image, mask, rng=rng, config=config)
        assert np.array_equal((out_image[0] > 0), (out_mask > 0))
        assert out_image.shape == image.shape


def test_speckle_injection_does_not_move_the_geometry() -> None:
    image = np.full((2, 16, 16), -13.0, dtype=np.float32)
    image[:, 2:5, 2:5] = -25.0
    mask = np.zeros((16, 16), dtype=np.float32)
    mask[2:5, 2:5] = 1.0
    config = AugmentConfig(
        horizontal_flip=False, vertical_flip=False, rot90=False, speckle_probability=1.0
    )
    out_image, out_mask = augment(image, mask, rng=np.random.default_rng(0), config=config)
    assert np.array_equal(out_mask, mask)
    # The damped patch is still darker on average after a fresh speckle draw.
    assert out_image[0][mask == 1].mean() < out_image[0][mask == 0].mean()


def test_augmentation_is_reproducible_for_a_seed() -> None:
    image = np.random.default_rng(0).normal(size=(2, 16, 16)).astype(np.float32)
    mask = np.zeros((16, 16), dtype=np.float32)
    a = augment(image, mask, rng=np.random.default_rng(3))
    b = augment(image, mask, rng=np.random.default_rng(3))
    assert np.array_equal(a[0], b[0])


def test_no_photometric_jitter_is_configured() -> None:
    """AD-12: backscatter magnitude is the signal, not a nuisance variable."""
    described = AugmentConfig().to_dict()
    assert described["photometric_jitter"] is False
    assert "physical signal" in described["reason_no_photometric"]


def test_speckle_injection_preserves_the_mean_in_the_linear_domain() -> None:
    rng = np.random.default_rng(1)
    image_db = np.full((2, 256, 256), -13.0, dtype=np.float32)
    noisy = inject_speckle(image_db, rng=rng)
    linear_before = 10 ** (image_db / 10.0)
    linear_after = 10 ** (noisy / 10.0)
    assert float(linear_after.mean()) == pytest.approx(float(linear_before.mean()), rel=0.02)
    assert float(noisy.std()) > 0.0


def test_disabling_everything_is_a_no_op() -> None:
    image = np.ones((2, 8, 8), dtype=np.float32)
    mask = np.zeros((8, 8), dtype=np.float32)
    config = AugmentConfig(
        horizontal_flip=False, vertical_flip=False, rot90=False, speckle_probability=0.0
    )
    out_image, out_mask = augment(image, mask, rng=np.random.default_rng(0), config=config)
    assert np.array_equal(out_image, image)
    assert np.array_equal(out_mask, mask)
