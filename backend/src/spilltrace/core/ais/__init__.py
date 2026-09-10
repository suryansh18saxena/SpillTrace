"""Pure AIS domain logic: validation, cleaning, gaps, trajectories, reliability.

Nothing in this package performs I/O.  No sockets, no database, no framework, no clock
— ``now`` is always injected — so every result is reproducible from its inputs alone.
The AISStream adapter lives in ``spilltrace.adapters.ais`` and depends on this package;
the dependency never runs the other way (AD-2).

Read ``docs/AIS_PIPELINE.md`` before changing a threshold here.  The numbers are
published criteria, not preferences, and three of them exist specifically to stop a
reporting gap from being read as evidence of wrongdoing (AD-24, CON-002).
"""

from __future__ import annotations

from spilltrace.core.ais.clean import CleanedPosition, clean_track, cleaning_summary
from spilltrace.core.ais.constants import (
    DARK_PERIOD_MIN_DISTANCE_FROM_SHORE_NM,
    DARK_PERIOD_MINUTES,
    MAX_ACCELERATION_KN_PER_S,
    MAX_IMPLIED_SOG_KNOTS,
    MAX_REPORTED_SOG_KNOTS,
    RELIABILITY_WEIGHTS,
    SEGMENT_GAP_MINUTES,
    SUSPICIOUS_GAP_MINUTES,
)
from spilltrace.core.ais.gaps import (
    Gap,
    GapClass,
    GapStatistics,
    classify_gap,
    describe_gap,
    detect_gaps,
    gap_quality_flag,
    summarise_gaps,
    with_shore_distance,
)
from spilltrace.core.ais.reliability import (
    ReliabilityBreakdown,
    SubScore,
    compute_ais_reliability,
    identity_completeness,
    identity_completeness_of,
)
from spilltrace.core.ais.trajectory import (
    TrajectorySegment,
    build_trajectories,
    closest_approach,
    interpolate_position,
)
from spilltrace.core.ais.validate import (
    ETAParts,
    MMSIClass,
    NormalisedFields,
    classify_mmsi,
    decode_rate_of_turn,
    ensure_utc,
    is_attributable_vessel_mmsi,
    mmsi_mid,
    normalise_sentinels,
    parse_aisstream_timestamp,
    validate_coordinates,
    validate_mmsi,
    validate_timestamp,
)

__all__ = [
    "DARK_PERIOD_MINUTES",
    "DARK_PERIOD_MIN_DISTANCE_FROM_SHORE_NM",
    "MAX_ACCELERATION_KN_PER_S",
    "MAX_IMPLIED_SOG_KNOTS",
    "MAX_REPORTED_SOG_KNOTS",
    "RELIABILITY_WEIGHTS",
    "SEGMENT_GAP_MINUTES",
    "SUSPICIOUS_GAP_MINUTES",
    "CleanedPosition",
    "ETAParts",
    "Gap",
    "GapClass",
    "GapStatistics",
    "MMSIClass",
    "NormalisedFields",
    "ReliabilityBreakdown",
    "SubScore",
    "TrajectorySegment",
    "build_trajectories",
    "classify_gap",
    "classify_mmsi",
    "clean_track",
    "cleaning_summary",
    "closest_approach",
    "compute_ais_reliability",
    "decode_rate_of_turn",
    "describe_gap",
    "detect_gaps",
    "ensure_utc",
    "gap_quality_flag",
    "identity_completeness",
    "identity_completeness_of",
    "interpolate_position",
    "is_attributable_vessel_mmsi",
    "mmsi_mid",
    "normalise_sentinels",
    "parse_aisstream_timestamp",
    "summarise_gaps",
    "validate_coordinates",
    "validate_mmsi",
    "validate_timestamp",
    "with_shore_distance",
]
