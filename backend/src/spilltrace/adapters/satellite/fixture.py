"""Deterministic offline satellite catalogue.

The fixture exists so the *real* code path — catalogue search, per-band download, SAR
preprocessing, tiling, inference, polygonisation — can be exercised end to end with no
credentials and no network.  Everything it produces is labelled
``data_provenance=SYNTHETIC`` and its product identifiers say ``SYNTHETIC`` in plain
text, so no artifact derived from it can be mistaken for an observation.

Two deliberate choices make it useful rather than decorative:

* one scene in every result set is **VV-only**, which is what forces the preprocessing
  stage's missing-VH path to be real rather than theoretical;
* the platforms alternate **S1A / S1C**, mirroring the mixed-platform result sets that
  make AD-07's ``product:type`` trap matter.

The measurement files it writes are single-band σ0 (linear power) GeoTIFFs, exactly the
shape a real GRD band has, so nothing downstream needs a fixture-specific branch.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from spilltrace.adapters.satellite.bundle import (
    SceneBand,
    SceneBundle,
    bundle_stored_object,
    sha256_file,
    write_bundle,
)
from spilltrace.core.enums import DataProvenance
from spilltrace.core.errors import ProviderError
from spilltrace.core.geometry import bbox_of, parse_geojson_geometry
from spilltrace.core.ports import ProgressCallback, SceneRecord, StoredObject
from spilltrace.core.raster import raster_bounds_geojson, write_geotiff
from spilltrace.core.time import ensure_utc
from spilltrace.logging import get_logger

log = get_logger(__name__)

PROVIDER = "fixture"
DEFAULT_SCENES = 3
DEFAULT_RASTER_SIZE = 512

#: Typical open-ocean σ0 at C-band VV, moderate incidence, 4–8 m/s wind: about -13 dB.
SEA_SIGMA0_VV = 0.05
#: A damped (oil-covered) surface loses roughly 10 dB of Bragg return.
SLICK_SIGMA0_VV = 0.005
#: Cross-pol sits well below co-pol over the ocean.
VH_RATIO = 0.13
#: GRDH is multi-looked; a Gamma distribution with this shape is the standard model.
EQUIVALENT_NUMBER_OF_LOOKS = 4.4


class FixtureCatalogue:
    """A catalogue that answers from arithmetic instead of a network."""

    name = "fixture"

    def __init__(
        self,
        *,
        scenes_per_search: int = DEFAULT_SCENES,
        raster_size: int = DEFAULT_RASTER_SIZE,
        seed: int = 42,
    ) -> None:
        self._scenes = max(1, scenes_per_search)
        self._raster_size = max(64, raster_size)
        self._seed = seed

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "data_provenance": str(DataProvenance.SYNTHETIC),
            "scenes_per_search": self._scenes,
            "raster_size": self._raster_size,
            "note": "Deterministic offline fixture. No Sentinel-1 observation is involved.",
        }

    # ------------------------------------------------------------------ search
    async def search(
        self,
        *,
        aoi_geojson: dict[str, Any],
        start: datetime,
        end: datetime,
        product_type: str = "IW_GRDH_1S",
        limit: int = 50,
    ) -> list[SceneRecord]:
        start = ensure_utc(start, field="start")
        end = ensure_utc(end, field="end")
        if end <= start:
            raise ProviderError("The search window ends before it starts.", provider=PROVIDER)

        geometry = parse_geojson_geometry(aoi_geojson)
        if geometry.is_empty:
            raise ProviderError("The area of interest is empty.", provider=PROVIDER)
        bbox = bbox_of(geometry)
        base = _digest_seed(bbox, start, end, product_type, self._seed)

        count = min(self._scenes, max(1, limit))
        span = (end - start).total_seconds()
        records: list[SceneRecord] = []
        for index in range(count):
            rng = np.random.default_rng(base + index)
            # Acquisitions land at repeatable points inside the window rather than at
            # its edges, so a window that only just contains a pass still yields one.
            offset = span * (index + 1) / (count + 1)
            acquired = start + timedelta(seconds=round(offset))
            platform = "S1A" if index % 2 == 0 else "S1C"
            polarizations: tuple[str, ...] = (
                ("VV",)
                if index == count - 1 and count > 1
                else (
                    "VV",
                    "VH",
                )
            )
            footprint = _expanded_bbox(bbox, float(rng.uniform(0.04, 0.12)))
            records.append(
                SceneRecord(
                    product_id=(
                        f"{platform}_IW_GRDH_1SDV_{acquired:%Y%m%dT%H%M%S}"
                        f"_SYNTHETIC_{base % 100000:05d}{index:02d}"
                    ),
                    provider=PROVIDER,
                    acquisition_time=acquired,
                    footprint_geojson=raster_bounds_geojson(footprint),
                    mission="SENTINEL-1",
                    platform=platform,
                    product_type=product_type,
                    sensor_mode="IW",
                    polarizations=polarizations,
                    orbit_direction="DESCENDING" if index % 2 == 0 else "ASCENDING",
                    relative_orbit=int(1 + (base + index) % 175),
                    absolute_orbit=int(40000 + (base + index) % 10000),
                    size_bytes=int(1.0e9 + (base + index) % 200_000_000),
                    resolution_m=10.0,
                    provider_ref={
                        "uuid": _fixture_uuid(base, index),
                        "name": f"fixture-{base:x}-{index}",
                        "synthetic": True,
                        "raster_size": self._raster_size,
                        "bounds": list(footprint),
                        "seed": int(base + index),
                    },
                    data_provenance=DataProvenance.SYNTHETIC,
                )
            )
        log.info("fixture_search_complete", results=len(records), provenance="SYNTHETIC")
        return records

    # ------------------------------------------------------------------ download
    async def download(
        self,
        record: SceneRecord,
        *,
        destination: str,
        progress: ProgressCallback | None = None,
        polarizations: tuple[str, ...] = (),
    ) -> StoredObject:
        target = Path(destination)
        await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)

        wanted = tuple(p.upper() for p in (polarizations or record.polarizations or ("VV",)))
        available = tuple(p.upper() for p in (record.polarizations or ("VV",)))
        channels = tuple(p for p in wanted if p in available) or available

        bounds = tuple(record.provider_ref.get("bounds") or (68.0, 21.0, 70.0, 23.0))
        size = int(record.provider_ref.get("raster_size") or self._raster_size)
        seed = int(record.provider_ref.get("seed") or self._seed)

        bands: list[SceneBand] = []
        for index, channel in enumerate(channels):
            if progress is not None:
                await progress(
                    fraction=index / max(1, len(channels)),
                    message=f"generating synthetic {channel} band",
                )
            array = await asyncio.to_thread(
                synthetic_sigma0, size, size, seed=seed, polarization=channel
            )
            payload = await asyncio.to_thread(
                write_geotiff,
                array,
                bounds=(float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3])),
                dtype="float32",
                band_descriptions=(f"sigma0_{channel.lower()}",),
                tags={
                    "provenance": "SYNTHETIC",
                    "product_id": record.product_id,
                    "polarization": channel,
                    "units": "sigma0 linear power",
                    "note": ("Deterministic synthetic backscatter. Not a Sentinel-1 observation."),
                },
            )
            filename = f"{record.product_id.lower()}-{channel.lower()}-001-cog.tiff"
            path = target / filename
            await asyncio.to_thread(path.write_bytes, payload)
            bands.append(
                SceneBand(
                    polarization=channel,
                    filename=filename,
                    size_bytes=len(payload),
                    checksum_sha256=await asyncio.to_thread(sha256_file, path),
                    source_url=None,
                    is_cog=True,
                )
            )

        notes = ["Synthetic scene generated offline; no Copernicus request was made."]
        if "VH" not in channels:
            notes.append("This fixture scene is VV-only, exactly as some real GRD products are.")

        bundle = SceneBundle(
            product_id=record.product_id,
            provider=self.name,
            bands=tuple(bands),
            data_provenance=DataProvenance.SYNTHETIC,
            notes=tuple(notes),
            extra={"bounds": list(bounds), "seed": seed, "raster_size": size},
        )
        await asyncio.to_thread(write_bundle, target, bundle)
        if progress is not None:
            await progress(fraction=1.0, message="synthetic scene written")
        return bundle_stored_object(target, bundle)


# --------------------------------------------------------------------------- raster
def synthetic_sigma0(
    height: int,
    width: int,
    *,
    seed: int,
    polarization: str = "VV",
    with_slick: bool = True,
) -> np.ndarray:
    """A σ0 (linear power) field with sea clutter, speckle and a damped slick.

    The slick is an elongated, meandering ribbon rather than a blob, because a blob is
    trivially separable and would flatter every detector that looked at it.
    """
    rng = np.random.default_rng(seed + (0 if polarization.upper() == "VV" else 977))
    rows = np.arange(height, dtype=np.float64)[:, None]
    cols = np.arange(width, dtype=np.float64)[None, :]

    ratio = 1.0 if polarization.upper() == "VV" else VH_RATIO
    # A slow across-track gradient: real GRDs are brighter at near range.
    gradient = 1.0 + 0.25 * (cols / max(1, width - 1) - 0.5)
    mean = SEA_SIGMA0_VV * ratio * gradient
    mean = np.broadcast_to(mean, (height, width)).copy()

    if with_slick:
        bearing = float(rng.uniform(0.0, np.pi))
        centre_r = height * float(rng.uniform(0.35, 0.65))
        centre_c = width * float(rng.uniform(0.35, 0.65))
        along = (rows - centre_r) * np.cos(bearing) + (cols - centre_c) * np.sin(bearing)
        across = -(rows - centre_r) * np.sin(bearing) + (cols - centre_c) * np.cos(bearing)
        # Meander the ribbon so its boundary is irregular in the way a real trail is.
        meander = 0.05 * width * np.sin(2.0 * np.pi * along / (0.55 * height))
        half_length = 0.34 * height
        half_width = 0.022 * width
        taper = np.clip(1.0 - (along / half_length) ** 2, 0.0, 1.0)
        profile = np.exp(-0.5 * ((across - meander) / (half_width * (0.35 + taper))) ** 2)
        damping = np.where(taper > 0.0, profile, 0.0)
        mean = mean * (1.0 - damping) + (SLICK_SIGMA0_VV * ratio) * damping

    # Two bright point targets: a ship wake next to a slick is the classic confuser.
    for _ in range(2):
        r = int(rng.integers(8, height - 8))
        c = int(rng.integers(8, width - 8))
        mean[r - 1 : r + 2, c - 1 : c + 2] *= 40.0

    # Gamma speckle with the GRDH equivalent number of looks.
    speckle = rng.gamma(
        shape=EQUIVALENT_NUMBER_OF_LOOKS, scale=1.0 / EQUIVALENT_NUMBER_OF_LOOKS, size=mean.shape
    )
    return np.asarray(mean * speckle, dtype=np.float32)


# --------------------------------------------------------------------------- helpers
def _digest_seed(
    bbox: tuple[float, float, float, float],
    start: datetime,
    end: datetime,
    product_type: str,
    salt: int,
) -> int:
    payload = "|".join(
        [
            ",".join(f"{value:.4f}" for value in bbox),
            start.isoformat(),
            end.isoformat(),
            product_type,
            str(salt),
        ]
    )
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:4], "big")


def _fixture_uuid(base: int, index: int) -> str:
    digest = hashlib.sha256(f"{base}:{index}".encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def _expanded_bbox(
    bbox: tuple[float, float, float, float], margin_deg: float
) -> tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = bbox
    return (
        max(-180.0, min_lon - margin_deg),
        max(-90.0, min_lat - margin_deg),
        min(180.0, max_lon + margin_deg),
        min(90.0, max_lat + margin_deg),
    )


__all__ = [
    "EQUIVALENT_NUMBER_OF_LOOKS",
    "SEA_SIGMA0_VV",
    "SLICK_SIGMA0_VV",
    "FixtureCatalogue",
    "synthetic_sigma0",
]
