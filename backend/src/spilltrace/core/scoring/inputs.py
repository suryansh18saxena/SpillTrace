"""Inputs to the scoring engine — plain, pure data.

The scorer must be reproducible and unit-testable without a database, a network or a
framework (NFR-014), so nothing here is an ORM row: these dataclasses are the *whole*
contract between the correlation stage and the scorer.  A caller assembles them from
whatever it has — PostGIS rows in production, literals in a test — and the scoring
result depends on nothing else.

The pipeline is expected to hand over a track that has already been restricted to the
case window and cleaned (``docs/AIS_PIPELINE.md`` §3, §7).  The scorer measures what it
is given and says so in the explanations; it does not go looking for more data.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from spilltrace.core.enums import DataProvenance


def as_utc(moment: datetime) -> datetime:
    """Normalise to UTC.

    A naive timestamp is *assumed* to be UTC rather than rejected: the storage CRS and
    every timestamp column in this system are UTC, and refusing to score a candidate
    over a missing ``tzinfo`` would be a worse failure than the assumption.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SpillContext:
    """The detected slick the attribution is about."""

    #: Acquisition time of the scene the slick was detected in.
    detection_time: datetime
    #: Slick centroid, WGS84 degrees.
    centroid_lon: float
    centroid_lat: float
    #: Slick polygon as GeoJSON.  Used to derive the principal axis for SCORE-004.
    geometry_geojson: dict[str, Any] | None = None
    #: Optional override for the slick's principal axis bearing in degrees.  When
    #: ``None`` it is derived from ``geometry_geojson``; supply it when an upstream
    #: stage has already computed a better estimate.
    principal_axis_deg: float | None = None
    data_provenance: DataProvenance = DataProvenance.REAL


@dataclass(frozen=True, slots=True)
class OriginContext:
    """The reverse-drift result: *where* and *when* a discharge plausibly happened.

    This is a probability region, never an exact discharge coordinate (CON-008), and
    the discharge window is inferred from back-tracked particle density, not observed
    (ambiguity A-02).  Both facts are why the factors below decay smoothly instead of
    testing a hard boundary.
    """

    #: Outer origin probability region as GeoJSON.  ``None`` when the drift stage has
    #: not run or produced nothing — the factors then report insufficient data.
    region_geojson: dict[str, Any] | None = None
    #: Nested probability contours as ``[(probability, geojson)]`` with probability in
    #: ``[0, 1]``.  Higher probability contours are contained in lower ones.  Order is
    #: irrelevant; the scorer sorts.
    contours: Sequence[tuple[float, dict[str, Any]]] = ()
    #: Inferred discharge window (ambiguity A-02).
    window_start: datetime | None = None
    window_end: datetime | None = None
    #: Drift-stage confidence in the region itself.  Reported as evidence, never
    #: multiplied into another confidence (AD-28).
    origin_confidence: float | None = None
    data_provenance: DataProvenance = DataProvenance.REAL


@dataclass(frozen=True, slots=True)
class VesselContext:
    """Vessel identity.  Scoring never depends on identity — only reporting does."""

    mmsi: int
    imo: int | None = None
    name: str | None = None
    ship_type: str | None = None
    data_provenance: DataProvenance = DataProvenance.REAL


@dataclass(frozen=True, slots=True)
class TrackSample:
    """One cleaned AIS position.

    ``sog_knots``, ``cog_deg`` and ``heading_deg`` are ``None`` when the AIS sentinel
    values (102.3 kn, 360°, 511°) were received: absent, not zero.  Treating a sentinel
    as a measurement is how a scorer invents evidence, so the factors check for ``None``
    explicitly everywhere.
    """

    timestamp: datetime
    lon: float
    lat: float
    sog_knots: float | None = None
    cog_deg: float | None = None
    heading_deg: float | None = None


@dataclass(frozen=True, slots=True)
class TrackContext:
    """A vessel's cleaned track plus the AIS quality statistics behind SCORE-006.

    The statistics come from the trajectory builder (``docs/AIS_PIPELINE.md`` §5).  They
    describe *how well we could see this vessel*, and they only ever lower a score —
    see :func:`spilltrace.core.scoring.factors.score_ais_reliability` (CON-002).
    """

    #: Ordered oldest-first.  The scorer re-sorts defensively so a caller's ordering
    #: mistake changes nothing about the result.
    samples: Sequence[TrackSample] = ()
    #: Positions retained by cleaning.  Defaults to ``len(samples)``.
    position_count: int | None = None
    #: Positions cleaning flagged as invalid.  Kept, not deleted — evidence is not
    #: destroyed — but excluded from the track handed to the scorer.
    rejected_count: int = 0
    #: Positions a complete Class A feed would have produced over the same window.
    expected_position_count: int | None = None
    #: ``observed / expected`` from the trajectory builder, clamped to [0, 1].
    coverage_ratio: float | None = None
    gap_count: int = 0
    max_gap_minutes: float = 0.0
    total_gap_minutes: float = 0.0
    #: Fraction of {IMO, name, callsign, type, dimensions} present on the static record.
    static_completeness: float | None = None
    data_provenance: DataProvenance = DataProvenance.REAL

    @property
    def observed_position_count(self) -> int:
        """Positions actually available to the scorer."""
        if self.position_count is not None:
            return self.position_count
        return len(self.samples)

    @classmethod
    def from_tuples(
        cls,
        rows: Iterable[
            tuple[datetime, float, float]
            | tuple[datetime, float, float, float | None]
            | tuple[datetime, float, float, float | None, float | None]
            | tuple[datetime, float, float, float | None, float | None, float | None]
        ],
        **kwargs: Any,
    ) -> TrackContext:
        """Build from ``(timestamp, lon, lat, sog_knots, cog_deg, heading_deg)`` rows.

        A convenience for adapters and tests; trailing fields may be omitted.
        """
        samples = tuple(TrackSample(*row) for row in rows)
        return cls(samples=samples, **kwargs)


@dataclass(frozen=True, slots=True)
class AISSubScores:
    """The five components of SCORE-006 (``docs/AIS_PIPELINE.md`` §6, ambiguity A-03).

    Each is in ``[0, 1]``; ``None`` means "not measurable from what we were given",
    which is a different statement from "measured as zero" and is reported as such.
    """

    coverage: float | None = None
    continuity: float | None = None
    density: float | None = None
    cleanliness: float | None = None
    identity: float | None = None
    #: Free-text notes about which components could not be measured.
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, float | None]:
        return {
            "coverage": self.coverage,
            "continuity": self.continuity,
            "density": self.density,
            "cleanliness": self.cleanliness,
            "identity": self.identity,
        }


__all__ = [
    "AISSubScores",
    "OriginContext",
    "SpillContext",
    "TrackContext",
    "TrackSample",
    "VesselContext",
    "as_utc",
]
