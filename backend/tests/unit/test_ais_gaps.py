"""Gap detection and classification — including the wording guarantees of CON-002.

The threshold tests sit exactly on each boundary, because "12 hours" is only a criterion
if the code agrees with the specification about what happens *at* twelve hours.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from spilltrace.core.ais import gaps as gaps_module
from spilltrace.core.ais.gaps import (
    Gap,
    GapClass,
    classify_gap,
    detect_gaps,
    gap_quality_flag,
    summarise_gaps,
    with_shore_distance,
)
from spilltrace.core.disclaimers import AIS_GAP_DISCLAIMER, contains_forbidden_language
from spilltrace.core.enums import AISQualityFlag
from spilltrace.core.ports import AISMessage

START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
MMSI = 419001234


def position(minutes: float, *, lat: float = 22.0, lon: float = 69.0) -> AISMessage:
    return AISMessage(
        mmsi=MMSI,
        timestamp=START + timedelta(minutes=minutes),
        latitude=lat,
        longitude=lon,
        message_type="PositionReport",
        source="test",
    )


def gap_of(minutes: float) -> Gap:
    return Gap(
        start=START,
        end=START + timedelta(minutes=minutes),
        duration_minutes=minutes,
        start_lon=69.0,
        start_lat=22.0,
        end_lon=69.5,
        end_lat=22.5,
        classification=GapClass.NORMAL,
        note="",
    )


# --------------------------------------------------------------------------- detection
def test_a_densely_reporting_track_has_no_gaps() -> None:
    positions = [position(minutes=index) for index in range(10)]
    assert detect_gaps(positions) == []


def test_a_gap_records_the_fixes_on_either_side_of_it() -> None:
    positions = [position(0, lat=22.0, lon=69.0), position(45, lat=22.5, lon=69.5)]
    (gap,) = detect_gaps(positions)

    assert gap.duration_minutes == pytest.approx(45.0)
    assert (gap.start_lon, gap.start_lat) == (69.0, 22.0)
    assert (gap.end_lon, gap.end_lat) == (69.5, 22.5)
    assert gap.start == START
    assert gap.end == START + timedelta(minutes=45)


def test_detection_orders_by_time_and_needs_two_positions() -> None:
    assert detect_gaps([]) == []
    assert detect_gaps([position(0)]) == []
    shuffled = [position(90), position(0), position(45)]
    assert [round(gap.duration_minutes) for gap in detect_gaps(shuffled)] == [45, 45]


def test_intervals_at_or_below_the_expected_reporting_rate_are_not_gaps() -> None:
    """The 3-minute floor matches the one ``coverage_ratio`` assumes, so the two agree."""
    assert detect_gaps([position(0), position(3)]) == []
    assert len(detect_gaps([position(0), position(4)])) == 1


# --------------------------------------------------------------------------- thresholds
@pytest.mark.parametrize(
    ("minutes", "distance_nm", "expected"),
    [
        (5.0, None, GapClass.NORMAL),
        (29.9, None, GapClass.NORMAL),
        (30.0, None, GapClass.SEGMENT),
        (119.9, None, GapClass.SEGMENT),
        (120.0, None, GapClass.SUSPICIOUS),
        (719.9, 60.0, GapClass.SUSPICIOUS),
        (720.0, 60.0, GapClass.EXTENDED),
        (840.0, 60.0, GapClass.EXTENDED),
        (720.0, 50.0, GapClass.SUSPICIOUS),
        (720.0, 50.1, GapClass.EXTENDED),
        (720.0, 10.0, GapClass.SUSPICIOUS),
    ],
)
def test_classification_at_every_boundary(
    minutes: float, distance_nm: float | None, expected: GapClass
) -> None:
    assert classify_gap(gap_of(minutes), distance_from_shore_nm=distance_nm) is expected


def test_twelve_hours_with_unknown_shore_distance_is_never_extended() -> None:
    """Half a criterion is not a criterion (AD-24).

    ``EXTENDED`` needs 12 h **and** > 50 nm from shore.  Without the distance we cannot
    tell a vessel far offshore from one in a coverage shadow near the coast, and the
    honest answer to that is not "probably offshore".
    """
    assert classify_gap(gap_of(720.0), distance_from_shore_nm=None) is GapClass.SUSPICIOUS
    assert classify_gap(gap_of(10_000.0), distance_from_shore_nm=None) is GapClass.SUSPICIOUS


def test_detection_alone_never_produces_an_extended_gap() -> None:
    """Distance from shore is unknown at detection time, so the band cannot be reached."""
    positions = [position(0), position(24 * 60)]
    (gap,) = detect_gaps(positions)
    assert gap.classification is GapClass.SUSPICIOUS
    assert gap.distance_from_shore_nm is None


def test_shore_distance_reclassifies_without_mutating_the_original() -> None:
    (gap,) = detect_gaps([position(0), position(14 * 60)])
    enriched = with_shore_distance(gap, distance_from_shore_nm=62.0)

    assert enriched.classification is GapClass.EXTENDED
    assert enriched.distance_from_shore_nm == 62.0
    assert enriched.duration_minutes == gap.duration_minutes
    assert gap.classification is GapClass.SUSPICIOUS  # untouched


def test_shore_distance_can_also_demote() -> None:
    (gap,) = detect_gaps([position(0), position(14 * 60)])
    assert (
        with_shore_distance(gap, distance_from_shore_nm=3.0).classification is GapClass.SUSPICIOUS
    )


# --------------------------------------------------------------------------- wording
@pytest.mark.parametrize("minutes", [5.0, 45.0, 180.0, 900.0])
def test_every_note_carries_the_gap_disclaimer(minutes: float) -> None:
    """CON-002: the caveat must not be separable from the number by a UI or an export."""
    (gap,) = detect_gaps([position(0), position(minutes)])
    assert AIS_GAP_DISCLAIMER in gap.note
    assert contains_forbidden_language(gap.note) == []


def test_an_extended_gap_says_it_lowers_the_score_rather_than_raising_it() -> None:
    (gap,) = detect_gaps([position(0), position(14 * 60)])
    note = with_shore_distance(gap, distance_from_shore_nm=62.0).note

    assert AIS_GAP_DISCLAIMER in note
    assert "lowers" in note
    assert contains_forbidden_language(note) == []


def test_no_public_name_in_this_module_implies_conduct() -> None:
    """Naming is an interface: ``went_dark_intentionally`` would be an accusation in code."""
    forbidden = ("wrongdoing", "guilt", "intentional", "went_dark", "evasion", "illegal", "culprit")
    for name, value in inspect.getmembers(gaps_module):
        if name.startswith("_"):
            continue
        lowered = name.lower()
        assert not any(word in lowered for word in forbidden), name
        if inspect.isclass(value) and hasattr(value, "__dataclass_fields__"):
            for field_name in value.__dataclass_fields__:
                assert not any(word in field_name.lower() for word in forbidden), field_name


def test_the_module_states_that_a_gap_is_not_evidence_of_wrongdoing() -> None:
    docstring = (gaps_module.__doc__ or "").lower()
    assert "not evidence of wrongdoing" in docstring
    assert "con-002" in docstring


# --------------------------------------------------------------------------- statistics
def test_gap_quality_flags_describe_the_record_not_the_vessel() -> None:
    assert gap_quality_flag(GapClass.EXTENDED) is AISQualityFlag.EXTENDED_REPORTING_GAP
    assert gap_quality_flag(GapClass.SUSPICIOUS) is AISQualityFlag.REPORTING_GAP
    assert gap_quality_flag(GapClass.SEGMENT) is None
    assert gap_quality_flag(GapClass.NORMAL) is None


def test_summarise_gaps_reports_count_longest_and_total() -> None:
    gaps = [gap_of(10.0), gap_of(45.0), gap_of(5.0)]
    statistics = summarise_gaps(gaps)

    assert statistics.gap_count == 3
    assert statistics.max_gap_minutes == pytest.approx(45.0)
    assert statistics.total_gap_minutes == pytest.approx(60.0)


def test_summarise_gaps_of_nothing_is_zero_not_an_error() -> None:
    statistics = summarise_gaps([])
    assert (statistics.gap_count, statistics.max_gap_minutes, statistics.total_gap_minutes) == (
        0,
        0.0,
        0.0,
    )
