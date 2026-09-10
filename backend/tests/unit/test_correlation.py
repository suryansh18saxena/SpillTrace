"""Vessel correlation.

Correlation decides who gets *considered*, so its failure modes are asymmetric: wrongly
including a vessel wastes an analyst's time, wrongly excluding one loses evidence. Both
directions are tested, including the case where nothing qualifies at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from shapely.geometry import mapping

from spilltrace.core.correlation import (
    DEFAULT_BUFFER_KM,
    correlate_track,
    line_bearing,
    segment_length_km,
)
from spilltrace.core.geometry import bbox_polygon, destination_point

ORIGIN = bbox_polygon(69.10, 22.35, 69.30, 22.50)
CENTRE = (69.20, 22.425)
WINDOW_START = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 13, 13, 0, tzinfo=UTC)
CONTOURS = [
    (0.90, mapping(bbox_polygon(69.08, 22.33, 69.32, 22.52))),
    (0.50, mapping(bbox_polygon(69.16, 22.39, 69.24, 22.46))),
]


def track(
    *,
    offset_km: float,
    at: datetime,
    bearing: float = 90.0,
    count: int = 21,
    speed_knots: float = 12.0,
):
    """A straight transit whose closest approach to CENTRE is ``offset_km`` at ``at``."""
    cpa = destination_point(*CENTRE, (bearing + 90.0) % 360.0, offset_km * 1000.0)
    step = timedelta(minutes=5)
    samples = []
    for i in range(-(count // 2), count // 2 + 1):
        when = at + i * step
        distance = speed_knots * 0.514444 * i * step.total_seconds()
        heading = bearing if distance >= 0 else (bearing + 180.0) % 360.0
        lon, lat = destination_point(*cpa, heading, abs(distance))
        samples.append((when, lon, lat, speed_knots, bearing))
    return samples


def correlate(samples, **kwargs):
    return correlate_track(
        mmsi=419000001,
        samples=samples,
        origin_region=ORIGIN,
        contours=CONTOURS,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        **kwargs,
    )


class TestInclusion:
    def test_a_vessel_inside_the_region_and_window_qualifies(self) -> None:
        evidence = correlate(track(offset_km=0.5, at=datetime(2026, 8, 13, 11, 0, tzinfo=UTC)))
        assert evidence is not None
        assert evidence.inside_region
        assert evidence.closest_approach_km == pytest.approx(0.0, abs=0.1)
        assert evidence.contour_probability == 0.50

    def test_a_vessel_just_outside_but_within_the_buffer_qualifies(self) -> None:
        # Sitting 3 km outside a region whose buffer is 5 km.
        evidence = correlate(
            track(offset_km=11.0, at=datetime(2026, 8, 13, 11, 0, tzinfo=UTC)),
            buffer_km=DEFAULT_BUFFER_KM,
        )
        assert evidence is not None
        assert not evidence.inside_region
        assert "search buffer" in evidence.notes[0]

    def test_a_distant_vessel_does_not_qualify(self) -> None:
        assert correlate(track(offset_km=80.0, at=datetime(2026, 8, 13, 11, 0, tzinfo=UTC))) is None

    def test_a_temporally_incompatible_vessel_does_not_qualify(self) -> None:
        # Three days early, straight through the middle of the region.
        assert correlate(track(offset_km=0.5, at=datetime(2026, 8, 10, 11, 0, tzinfo=UTC))) is None

    def test_an_empty_track_does_not_qualify(self) -> None:
        assert correlate([]) is None

    def test_the_time_tolerance_is_applied(self) -> None:
        just_before = datetime(2026, 8, 13, 7, 45, tzinfo=UTC)  # 75 min before the window
        assert correlate(track(offset_km=0.5, at=just_before), time_tolerance_hours=2.0) is not None
        assert correlate(track(offset_km=0.5, at=just_before), time_tolerance_hours=0.5) is None


class TestEvidence:
    def test_evidence_is_reported_in_checkable_numbers(self) -> None:
        evidence = correlate(track(offset_km=1.0, at=datetime(2026, 8, 13, 11, 0, tzinfo=UTC)))
        assert evidence is not None
        payload = evidence.to_dict()
        for key in (
            "closest_approach_km",
            "closest_approach_time",
            "contour_probability",
            "inside_region",
            "dwell_minutes",
            "positions_in_window",
            "reason",
        ):
            assert key in payload
        assert payload["reason"].endswith(".")

    def test_dwell_time_is_measured(self) -> None:
        evidence = correlate(
            track(offset_km=0.0, at=datetime(2026, 8, 13, 11, 0, tzinfo=UTC), count=41)
        )
        assert evidence is not None
        assert evidence.dwell_minutes > 0

    def test_a_tighter_contour_is_reported_when_entered(self) -> None:
        inner = correlate(track(offset_km=0.0, at=datetime(2026, 8, 13, 11, 0, tzinfo=UTC)))
        outer = correlate(track(offset_km=7.0, at=datetime(2026, 8, 13, 11, 0, tzinfo=UTC)))
        assert inner is not None and outer is not None
        assert inner.contour_probability == 0.50
        assert outer.contour_probability in (0.90, None)

    def test_the_reason_mentions_the_window_relationship(self) -> None:
        evidence = correlate(track(offset_km=0.5, at=datetime(2026, 8, 13, 11, 0, tzinfo=UTC)))
        assert evidence is not None
        assert "inferred discharge window" in evidence.reason


class TestGeometryHelpers:
    def test_line_bearing_of_an_eastward_track(self) -> None:
        from shapely.geometry import LineString

        assert line_bearing(LineString([(69.0, 22.0), (69.5, 22.0)])) == pytest.approx(
            90.0, abs=0.5
        )

    def test_line_bearing_needs_two_points(self) -> None:
        from shapely.geometry import LineString

        assert line_bearing(LineString()) is None

    def test_segment_length(self) -> None:
        assert segment_length_km([(69.0, 22.0), (69.0, 22.5)]) == pytest.approx(55.4, rel=0.01)

    def test_segment_length_of_one_point_is_zero(self) -> None:
        assert segment_length_km([(69.0, 22.0)]) == 0.0
