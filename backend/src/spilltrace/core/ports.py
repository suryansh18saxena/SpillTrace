"""Ports — the typed boundaries between the domain and the outside world (AD-2).

Every port has at least two implementations: one that talks to a real provider and one
that is deterministic and offline.  Which one is active is a configuration choice, and
the choice is always visible to the analyst through ``data_provenance``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from spilltrace.core.enums import DataProvenance, DriftMode


# --------------------------------------------------------------------------- storage
@dataclass(frozen=True, slots=True)
class StoredObject:
    uri: str
    key: str
    size_bytes: int
    checksum_sha256: str
    media_type: str | None = None


@runtime_checkable
class ObjectStore(Protocol):
    """S3-compatible object storage.  Large binaries never go in the database (CON-005)."""

    async def put_bytes(
        self, key: str, data: bytes, *, media_type: str | None = None
    ) -> StoredObject: ...

    async def put_file(
        self, key: str, path: str, *, media_type: str | None = None
    ) -> StoredObject: ...

    async def get_bytes(self, key: str) -> bytes: ...

    async def exists(self, key: str) -> bool: ...

    async def delete(self, key: str) -> None: ...

    async def presigned_url(self, key: str, *, expires_seconds: int = 3600) -> str: ...

    async def healthcheck(self) -> None: ...

    def describe(self) -> str: ...


# --------------------------------------------------------------------------- satellite
@dataclass(frozen=True, slots=True)
class SceneRecord:
    """A catalogue hit, normalised across providers."""

    product_id: str
    provider: str
    acquisition_time: datetime
    footprint_geojson: dict[str, Any]
    mission: str | None = None
    platform: str | None = None
    product_type: str | None = None
    sensor_mode: str | None = None
    polarizations: tuple[str, ...] = ()
    orbit_direction: str | None = None
    relative_orbit: int | None = None
    absolute_orbit: int | None = None
    size_bytes: int | None = None
    resolution_m: float | None = None
    provider_ref: dict[str, Any] = field(default_factory=dict)
    data_provenance: DataProvenance = DataProvenance.REAL


@runtime_checkable
class SatelliteCatalogue(Protocol):
    name: str

    async def search(
        self,
        *,
        aoi_geojson: dict[str, Any],
        start: datetime,
        end: datetime,
        product_type: str = "IW_GRDH_1S",
        limit: int = 50,
    ) -> list[SceneRecord]: ...

    async def download(
        self,
        record: SceneRecord,
        *,
        destination: str,
        progress: ProgressCallback | None = None,
    ) -> StoredObject: ...


class ProgressCallback(Protocol):
    async def __call__(self, *, fraction: float, message: str) -> None: ...


# --------------------------------------------------------------------------- environment
@dataclass(frozen=True, slots=True)
class EnvironmentalField:
    """A gridded environmental variable subset.

    ``values`` is indexed ``[time, lat, lon]``.  Units are always SI and stated
    explicitly so nothing downstream has to guess.
    """

    variable: str
    units: str
    times: tuple[datetime, ...]
    lats: tuple[float, ...]
    lons: tuple[float, ...]
    values: Any  # numpy.ndarray[time, lat, lon]
    source: str
    dataset_id: str | None = None
    data_provenance: DataProvenance = DataProvenance.REAL


@dataclass(frozen=True, slots=True)
class EnvironmentalBundle:
    wind_u: EnvironmentalField
    wind_v: EnvironmentalField
    current_u: EnvironmentalField
    current_v: EnvironmentalField
    source: str
    dataset_ids: dict[str, str] = field(default_factory=dict)
    data_provenance: DataProvenance = DataProvenance.REAL


@runtime_checkable
class EnvironmentalProvider(Protocol):
    name: str

    async def fetch(
        self,
        *,
        bbox: tuple[float, float, float, float],
        start: datetime,
        end: datetime,
    ) -> EnvironmentalBundle: ...


# --------------------------------------------------------------------------- AIS
@dataclass(frozen=True, slots=True)
class AISMessage:
    """A normalised AIS message.

    Sentinel values from the AIS standard (SOG 102.3, COG 360, heading 511, lat 91,
    lon 181, ROT -128) are converted to ``None`` at the adapter boundary so no
    downstream code ever mistakes them for measurements.
    """

    mmsi: int
    timestamp: datetime
    latitude: float
    longitude: float
    message_type: str
    source: str
    sog_knots: float | None = None
    cog_deg: float | None = None
    heading_deg: float | None = None
    rot: float | None = None
    nav_status: int | None = None
    name: str | None = None
    imo: int | None = None
    callsign: str | None = None
    ship_type: int | None = None
    destination: str | None = None
    length_m: float | None = None
    width_m: float | None = None
    draught_m: float | None = None
    eta: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    data_provenance: DataProvenance = DataProvenance.REAL


@runtime_checkable
class AISProvider(Protocol):
    name: str

    def stream(
        self,
        *,
        bboxes: Sequence[tuple[float, float, float, float]],
        message_types: Sequence[str] = ("PositionReport", "ShipStaticData"),
    ) -> AsyncIterator[AISMessage]:
        """Yield messages until cancelled."""
        ...

    async def historical(
        self,
        *,
        bbox: tuple[float, float, float, float],
        start: datetime,
        end: datetime,
    ) -> list[AISMessage]:
        """Positions for a past window.

        Live streams cannot answer this; implementations that cannot must raise
        ``ProviderUnavailableError`` rather than returning an empty list, so the
        difference between 'no vessels' and 'cannot know' is never lost.
        """
        ...


# --------------------------------------------------------------------------- drift
@dataclass(frozen=True, slots=True)
class ParticleState:
    particle_id: int
    step_index: int
    timestamp: datetime
    lon: float
    lat: float
    member: int = 0
    status: str | None = None
    mass_oil: float | None = None


@dataclass(frozen=True, slots=True)
class DriftResult:
    mode: DriftMode
    engine: str
    seed: int
    particles: list[ParticleState]
    times: tuple[datetime, ...]
    parameters: dict[str, Any]
    data_provenance: DataProvenance = DataProvenance.REAL
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class DriftEngine(Protocol):
    name: str

    async def simulate(
        self,
        *,
        seed_geojson: dict[str, Any],
        start_time: datetime,
        mode: DriftMode,
        duration_hours: float,
        time_step_seconds: int,
        number_of_particles: int,
        environment: EnvironmentalBundle,
        seed: int,
        ensemble_members: int = 1,
        parameters: dict[str, Any] | None = None,
        progress: ProgressCallback | None = None,
    ) -> DriftResult: ...


# --------------------------------------------------------------------------- ML
@dataclass(frozen=True, slots=True)
class SegmentationResult:
    probability: Any  # numpy.ndarray[H, W], float32 in [0, 1]
    model_name: str
    model_version: str
    input_channels: int
    notes: list[str] = field(default_factory=list)
    data_provenance: DataProvenance = DataProvenance.REAL


@runtime_checkable
class SegmentationModel(Protocol):
    name: str
    version: str

    async def predict(self, tiles: Any) -> SegmentationResult:
        """``tiles`` is ``ndarray[N, C, H, W]``; returns a probability map."""
        ...

    def describe(self) -> dict[str, Any]: ...


__all__ = [
    "AISMessage",
    "AISProvider",
    "DriftEngine",
    "DriftResult",
    "EnvironmentalBundle",
    "EnvironmentalField",
    "EnvironmentalProvider",
    "ObjectStore",
    "ParticleState",
    "ProgressCallback",
    "SatelliteCatalogue",
    "SceneRecord",
    "SegmentationModel",
    "SegmentationResult",
    "StoredObject",
]
