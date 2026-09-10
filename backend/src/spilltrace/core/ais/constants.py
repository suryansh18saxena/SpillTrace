"""Numeric thresholds for the AIS pipeline — every one of them traceable.

No threshold in this package is written at its call site.  An analyst who sees a
position flagged as an impossible jump must be able to find the number *and the reason
for the number* in one place, and a reviewer must be able to check that number against
the published criterion it came from.  Sources: ``docs/AIS_PIPELINE.md`` §2-§6 and
``docs/DECISIONS.md`` AD-21…AD-26.

The gap thresholds in particular are deliberately three separate names with three
separate values (AD-24): conflating them is exactly how a system ends up implying
wrongdoing from a satellite revisit interval.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from spilltrace.core.geometry import KNOT_IN_MS

# --------------------------------------------------------------------------- speed
#: Reported ``SOG`` above this is treated as a bad *field*, not a fast ship.  30 kn is
#: the most commonly published cutoff; 25 kn is used for merchant traffic specifically,
#: so 30 kn is the conservative choice for mixed traffic (AD-23).
MAX_REPORTED_SOG_KNOTS: Final[float] = 30.0

#: Speed *implied* by two consecutive fixes above this is a position error, not motion.
#: Deliberately a different number from ``MAX_REPORTED_SOG_KNOTS``: a corrupted speed
#: field and a corrupted position are different failure modes and must not share a
#: threshold, or one masks the other (AD-23).
MAX_IMPLIED_SOG_KNOTS: Final[float] = 40.0

#: Maximum plausible acceleration of a surface vessel (Sinni & Kyriazanos).  0.15 kn/s
#: is ~9 kn per minute — far beyond any real ship, which is the point: a bound this
#: permissive only ever fires on data errors, never on seamanship.
MAX_ACCELERATION_KN_PER_S: Final[float] = 0.15

#: The same bound in SI, because displacement checks work in metres and seconds.
MAX_ACCELERATION_MS2: Final[float] = MAX_ACCELERATION_KN_PER_S * KNOT_IN_MS

#: Below this speed a vessel's course over ground is dominated by noise, so comparing
#: ``COG`` with the bearing between fixes says nothing.  Manoeuvring, drifting and
#: moored vessels all live here.
COG_CONSISTENCY_MIN_SOG_KNOTS: Final[float] = 1.0

#: A course that disagrees with the observed bearing by more than a right angle is not
#: a turn, it is a disagreement between two fields.
COG_CONSISTENCY_MAX_DEVIATION_DEG: Final[float] = 90.0

# --------------------------------------------------------------------------- gaps
#: Split a trajectory into continuous segments.  Not a behavioural signal — purely a
#: geometry decision, so that a ``LineString`` never bridges a period we did not see.
SEGMENT_GAP_MINUTES: Final[float] = 30.0

#: Worth an analyst's attention.  **Review only** — it is never scored (AD-24).
SUSPICIOUS_GAP_MINUTES: Final[float] = 120.0

#: Global Fishing Watch's dark-period criterion.  Below 12 h a gap is not informative
#: at all: a single sun-synchronous AIS satellite takes roughly that long to re-cover a
#: location, so shorter gaps are mostly orbital mechanics.
DARK_PERIOD_MINUTES: Final[float] = 720.0

#: The other half of the same criterion.  Nearer than 50 nm to shore the difference
#: between terrestrial and satellite reception dominates, so distance from coverage —
#: not vessel behaviour — explains the gap.
DARK_PERIOD_MIN_DISTANCE_FROM_SHORE_NM: Final[float] = 50.0

# --------------------------------------------------------------------------- rates
#: ITU-R M.1371 Class A reporting intervals.  Under way the interval is 2-10 s; at
#: anchor or moored it relaxes to 3 minutes.
CLASS_A_UNDERWAY_MIN_INTERVAL_SECONDS: Final[float] = 2.0
CLASS_A_UNDERWAY_MAX_INTERVAL_SECONDS: Final[float] = 10.0
CLASS_A_ANCHORED_INTERVAL_SECONDS: Final[float] = 180.0

#: The rate used to compute ``coverage_ratio``, conservatively floored at the slowest
#: Class A rate.  Using the under-way rate would make every real track look sparse and
#: would turn ordinary receiver coverage into an apparent data-quality problem.
EXPECTED_REPORT_INTERVAL_SECONDS: Final[float] = CLASS_A_ANCHORED_INTERVAL_SECONDS
EXPECTED_REPORT_INTERVAL_MINUTES: Final[float] = EXPECTED_REPORT_INTERVAL_SECONDS / 60.0
EXPECTED_REPORTS_PER_HOUR: Final[float] = 3600.0 / EXPECTED_REPORT_INTERVAL_SECONDS

# --------------------------------------------------------------------------- time
#: Clock skew allowance before a timestamp is treated as impossible rather than early.
FUTURE_TIMESTAMP_TOLERANCE_MINUTES: Final[float] = 5.0

#: The Unix epoch is what an uninitialised or failed clock reports, so an exact match
#: is a decoder artefact rather than a 1970 voyage.
EPOCH_ZERO_UTC: Final[datetime] = datetime(1970, 1, 1, tzinfo=UTC)

#: AIS carriage requirements began with SOLAS Chapter V in 2002; nothing before 2000
#: can be a genuine AIS observation, so anything earlier is a decoding failure.
MIN_PLAUSIBLE_TIMESTAMP_UTC: Final[datetime] = datetime(2000, 1, 1, tzinfo=UTC)

# --------------------------------------------------------------------------- dedup
#: Five decimal degrees is ~1.1 m at the equator, an order of magnitude finer than AIS
#: positional accuracy, so rounding here cannot merge two genuinely distinct fixes.
DEDUP_COORDINATE_DECIMALS: Final[int] = 5

#: Duplicate detection buckets timestamps to the second: AISStream re-delivers the same
#: report with differing sub-second receipt times, and ``time_utc`` is receipt time, not
#: transmit time (AD-21), so sub-second differences carry no information.
DEDUP_TIMESTAMP_RESOLUTION_SECONDS: Final[float] = 1.0

#: Latitude/longitude within this of exactly (0, 0) is the Null Island artefact — the
#: value a decoder emits when it has no position at all.
NULL_ISLAND_TOLERANCE_DEG: Final[float] = 1e-9

# --------------------------------------------------------------------------- sentinels
# ITU-R M.1371 "not available" encodings.  AISStream delivers decoded physical units
# but does **not** document whether it normalises these (AD-22), so they are filtered
# defensively at the boundary and turned into NULL — never into a number.
SOG_SENTINEL_KNOTS: Final[float] = 102.2
COG_SENTINEL_DEG: Final[float] = 360.0
HEADING_SENTINEL_DEG: Final[int] = 511
LATITUDE_SENTINEL_DEG: Final[float] = 91.0
LONGITUDE_SENTINEL_DEG: Final[float] = 181.0
MAX_LATITUDE_DEG: Final[float] = 90.0
MAX_LONGITUDE_DEG: Final[float] = 180.0
ROT_SENTINEL: Final[int] = -128

#: Second-of-minute 60-63 is receiver status (60 = not available, 61 = manual input,
#: 62 = dead reckoning, 63 = inoperative), never a time.
SECOND_OF_MINUTE_SENTINEL: Final[int] = 60
MAX_SECOND_OF_MINUTE: Final[int] = 59

#: Ship-and-cargo type: 0 is "not available"; the table only defines 1-99.
SHIP_TYPE_MIN: Final[int] = 1
SHIP_TYPE_MAX: Final[int] = 99

#: Reference-point dimensions saturate: A/B at 511 m, C/D at 63 m mean "at or above",
#: which is a bound, not a measurement.
DIMENSION_AB_SENTINEL_M: Final[float] = 511.0
DIMENSION_CD_SENTINEL_M: Final[float] = 63.0

#: ETA "not available" encodings.
ETA_MONTH_SENTINEL: Final[int] = 0
ETA_DAY_SENTINEL: Final[int] = 0
ETA_HOUR_SENTINEL: Final[int] = 24
ETA_MINUTE_SENTINEL: Final[int] = 60

#: ``ROT_AIS = 4.733·√(ROT_sensor)``.  **UNCERTAIN** whether AISStream pre-decodes this
#: (AD-22), so the decode is available but ROT is never used in scoring.
ROT_AIS_SCALE: Final[float] = 4.733

# --------------------------------------------------------------------------- MMSI
MMSI_DIGITS: Final[int] = 9
MMSI_MIN: Final[int] = 1
MMSI_MAX: Final[int] = 999_999_999

#: Ship MIDs (Maritime Identification Digits) occupy 201-775; everything outside is
#: either a reserved station class or an invalid identifier (AD-25).
MMSI_MID_MIN: Final[int] = 201
MMSI_MID_MAX: Final[int] = 775

# --------------------------------------------------------------------------- scoring
#: ``ais_reliability`` weights (docs/AIS_PIPELINE.md §6, SCORE-006).  These resolve
#: ambiguity A-03: the PRD names the factor but never defines it.  They sum to 1.0 and
#: a unit test asserts that they still do.
RELIABILITY_WEIGHT_COVERAGE: Final[float] = 0.30
RELIABILITY_WEIGHT_CONTINUITY: Final[float] = 0.25
RELIABILITY_WEIGHT_DENSITY: Final[float] = 0.20
RELIABILITY_WEIGHT_CLEANLINESS: Final[float] = 0.15
RELIABILITY_WEIGHT_IDENTITY: Final[float] = 0.10

RELIABILITY_WEIGHTS: Final[dict[str, float]] = {
    "coverage": RELIABILITY_WEIGHT_COVERAGE,
    "continuity": RELIABILITY_WEIGHT_CONTINUITY,
    "density": RELIABILITY_WEIGHT_DENSITY,
    "cleanliness": RELIABILITY_WEIGHT_CLEANLINESS,
    "identity": RELIABILITY_WEIGHT_IDENTITY,
}

#: The static fields whose presence makes up the ``identity`` sub-score.  "dimensions"
#: counts as present only when both length and width are known, because half a hull is
#: not an identification.
IDENTITY_FIELDS: Final[tuple[str, ...]] = ("imo", "name", "callsign", "ship_type", "dimensions")

#: Per-segment quality weights.  Distinct from the vessel-level reliability weights
#: above: this scores *one continuous segment's* geometry, not a vessel's whole
#: evidential footprint, and it never feeds SCORE-006 directly.
SEGMENT_QUALITY_WEIGHT_COVERAGE: Final[float] = 0.50
SEGMENT_QUALITY_WEIGHT_CONTINUITY: Final[float] = 0.30
SEGMENT_QUALITY_WEIGHT_CLEANLINESS: Final[float] = 0.20

SEGMENT_QUALITY_WEIGHTS: Final[dict[str, float]] = {
    "coverage": SEGMENT_QUALITY_WEIGHT_COVERAGE,
    "continuity": SEGMENT_QUALITY_WEIGHT_CONTINUITY,
    "cleanliness": SEGMENT_QUALITY_WEIGHT_CLEANLINESS,
}

#: Scores are rounded before storage so that two runs over identical input produce
#: byte-identical artifacts; floating-point noise is not evidence.
SCORE_DECIMALS: Final[int] = 6

# --------------------------------------------------------------------------- cleaning
#: Two fixes bearing the same instant may differ by at most this before they describe
#: two places at once.  Tied to ``DEDUP_COORDINATE_DECIMALS`` (~1.1 m), so it is exactly
#: the rounding noise the deduplicator tolerates and nothing more.  One MMSI
#: broadcasting from two positions simultaneously is a documented 2025 spoofing
#: typology, so the pair is flagged rather than quietly averaged.
SAME_INSTANT_DISPLACEMENT_TOLERANCE_M: Final[float] = 1.5

#: Below this displacement the bearing between two fixes is dominated by AIS positional
#: noise, so comparing it with ``COG`` would flag well-behaved vessels reporting every
#: few seconds.  Roughly ten times the resolution of an encoded AIS position.
COG_CONSISTENCY_MIN_DISPLACEMENT_M: Final[float] = 10.0
