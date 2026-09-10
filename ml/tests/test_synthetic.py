"""The offline dataset generator: deterministic, dB-valued, and honestly hard."""

from __future__ import annotations

import json

import numpy as np

from dataset.synthetic import (
    DATA_PROVENANCE,
    dataset_fingerprint,
    generate_dataset,
    generate_sample,
    write_dataset,
)


def test_samples_are_two_channel_db_with_a_binary_mask() -> None:
    sample = generate_sample(0, size=128, seed=1, kind="oil")
    assert sample.image.shape == (2, 128, 128)
    assert sample.image.dtype == np.float32
    assert sample.mask.shape == (128, 128)
    assert set(np.unique(sample.mask)) <= {0, 1}
    # σ0 in dB over water is negative; that is how the loader recognises the units.
    assert float(np.median(sample.image)) < 0.0


def test_the_generator_is_deterministic() -> None:
    first = generate_sample(3, size=96, seed=5)
    second = generate_sample(3, size=96, seed=5)
    assert np.array_equal(first.image, second.image)
    assert np.array_equal(first.mask, second.mask)
    assert not np.array_equal(first.image, generate_sample(3, size=96, seed=6).image)


def test_oil_samples_have_a_mask_and_a_measurable_contrast() -> None:
    sample = generate_sample(0, size=192, seed=2, kind="oil")
    assert sample.oil_fraction > 0.0
    inside = sample.image[0][sample.mask == 1].mean()
    outside = sample.image[0][sample.mask == 0].mean()
    # Oil damps Bragg scattering by roughly 10 dB.
    assert outside - inside > 5.0


def test_lookalikes_are_dark_but_carry_an_empty_mask() -> None:
    """Without this class a model passes by learning 'dark means oil'."""
    sample = generate_sample(1, size=192, seed=2, kind="lookalike")
    assert sample.oil_fraction == 0.0
    assert float(np.percentile(sample.image[0], 5)) < float(np.median(sample.image[0]))


def test_clean_samples_are_empty() -> None:
    sample = generate_sample(2, size=96, seed=2, kind="clean")
    assert sample.mask.sum() == 0


def test_a_dataset_cycles_through_all_three_kinds() -> None:
    samples = generate_dataset(9, size=64, seed=3)
    assert {s.kind for s in samples} == {"oil", "lookalike", "clean"}
    assert len({s.index for s in samples}) == 9


def test_cross_pol_sits_below_co_pol() -> None:
    sample = generate_sample(0, size=128, seed=4, kind="clean")
    assert float(np.median(sample.image[1])) < float(np.median(sample.image[0])) - 5.0


def test_the_fingerprint_pins_the_content() -> None:
    a = generate_dataset(4, size=64, seed=1)
    b = generate_dataset(4, size=64, seed=1)
    c = generate_dataset(4, size=64, seed=2)
    assert dataset_fingerprint(a) == dataset_fingerprint(b)
    assert dataset_fingerprint(a) != dataset_fingerprint(c)


def test_written_files_match_the_published_layout(tmp_path) -> None:
    import rasterio

    samples = generate_dataset(3, size=64, seed=1)
    manifest_path = write_dataset(tmp_path, samples)
    manifest = json.loads(manifest_path.read_text())
    assert manifest["data_provenance"] == DATA_PROVENANCE
    assert len(manifest["samples"]) == 3

    with rasterio.open(tmp_path / "0000.tif") as dataset:
        assert dataset.count == 2
        assert dataset.dtypes[0] == "float32"
    with rasterio.open(tmp_path / "0000_segmentation.tif") as dataset:
        assert dataset.count == 1
        assert dataset.dtypes[0] == "uint8"


def test_every_sample_declares_itself_synthetic() -> None:
    for sample in generate_dataset(3, size=64, seed=1):
        assert sample.to_metadata()["data_provenance"] == "SYNTHETIC"
