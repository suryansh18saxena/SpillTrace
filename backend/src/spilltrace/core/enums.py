"""Domain enumerations shared by the database, API and workers."""

from __future__ import annotations

from enum import StrEnum


class DataProvenance(StrEnum):
    """Where the data behind an artifact actually came from.

    Carried by every derived artifact and surfaced in the UI and evidence report so
    synthetic data can never be mistaken for a real-world observation (CON-009).
    """

    REAL = "REAL"
    SYNTHETIC = "SYNTHETIC"
    MIXED = "MIXED"


class CaseStatus(StrEnum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)


class JobType(StrEnum):
    """Stable job identifiers.  Order here is the canonical pipeline order."""

    SCENE_SEARCH = "scene.search"
    SCENE_DOWNLOAD = "scene.download"
    SAR_PREPROCESS = "sar.preprocess"
    ML_DETECT = "ml.detect"
    DETECT_VERIFY = "detect.verify"
    ENV_FETCH = "env.fetch"
    DRIFT_HINDCAST = "drift.hindcast"
    AIS_INGEST = "ais.ingest"
    AIS_CLEAN = "ais.clean"
    TRAJ_BUILD = "traj.build"
    CORRELATE = "correlate"
    SCORE = "score"
    REPORT_BUILD = "report.build"
    DEMO_SEED = "demo.seed"


#: The default end-to-end investigation pipeline (PRD Part C).
#:
#: ``env.fetch`` runs **before** ``detect.verify``, not after it as the PRD's numbered
#: list implies. Wind is the single most useful physical discriminator between oil and a
#: look-alike (docs/DECISIONS.md AD-15), and verification cannot apply it to data that
#: has not been retrieved yet. Ordered the other way, the wind rule reports "not
#: evaluated" on every real case and the most important check silently never runs.
PIPELINE_ORDER: tuple[JobType, ...] = (
    JobType.SCENE_SEARCH,
    JobType.SCENE_DOWNLOAD,
    JobType.SAR_PREPROCESS,
    JobType.ML_DETECT,
    JobType.ENV_FETCH,
    JobType.DETECT_VERIFY,
    JobType.DRIFT_HINDCAST,
    JobType.AIS_INGEST,
    JobType.AIS_CLEAN,
    JobType.TRAJ_BUILD,
    JobType.CORRELATE,
    JobType.SCORE,
    JobType.REPORT_BUILD,
)


class VerificationStatus(StrEnum):
    """Three-class outcome, matching operational practice (Solberg et al. 1999).

    A binary oil/not-oil verdict over-claims; the ``UNCERTAIN`` class is what makes the
    result usable as investigative evidence.
    """

    VERIFIED = "VERIFIED"
    UNCERTAIN = "UNCERTAIN"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class DriftMode(StrEnum):
    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"
    ENSEMBLE = "ENSEMBLE"


class DriftEngineName(StrEnum):
    OPENOIL = "openoil"
    OPENDRIFT = "opendrift"
    ANALYTICAL = "analytical"


class DownloadStatus(StrEnum):
    NOT_DOWNLOADED = "NOT_DOWNLOADED"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    FAILED = "FAILED"


class ArtifactType(StrEnum):
    GRD = "GRD"
    TILE = "TILE"
    PROBABILITY_RASTER = "PROBABILITY_RASTER"
    MASK = "MASK"
    ENV_NETCDF = "ENV_NETCDF"
    DRIFT_OUTPUT = "DRIFT_OUTPUT"
    DENSITY_GRID = "DENSITY_GRID"
    REPORT_HTML = "REPORT_HTML"
    REPORT_PDF = "REPORT_PDF"
    GEOJSON = "GEOJSON"


class UserRole(StrEnum):
    ANALYST = "analyst"
    ADMIN = "admin"


class AISQualityFlag(StrEnum):
    """Why a position was flagged.  Descriptive only — never an accusation (CON-002)."""

    DUPLICATE = "DUPLICATE"
    INVALID_MMSI = "INVALID_MMSI"
    NON_SHIP_STATION = "NON_SHIP_STATION"
    INVALID_COORDINATE = "INVALID_COORDINATE"
    SENTINEL_POSITION = "SENTINEL_POSITION"
    NULL_ISLAND = "NULL_ISLAND"
    BAD_TIMESTAMP = "BAD_TIMESTAMP"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    IMPLAUSIBLE_SOG = "IMPLAUSIBLE_SOG"
    IMPOSSIBLE_JUMP = "IMPOSSIBLE_JUMP"
    KINEMATIC_OUTLIER = "KINEMATIC_OUTLIER"
    COG_INCONSISTENT = "COG_INCONSISTENT"
    REPORTING_GAP = "REPORTING_GAP"
    EXTENDED_REPORTING_GAP = "EXTENDED_REPORTING_GAP"
    #: A trajectory segment holding a single fix: recorded, never dropped, but it
    #: yields no geometry and supports no movement inference.
    SINGLE_POINT_SEGMENT = "SINGLE_POINT_SEGMENT"


class ComponentStatus(StrEnum):
    UP = "UP"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
