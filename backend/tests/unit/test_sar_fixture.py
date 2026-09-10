"""The offline satellite fixture.

Its job is to make the *real* code path runnable without credentials, so what is tested
is that it is deterministic, that it is unmistakably labelled synthetic, and that what it
writes to disk is shaped exactly like a real per-band download.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from spilltrace.adapters.satellite.bundle import (
    SceneBand,
    SceneBundle,
    bundle_stored_object,
    read_bundle,
    write_bundle,
)
from spilltrace.adapters.satellite.fixture import (
    SEA_SIGMA0_VV,
    SLICK_SIGMA0_VV,
    FixtureCatalogue,
    synthetic_sigma0,
)
from spilltrace.core.enums import DataProvenance
from spilltrace.core.errors import ProviderError
from spilltrace.core.ports import SatelliteCatalogue, SceneRecord

AOI = {
    "type": "Polygon",
    "coordinates": [[[68.6, 21.9], [70.4, 21.9], [70.4, 23.1], [68.6, 23.1], [68.6, 21.9]]],
}
START = datetime(2026, 8, 13, tzinfo=UTC)
END = START + timedelta(days=3)


async def _search(catalogue: FixtureCatalogue | None = None) -> list[SceneRecord]:
    catalogue = catalogue or FixtureCatalogue(raster_size=128)
    return await catalogue.search(aoi_geojson=AOI, start=START, end=END)


def test_the_fixture_satisfies_the_port() -> None:
    assert isinstance(FixtureCatalogue(), SatelliteCatalogue)


async def test_search_is_deterministic_for_the_same_query() -> None:
    first = await _search()
    second = await _search()
    assert [r.product_id for r in first] == [r.product_id for r in second]
    assert [r.acquisition_time for r in first] == [r.acquisition_time for r in second]


async def test_a_different_window_gives_different_scenes() -> None:
    first = await _search()
    catalogue = FixtureCatalogue(raster_size=128)
    other = await catalogue.search(
        aoi_geojson=AOI, start=START + timedelta(days=10), end=END + timedelta(days=10)
    )
    assert {r.product_id for r in first}.isdisjoint({r.product_id for r in other})


async def test_every_record_is_labelled_synthetic() -> None:
    for record in await _search():
        assert record.data_provenance is DataProvenance.SYNTHETIC
        assert "SYNTHETIC" in record.product_id
        assert record.provider == "fixture"


async def test_acquisitions_fall_inside_the_requested_window() -> None:
    for record in await _search():
        assert START < record.acquisition_time < END


async def test_the_result_set_mixes_platforms_and_includes_a_single_pol_scene() -> None:
    """Both are real properties of CDSE result sets that break naive code."""
    records = await _search()
    assert {r.platform for r in records} == {"S1A", "S1C"}
    assert any(r.polarizations == ("VV",) for r in records)
    assert any(r.polarizations == ("VV", "VH") for r in records)


async def test_footprints_cover_the_area_of_interest() -> None:
    from shapely.geometry import shape

    aoi = shape(AOI)
    for record in await _search():
        assert shape(record.footprint_geojson).covers(aoi)


async def test_an_inverted_window_is_rejected() -> None:
    with pytest.raises(ProviderError, match="ends before"):
        await FixtureCatalogue().search(aoi_geojson=AOI, start=END, end=START)


async def test_an_empty_aoi_is_rejected() -> None:
    with pytest.raises(ProviderError, match="empty"):
        await FixtureCatalogue().search(
            aoi_geojson={"type": "Polygon", "coordinates": []}, start=START, end=END
        )


# --------------------------------------------------------------------------- download
async def test_download_writes_one_geotiff_per_polarisation(tmp_path: Path) -> None:
    from spilltrace.core.raster import read_geotiff

    catalogue = FixtureCatalogue(raster_size=128)
    record = (await _search(catalogue))[0]
    stored = await catalogue.download(record, destination=str(tmp_path))

    bundle = read_bundle(tmp_path)
    assert {band.polarization for band in bundle.bands} == {"VV", "VH"}
    assert bundle.data_provenance is DataProvenance.SYNTHETIC
    assert stored.checksum_sha256 == bundle.manifest_checksum()

    for band in bundle.bands:
        array, meta = read_geotiff((tmp_path / band.filename).read_bytes())
        assert array.shape == (1, 128, 128)
        assert meta["crs"] == "EPSG:4326"
        assert meta["tags"]["provenance"] == "SYNTHETIC"
        assert float(array.min()) > 0.0  # σ0 is a power, never zero or negative


async def test_download_is_byte_identical_on_a_repeat(tmp_path: Path) -> None:
    catalogue = FixtureCatalogue(raster_size=128)
    record = (await _search(catalogue))[0]
    first = await catalogue.download(record, destination=str(tmp_path / "a"))
    second = await catalogue.download(record, destination=str(tmp_path / "b"))
    assert first.checksum_sha256 == second.checksum_sha256


async def test_a_single_pol_scene_downloads_one_band_and_says_so(tmp_path: Path) -> None:
    catalogue = FixtureCatalogue(raster_size=128)
    record = next(r for r in await _search(catalogue) if r.polarizations == ("VV",))
    await catalogue.download(record, destination=str(tmp_path))
    bundle = read_bundle(tmp_path)
    assert [band.polarization for band in bundle.bands] == ["VV"]
    assert any("VV-only" in note for note in bundle.notes)


async def test_progress_is_reported_and_ends_at_one(tmp_path: Path) -> None:
    seen: list[tuple[float, str]] = []

    async def progress(*, fraction: float, message: str) -> None:
        seen.append((fraction, message))

    catalogue = FixtureCatalogue(raster_size=64)
    record = (await _search(catalogue))[0]
    await catalogue.download(record, destination=str(tmp_path), progress=progress)
    assert seen
    assert seen[-1][0] == 1.0
    assert all(0.0 <= fraction <= 1.0 for fraction, _ in seen)


# --------------------------------------------------------------------------- raster
def test_the_synthetic_scene_has_a_damped_region_well_below_the_sea() -> None:
    array = synthetic_sigma0(256, 256, seed=42)
    darkest_decile = float(np.percentile(array, 2))
    assert darkest_decile < SEA_SIGMA0_VV / 3
    assert float(np.median(array)) == pytest.approx(SEA_SIGMA0_VV, rel=0.4)
    assert array.min() > 0.0


def test_cross_pol_sits_below_co_pol() -> None:
    vv = synthetic_sigma0(128, 128, seed=42, polarization="VV")
    vh = synthetic_sigma0(128, 128, seed=42, polarization="VH")
    assert float(np.median(vh)) < float(np.median(vv)) / 4


def test_the_generator_is_reproducible() -> None:
    assert np.array_equal(synthetic_sigma0(64, 64, seed=7), synthetic_sigma0(64, 64, seed=7))
    assert not np.array_equal(synthetic_sigma0(64, 64, seed=7), synthetic_sigma0(64, 64, seed=8))


def test_a_slick_free_scene_can_be_generated() -> None:
    with_slick = synthetic_sigma0(256, 256, seed=3, with_slick=True)
    without = synthetic_sigma0(256, 256, seed=3, with_slick=False)
    assert float(np.percentile(with_slick, 2)) < float(np.percentile(without, 2))
    assert SLICK_SIGMA0_VV < SEA_SIGMA0_VV


# --------------------------------------------------------------------------- bundle
def test_the_bundle_checksum_is_order_independent(tmp_path: Path) -> None:
    bands = (
        SceneBand(polarization="VV", filename="a.tiff", size_bytes=10, checksum_sha256="aa"),
        SceneBand(polarization="VH", filename="b.tiff", size_bytes=20, checksum_sha256="bb"),
    )
    forward = SceneBundle(product_id="p", provider="fixture", bands=bands)
    reverse = SceneBundle(product_id="p", provider="fixture", bands=bands[::-1])
    assert forward.manifest_checksum() == reverse.manifest_checksum()
    assert forward.total_bytes == 30


def test_a_bundle_round_trips_through_disk(tmp_path: Path) -> None:
    bundle = SceneBundle(
        product_id="p",
        provider="fixture",
        bands=(
            SceneBand(polarization="VV", filename="a.tiff", size_bytes=10, checksum_sha256="aa"),
        ),
        data_provenance=DataProvenance.SYNTHETIC,
        notes=("a note",),
    )
    write_bundle(tmp_path, bundle)
    restored = read_bundle(tmp_path)
    assert restored.to_dict() == bundle.to_dict()
    assert restored.band("vv") is not None
    assert restored.band("HH") is None

    stored = bundle_stored_object(tmp_path, bundle)
    assert stored.uri.startswith("file://")
    assert stored.size_bytes == 10
