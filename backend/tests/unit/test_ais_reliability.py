"""The AIS reliability factor (SCORE-006, docs/AIS_PIPELINE.md §6).

The load-bearing test in this file is ``test_sparse_ais_scores_lower_...``: it is the
CON-002 guard.  If it ever fails, the system has started rewarding vessels for being
unobserved, which is the inference the whole project is built to refuse.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from spilltrace.core.ais.constants import (
    DARK_PERIOD_MINUTES,
    IDENTITY_FIELDS,
    RELIABILITY_WEIGHTS,
)
from spilltrace.core.ais.reliability import (
    ReliabilityBreakdown,
    compute_ais_reliability,
    identity_completeness,
    identity_completeness_of,
)
from spilltrace.core.disclaimers import AIS_GAP_DISCLAIMER, contains_forbidden_language
from spilltrace.core.enums import DataProvenance
from spilltrace.core.ports import AISMessage

WINDOW_HOURS = 24.0


def breakdown(
    *,
    coverage_ratio: float = 0.9,
    max_gap_minutes: float = 5.0,
    position_count: int = 480,
    window_hours: float = WINDOW_HOURS,
    total_positions: int = 500,
    rejected_positions: int = 20,
    static_completeness: float = 1.0,
) -> ReliabilityBreakdown:
    return compute_ais_reliability(
        coverage_ratio=coverage_ratio,
        max_gap_minutes=max_gap_minutes,
        position_count=position_count,
        window_hours=window_hours,
        total_positions=total_positions,
        rejected_positions=rejected_positions,
        static_completeness=static_completeness,
    )


# --------------------------------------------------------------------------- weights
def test_the_weights_sum_to_one() -> None:
    assert sum(RELIABILITY_WEIGHTS.values()) == pytest.approx(1.0)


def test_the_weights_are_the_ones_the_specification_publishes() -> None:
    assert RELIABILITY_WEIGHTS == {
        "coverage": 0.30,
        "continuity": 0.25,
        "density": 0.20,
        "cleanliness": 0.15,
        "identity": 0.10,
    }


def test_the_breakdown_carries_those_same_weights() -> None:
    result = breakdown()
    assert {score.name: score.weight for score in result.sub_scores} == RELIABILITY_WEIGHTS
    assert sum(score.weight for score in result.sub_scores) == pytest.approx(1.0)
    assert sum(score.contribution for score in result.sub_scores) == pytest.approx(result.total)


# --------------------------------------------------------------------------- range
def test_a_vessel_we_never_saw_scores_zero() -> None:
    result = breakdown(
        coverage_ratio=0.0,
        max_gap_minutes=DARK_PERIOD_MINUTES,
        position_count=0,
        total_positions=0,
        rejected_positions=0,
        static_completeness=0.0,
    )
    assert result.total == 0.0
    assert all(score.value == 0.0 for score in result.sub_scores)


def test_a_perfectly_observed_vessel_scores_one() -> None:
    result = breakdown(
        coverage_ratio=1.0,
        max_gap_minutes=0.0,
        position_count=1000,
        total_positions=1000,
        rejected_positions=0,
        static_completeness=1.0,
    )
    assert result.total == 1.0
    assert all(score.value == 1.0 for score in result.sub_scores)


def test_every_sub_score_at_a_half_gives_exactly_a_half() -> None:
    """Each sub-score is on the same [0, 1] scale, so a uniform half must total a half."""
    result = breakdown(
        coverage_ratio=0.5,
        max_gap_minutes=DARK_PERIOD_MINUTES / 2,
        position_count=240,
        total_positions=100,
        rejected_positions=50,
        static_completeness=0.5,
    )
    assert result.total == pytest.approx(0.5)
    assert [score.value for score in result.sub_scores] == pytest.approx([0.5] * 5)


def test_values_are_clamped_rather_than_allowed_to_run_past_the_ends() -> None:
    result = breakdown(coverage_ratio=3.0, max_gap_minutes=10 * DARK_PERIOD_MINUTES)
    assert result.coverage.value == 1.0
    assert result.continuity.value == 0.0
    assert 0.0 <= result.total <= 1.0


# --------------------------------------------------------------------------- CON-002
def test_sparse_ais_scores_lower_than_continuous_ais() -> None:
    """The CON-002 guard: absence of evidence must never improve a vessel's standing.

    Two vessels, identical in every other respect; one has a fourteen-hour hole in its
    reporting.  If the system ever scored that vessel *higher* it would be saying "it
    went dark, therefore it did it" — an unfalsifiable inference, because a vessel that
    transmitted nothing cannot produce the evidence that would clear it.
    """
    continuous = breakdown(coverage_ratio=0.95, max_gap_minutes=5.0, position_count=470)
    sparse = breakdown(coverage_ratio=0.30, max_gap_minutes=14 * 60.0, position_count=120)

    assert sparse.total < continuous.total
    assert sparse.continuity.value == 0.0
    assert sparse.continuity.value < continuous.continuity.value
    assert sparse.coverage.value < continuous.coverage.value
    assert sparse.density.value < continuous.density.value


def test_the_gap_alone_lowers_the_score_with_everything_else_held_equal() -> None:
    """Isolates the gap: only ``max_gap_minutes`` differs between these two."""
    tight = breakdown(max_gap_minutes=5.0)
    dark = breakdown(max_gap_minutes=14 * 60.0)

    assert dark.total < tight.total
    assert tight.total - dark.total == pytest.approx(
        RELIABILITY_WEIGHTS["continuity"] * tight.continuity.value
    )


def test_continuity_hits_zero_exactly_at_the_dark_period_threshold() -> None:
    assert breakdown(max_gap_minutes=DARK_PERIOD_MINUTES).continuity.value == 0.0
    assert breakdown(max_gap_minutes=DARK_PERIOD_MINUTES - 1).continuity.value > 0.0
    assert breakdown(max_gap_minutes=DARK_PERIOD_MINUTES * 5).continuity.value == 0.0


def test_a_long_gap_explanation_carries_the_disclaimer() -> None:
    """Wherever a gap is surfaced, the caveat goes with it (CON-002)."""
    assert AIS_GAP_DISCLAIMER in breakdown(max_gap_minutes=14 * 60.0).continuity.explanation
    assert AIS_GAP_DISCLAIMER not in breakdown(max_gap_minutes=5.0).continuity.explanation


def test_no_explanation_reads_as_an_accusation() -> None:
    for result in (breakdown(), breakdown(coverage_ratio=0.0, max_gap_minutes=2000.0)):
        for score in result.sub_scores:
            assert score.explanation
            assert contains_forbidden_language(score.explanation) == []


def test_receiving_nothing_is_not_the_same_as_receiving_only_clean_data() -> None:
    """CON-007: zero positions must not read as perfect cleanliness."""
    empty = breakdown(total_positions=0, rejected_positions=0)
    assert empty.cleanliness.value == 0.0
    assert "not evidence of its absence" in empty.cleanliness.explanation


# --------------------------------------------------------------------------- identity
def test_identity_completeness_counts_the_five_static_fields() -> None:
    assert len(IDENTITY_FIELDS) == 5
    assert identity_completeness() == 0.0
    assert identity_completeness(imo=9074729) == pytest.approx(0.2)
    assert identity_completeness(
        imo=9074729,
        name="EVER GIVEN",
        callsign="H3RC",
        ship_type=70,
        length_m=399.0,
        width_m=59.0,
    ) == pytest.approx(1.0)


def test_half_a_hull_is_not_an_identification() -> None:
    assert identity_completeness(length_m=399.0) == 0.0
    assert identity_completeness(length_m=399.0, width_m=59.0) == pytest.approx(0.2)


def test_ais_pads_static_text_so_blank_strings_count_as_absent() -> None:
    assert identity_completeness(name="   ", callsign="") == 0.0
    assert identity_completeness(name="EVER GIVEN") == pytest.approx(0.2)


def test_identity_completeness_of_a_static_message() -> None:
    message = AISMessage(
        mmsi=419001234,
        timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        latitude=22.0,
        longitude=69.0,
        message_type="ShipStaticData",
        source="test",
        name="TEST VESSEL",
        ship_type=80,
        data_provenance=DataProvenance.SYNTHETIC,
    )
    assert identity_completeness_of(message) == pytest.approx(0.4)


# --------------------------------------------------------------------------- contract
@pytest.mark.parametrize(
    "kwargs",
    [
        {"position_count": -1},
        {"total_positions": -1},
        {"rejected_positions": -1},
        {"rejected_positions": 900, "total_positions": 100},
        {"window_hours": -1.0},
        {"max_gap_minutes": -1.0},
    ],
)
def test_impossible_inputs_raise_rather_than_producing_a_plausible_score(
    kwargs: dict[str, float],
) -> None:
    with pytest.raises(ValueError):
        breakdown(**kwargs)  # type: ignore[arg-type]


def test_the_breakdown_explains_itself() -> None:
    result = breakdown()
    assert set(result.as_dict()) == {*RELIABILITY_WEIGHTS, "total"}
    assert len(result.explanations()) == 5
    assert all(":" in line for line in result.explanations())
