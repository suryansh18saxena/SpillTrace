"""SQLAlchemy models for every SPILLTRACE entity.

Traces DB-001…DB-015 in ``docs/DATABASE.md``.  Rules enforced here:

* geometry is always EPSG:4326 with a GiST index;
* no large binary lives in a column — only ``storage_uri`` + ``checksum_sha256``
  (CON-005);
* every derived row carries ``data_provenance`` and ``run_manifest``;
* every score-bearing column is range-checked at the database level.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spilltrace.core.enums import (
    ArtifactType,
    CaseStatus,
    DataProvenance,
    DownloadStatus,
    DriftEngineName,
    DriftMode,
    JobStatus,
    UserRole,
    VerificationStatus,
)
from spilltrace.db.base import Base, ManifestMixin, ProvenanceMixin, TimestampMixin, uuid_pk

SRID = 4326


def _enum_check(column: str, enum_cls: type[StrEnum], name: str) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=name)


_PROVENANCE_VALUES = ", ".join(f"'{m.value}'" for m in DataProvenance)


# ============================================================================ users
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=UserRole.ANALYST.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cases: Mapped[list[Case]] = relationship(back_populates="owner")

    __table_args__ = (_enum_check("role", UserRole, "users_role_valid"),)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email} ({self.role})>"


class RefreshToken(Base, TimestampMixin):
    """Rotating refresh tokens.  Only a hash is stored (NFR-007)."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))


# ============================================================================ cases
class Case(Base, TimestampMixin, ProvenanceMixin):
    """DB-001 — an investigation (FR-001)."""

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = uuid_pk()
    case_ref: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CaseStatus.DRAFT.value, index=True
    )
    aoi: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=SRID, spatial_index=True), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scenario: Mapped[str | None] = mapped_column(String(64))
    seed: Mapped[int | None] = mapped_column(BigInteger)

    owner: Mapped[User] = relationship(back_populates="cases")
    scenes: Mapped[list[CaseScene]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    detections: Mapped[list[SpillDetection]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[Job]] = relationship(back_populates="case", cascade="all, delete-orphan")

    __table_args__ = (
        _enum_check("status", CaseStatus, "cases_status_valid"),
        CheckConstraint("end_time > start_time", name="cases_time_window_valid"),
        CheckConstraint(
            f"data_provenance IN ({_PROVENANCE_VALUES})", name="cases_provenance_valid"
        ),
        Index("ix_cases_owner_created", "owner_id", "created_at"),
        Index("ix_cases_time_window", "start_time", "end_time"),
    )


# ============================================================ satellite scenes
class SatelliteScene(Base, TimestampMixin, ProvenanceMixin):
    """DB-002 — a catalogue record, deduplicated globally by ``product_id``."""

    __tablename__ = "satellite_scenes"

    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    mission: Mapped[str | None] = mapped_column(String(32))
    platform: Mapped[str | None] = mapped_column(String(32))
    product_type: Mapped[str | None] = mapped_column(String(16))
    sensor_mode: Mapped[str | None] = mapped_column(String(16))
    acquisition_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    footprint: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=SRID, spatial_index=True), nullable=False
    )
    bbox: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=SRID, spatial_index=True), nullable=False
    )
    polarizations: Mapped[list[str] | None] = mapped_column(ARRAY(String(4)))
    orbit_direction: Mapped[str | None] = mapped_column(String(16))
    relative_orbit: Mapped[int | None] = mapped_column(Integer)
    absolute_orbit: Mapped[int | None] = mapped_column(Integer)
    resolution_m: Mapped[float | None] = mapped_column(Float)
    provider_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    storage_uri: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    download_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=DownloadStatus.NOT_DOWNLOADED.value
    )

    __table_args__ = (
        _enum_check("download_status", DownloadStatus, "scenes_download_status_valid"),
        Index("ix_scenes_type_time", "product_type", "acquisition_time"),
    )


class CaseScene(Base, TimestampMixin):
    """Link table — which scenes were found for, and selected by, a case."""

    __tablename__ = "case_scenes"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("satellite_scenes.id", ondelete="CASCADE"), primary_key=True
    )
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    coverage_fraction: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)

    case: Mapped[Case] = relationship(back_populates="scenes")
    scene: Mapped[SatelliteScene] = relationship()


# ============================================================ spill detections
class SpillDetection(Base, TimestampMixin, ProvenanceMixin, ManifestMixin):
    """DB-003 — a georeferenced oil-like slick (FR-005, FR-006)."""

    __tablename__ = "spill_detections"

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("satellite_scenes.id", ondelete="SET NULL")
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=SRID, spatial_index=True), nullable=False
    )
    centroid: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=SRID, spatial_index=True), nullable=False
    )
    area_km2: Mapped[float] = mapped_column(Float, nullable=False)
    perimeter_km: Mapped[float | None] = mapped_column(Float)
    # Model confidence only.  Never combined with verification or origin confidence (A-06).
    detection_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    mean_probability: Mapped[float | None] = mapped_column(Float)
    max_probability: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    pixel_count: Mapped[int | None] = mapped_column(Integer)
    probability_raster_uri: Mapped[str | None] = mapped_column(Text)
    mask_raster_uri: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    case: Mapped[Case] = relationship(back_populates="detections")
    scene: Mapped[SatelliteScene | None] = relationship()
    model_version: Mapped[ModelVersion | None] = relationship()
    verifications: Mapped[list[VerificationResult]] = relationship(
        back_populates="spill", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "detection_confidence >= 0 AND detection_confidence <= 1",
            name="detections_confidence_range",
        ),
        CheckConstraint("area_km2 >= 0", name="detections_area_non_negative"),
        Index("ix_detections_case_time", "case_id", "detected_at"),
    )


class VerificationResult(Base, TimestampMixin, ManifestMixin):
    """DB-004 — transparent look-alike verification (FR-007).

    Three-class outcome following operational practice: a binary verdict would
    over-claim, and ``UNCERTAIN`` is what keeps the result usable as evidence.
    """

    __tablename__ = "verification_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    spill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spill_detections.id", ondelete="CASCADE"), nullable=False
    )
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    verification_confidence: Mapped[float] = mapped_column(Float, nullable=False)

    wind_speed_ms: Mapped[float | None] = mapped_column(Float)
    wind_direction_deg: Mapped[float | None] = mapped_column(Float)
    wind_source: Mapped[str | None] = mapped_column(String(64))

    shape_area_km2: Mapped[float | None] = mapped_column(Float)
    shape_perimeter_km: Mapped[float | None] = mapped_column(Float)
    shape_complexity: Mapped[float | None] = mapped_column(Float)
    shape_compactness: Mapped[float | None] = mapped_column(Float)
    shape_elongation: Mapped[float | None] = mapped_column(Float)

    slick_mean_db: Mapped[float | None] = mapped_column(Float)
    background_mean_db: Mapped[float | None] = mapped_column(Float)
    contrast_db: Mapped[float | None] = mapped_column(Float)
    slick_std_db: Mapped[float | None] = mapped_column(Float)
    background_std_db: Mapped[float | None] = mapped_column(Float)
    gradient_mean: Mapped[float | None] = mapped_column(Float)

    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    classifier_name: Mapped[str | None] = mapped_column(String(64))
    classifier_score: Mapped[float | None] = mapped_column(Float)

    spill: Mapped[SpillDetection] = relationship(back_populates="verifications")

    __table_args__ = (
        _enum_check("status", VerificationStatus, "verification_status_valid"),
        CheckConstraint(
            "verification_confidence >= 0 AND verification_confidence <= 1",
            name="verification_confidence_range",
        ),
        Index(
            "uq_verification_latest",
            "spill_id",
            unique=True,
            postgresql_where=text("is_latest"),
        ),
    )


# ============================================================ environment & drift
class EnvironmentalRun(Base, TimestampMixin, ProvenanceMixin, ManifestMixin):
    """DB-005 — a wind/current retrieval (FR-008)."""

    __tablename__ = "environmental_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64))
    dataset_id: Mapped[str | None] = mapped_column(String(200))
    variables: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    time_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extent: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=SRID, spatial_index=True), nullable=False
    )
    grid_resolution_deg: Mapped[float | None] = mapped_column(Float)
    storage_uri: Mapped[str | None] = mapped_column(Text)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED")
    error_message: Mapped[str | None] = mapped_column(Text)
    # Summary statistics so the UI can show wind without opening the NetCDF.
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_env_case_time", "case_id", "time_start"),)


class DriftRun(Base, TimestampMixin, ProvenanceMixin, ManifestMixin):
    """DB-006 — a drift simulation producing an origin probability region (FR-009/010)."""

    __tablename__ = "drift_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    spill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spill_detections.id", ondelete="CASCADE"), nullable=False
    )
    environmental_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environmental_runs.id", ondelete="SET NULL")
    )
    engine: Mapped[str] = mapped_column(String(24), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    number_of_particles: Mapped[int] = mapped_column(Integer, nullable=False)
    ensemble_members: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    duration_hours: Mapped[float] = mapped_column(Float, nullable=False)
    time_step_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    # A probability region, never an exact discharge coordinate (CON-008).
    origin_geometry: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=SRID, spatial_index=True)
    )
    origin_confidence: Mapped[float | None] = mapped_column(Float)
    density_grid_uri: Mapped[str | None] = mapped_column(Text)
    contours: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Inferred discharge window (resolution of ambiguity A-02).
    inferred_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inferred_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED")
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        _enum_check("engine", DriftEngineName, "drift_engine_valid"),
        _enum_check("mode", DriftMode, "drift_mode_valid"),
        CheckConstraint(
            "origin_confidence IS NULL OR (origin_confidence >= 0 AND origin_confidence <= 1)",
            name="drift_origin_confidence_range",
        ),
        CheckConstraint("number_of_particles > 0", name="drift_particles_positive"),
        Index("ix_drift_case_created", "case_id", "created_at"),
        Index("ix_drift_spill_mode", "spill_id", "mode"),
    )


class DriftParticle(Base):
    """DB-015 — decimated particle states for visualisation.

    The complete simulation output lives in object storage (CON-005); this table holds
    only what the map animates.
    """

    __tablename__ = "drift_particles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    drift_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drift_runs.id", ondelete="CASCADE"), nullable=False
    )
    particle_id: Mapped[int] = mapped_column(Integer, nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    member: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    position: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=SRID, spatial_index=True), nullable=False
    )
    status: Mapped[str | None] = mapped_column(String(24))
    mass_oil: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (Index("ix_particles_run_step", "drift_run_id", "step_index"),)


# ============================================================ vessels & AIS
class Vessel(Base, TimestampMixin, ProvenanceMixin):
    """DB-007 — vessel identity.

    MMSI is a radio identifier that is reassigned over time; IMO, when available from
    static messages, is the durable key.  Both are kept.
    """

    __tablename__ = "vessels"

    id: Mapped[uuid.UUID] = uuid_pk()
    mmsi: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    imo: Mapped[int | None] = mapped_column(BigInteger, index=True)
    name: Mapped[str | None] = mapped_column(String(120))
    callsign: Mapped[str | None] = mapped_column(String(32))
    ship_type: Mapped[int | None] = mapped_column(SmallInteger)
    ship_type_name: Mapped[str | None] = mapped_column(String(64))
    flag_country: Mapped[str | None] = mapped_column(String(80))
    flag_mid: Mapped[int | None] = mapped_column(SmallInteger)
    length_m: Mapped[float | None] = mapped_column(Float)
    width_m: Mapped[float | None] = mapped_column(Float)
    draught_m: Mapped[float | None] = mapped_column(Float)
    destination: Mapped[str | None] = mapped_column(String(120))
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    static_completeness: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str | None] = mapped_column(String(32))

    positions: Mapped[list[AISPosition]] = relationship(
        back_populates="vessel", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("mmsi >= 100000000 AND mmsi <= 999999999", name="vessels_mmsi_9_digits"),
        CheckConstraint(
            "static_completeness >= 0 AND static_completeness <= 1",
            name="vessels_static_completeness_range",
        ),
    )


class AISPosition(Base):
    """DB-008 — one AIS position report (FR-011, FR-012)."""

    __tablename__ = "ais_positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False
    )
    mmsi: Mapped[int] = mapped_column(BigInteger, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    position: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=SRID, spatial_index=True), nullable=False
    )
    sog_knots: Mapped[float | None] = mapped_column(Float)
    cog_deg: Mapped[float | None] = mapped_column(Float)
    heading_deg: Mapped[float | None] = mapped_column(Float)
    rot: Mapped[float | None] = mapped_column(Float)
    nav_status: Mapped[int | None] = mapped_column(SmallInteger)
    message_type: Mapped[str | None] = mapped_column(String(48))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quality_flags: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    vessel: Mapped[Vessel] = relationship(back_populates="positions")

    __table_args__ = (
        UniqueConstraint("mmsi", "timestamp", "source", name="uq_ais_positions_dedup"),
        CheckConstraint(
            "sog_knots IS NULL OR (sog_knots >= 0 AND sog_knots < 102.2)",
            name="ais_sog_plausible",
        ),
        CheckConstraint(
            "cog_deg IS NULL OR (cog_deg >= 0 AND cog_deg < 360)", name="ais_cog_range"
        ),
        CheckConstraint(
            "heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg < 360)",
            name="ais_heading_range",
        ),
        Index("ix_ais_vessel_time", "vessel_id", "timestamp"),
        Index("ix_ais_timestamp_brin", "timestamp", postgresql_using="brin"),
        Index("ix_ais_valid_time", "timestamp", postgresql_where=text("is_valid")),
    )


class Trajectory(Base, TimestampMixin, ProvenanceMixin):
    """DB-009 — a reconstructed vessel track (FR-013)."""

    __tablename__ = "trajectories"

    id: Mapped[uuid.UUID] = uuid_pk()
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    time_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=SRID, spatial_index=True), nullable=False
    )
    position_count: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mean_sog_knots: Mapped[float | None] = mapped_column(Float)
    max_sog_knots: Mapped[float | None] = mapped_column(Float)
    gap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_gap_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_gap_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    coverage_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    quality_flags: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list
    )

    vessel: Mapped[Vessel] = relationship()

    __table_args__ = (
        CheckConstraint("time_end >= time_start", name="trajectories_time_order"),
        CheckConstraint(
            "quality_score >= 0 AND quality_score <= 1", name="trajectories_quality_range"
        ),
        Index("ix_trajectories_vessel_time", "vessel_id", "time_start"),
    )


# ============================================================ attribution
class Attribution(Base, TimestampMixin, ProvenanceMixin, ManifestMixin):
    """DB-010 — factor-by-factor vessel scoring (FR-015, FR-016, PRD Part J).

    Every factor is stored separately so the UI and report can explain the result
    rather than presenting an opaque number (SCORE-007).
    """

    __tablename__ = "attributions"

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    spill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spill_detections.id", ondelete="CASCADE"), nullable=False
    )
    drift_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drift_runs.id", ondelete="SET NULL")
    )
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False
    )
    trajectory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trajectories.id", ondelete="SET NULL")
    )

    origin_proximity: Mapped[float] = mapped_column(Float, nullable=False)
    time_match: Mapped[float] = mapped_column(Float, nullable=False)
    trajectory_match: Mapped[float] = mapped_column(Float, nullable=False)
    heading_match: Mapped[float] = mapped_column(Float, nullable=False)
    speed_match: Mapped[float] = mapped_column(Float, nullable=False)
    ais_reliability: Mapped[float] = mapped_column(Float, nullable=False)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    factor_explanations: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    closest_approach_km: Mapped[float | None] = mapped_column(Float)
    closest_approach_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scoring_version: Mapped[str] = mapped_column(String(32), nullable=False)

    vessel: Mapped[Vessel] = relationship()
    trajectory: Mapped[Trajectory | None] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "case_id", "spill_id", "vessel_id", "scoring_version", name="uq_attribution_unique"
        ),
        *[
            CheckConstraint(f"{c} >= 0 AND {c} <= 1", name=f"attribution_{c}_range")
            for c in (
                "origin_proximity",
                "time_match",
                "trajectory_match",
                "heading_match",
                "speed_match",
                "ais_reliability",
                "final_score",
            )
        ],
        Index("ix_attributions_rank", "case_id", "spill_id", "rank"),
    )


# ============================================================ jobs & artifacts
class Job(Base, TimestampMixin):
    """DB-011 — durable job record.  The database, not Redis, is the source of truth."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE")
    )
    pipeline_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.QUEUED.value)
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    step: Mapped[str | None] = mapped_column(String(200))
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    depends_on: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(64))

    case: Mapped[Case | None] = relationship(back_populates="jobs")

    __table_args__ = (
        _enum_check("status", JobStatus, "jobs_status_valid"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="jobs_progress_range"),
        Index("ix_jobs_case_created", "case_id", "created_at"),
        Index("ix_jobs_dispatch", "status", "priority", "queued_at"),
        Index(
            "ix_jobs_running_heartbeat",
            "heartbeat_at",
            postgresql_where=text("status = 'RUNNING'"),
        ),
    )


class EvidenceArtifact(Base, TimestampMixin, ProvenanceMixin):
    """DB-012 — reference to a stored object, with its checksum (NFR-005/006)."""

    __tablename__ = "evidence_artifacts"

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    related_table: Mapped[str | None] = mapped_column(String(64))
    related_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )

    __table_args__ = (
        _enum_check("artifact_type", ArtifactType, "artifacts_type_valid"),
        Index("ix_artifacts_case_type", "case_id", "artifact_type"),
    )


class ModelVersion(Base, TimestampMixin):
    """DB-013 — a versioned model with **measured** metrics.

    Metrics are written only by the training/evaluation pipeline from real runs.
    """

    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    framework: Mapped[str | None] = mapped_column(String(32))
    task: Mapped[str | None] = mapped_column(String(48))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    training_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    input_channels: Mapped[int | None] = mapped_column(SmallInteger)
    input_size: Mapped[int | None] = mapped_column(Integer)
    normalization: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_model_name_version"),
        Index("uq_model_active", "name", unique=True, postgresql_where=text("is_active")),
    )


__all__ = [
    "AISPosition",
    "Attribution",
    "Base",
    "Case",
    "CaseScene",
    "DriftParticle",
    "DriftRun",
    "EnvironmentalRun",
    "EvidenceArtifact",
    "Job",
    "ModelVersion",
    "RefreshToken",
    "SatelliteScene",
    "SpillDetection",
    "Trajectory",
    "User",
    "VerificationResult",
    "Vessel",
]
