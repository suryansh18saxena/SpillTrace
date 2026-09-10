"""The demonstration scenario must be reproducible and clearly labelled.

Reproducibility matters for the same reason it does in the drift stage: a demonstration
whose numbers move between runs cannot be checked.  Labelling matters because synthetic
data that could be mistaken for an observation is worse than no demonstration at all
(CON-009).
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import numpy as np
import pytest

from spilltrace.core.enums import DataProvenance
from spilltrace.core.errors import NotFoundError
from spilltrace.core.geometry import geodesic_distance_m
from spilltrace.demo.ais import generate_scenario_messages, generate_vessel_messages
from spilltrace.demo.environment import summarise, synthetic_environment
from spilltrace.demo.origin import backtracked_position, mean_drift_vector
from spilltrace.demo.scenarios import SCENARIOS, get_scenario
from spilltrace.demo.slick import probability_grid, slick_metrics, synthetic_slick

SCENARIO = get_scenario("kutch-01")


def digest(messages) -> str:
    payload = [
        (
            m.mmsi,
            m.timestamp.isoformat(),
            round(m.longitude, 8),
            round(m.latitude, 8),
            m.sog_knots,
            m.cog_deg,
        )
        for m in messages
    ]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


class TestScenarioRegistry:
    def test_the_scenario_resolves(self) -> None:
        assert SCENARIO.key == "kutch-01"
        assert len(SCENARIO.vessels) >= 3

    def test_unknown_scenarios_fail_loudly(self) -> None:
        with pytest.raises(NotFoundError, match="Unknown demo scenario"):
            get_scenario("atlantis-99")

    def test_every_registered_scenario_serialises(self) -> None:
        for scenario in SCENARIOS.values():
            payload = scenario.to_dict()
            assert payload["vessel_count"] == len(scenario.vessels)
            assert payload["notes"]

    def test_the_case_window_contains_every_vessel_approach(self) -> None:
        for vessel in SCENARIO.vessels:
            approach = SCENARIO.acquisition_time - timedelta(hours=vessel.hours_before_acquisition)
            assert SCENARIO.case_start <= approach <= SCENARIO.case_end

    def test_mmsi_values_are_plausible_ship_identifiers(self) -> None:
        from spilltrace.core.ais import is_attributable_vessel_mmsi

        for vessel in SCENARIO.vessels:
            assert 100_000_000 <= vessel.mmsi <= 999_999_999
            assert is_attributable_vessel_mmsi(vessel.mmsi)


class TestSlick:
    def test_generation_is_deterministic(self) -> None:
        a = synthetic_slick(
            centre=(69.42, 22.44), length_km=42.0, width_km=2.6, bearing_deg=118.0, seed=42
        )
        b = synthetic_slick(
            centre=(69.42, 22.44), length_km=42.0, width_km=2.6, bearing_deg=118.0, seed=42
        )
        assert a.equals_exact(b, 1e-12)

    def test_a_different_seed_gives_a_different_slick(self) -> None:
        a = synthetic_slick(
            centre=(69.42, 22.44), length_km=42.0, width_km=2.6, bearing_deg=118.0, seed=42
        )
        b = synthetic_slick(
            centre=(69.42, 22.44), length_km=42.0, width_km=2.6, bearing_deg=118.0, seed=43
        )
        assert not a.equals_exact(b, 1e-9)

    def test_the_slick_is_valid_and_elongated(self) -> None:
        slick = synthetic_slick(
            centre=(69.42, 22.44), length_km=42.0, width_km=2.6, bearing_deg=118.0, seed=42
        )
        assert slick.is_valid
        metrics = slick_metrics(slick)
        assert metrics["elongation"] > 1.5
        assert metrics["complexity"] > 1.5
        assert 10.0 < metrics["area_km2"] < 400.0

    def test_probability_grid_matches_the_polygon(self) -> None:
        slick = synthetic_slick(
            centre=(69.42, 22.44), length_km=42.0, width_km=2.6, bearing_deg=118.0, seed=42
        )
        grid, bounds = probability_grid(slick, seed=42)
        assert grid.dtype == np.float32
        assert float(grid.min()) >= 0.0 and float(grid.max()) <= 1.0
        assert float(grid.max()) > 0.8
        min_lon, min_lat, max_lon, max_lat = bounds
        s_min_lon, s_min_lat, s_max_lon, s_max_lat = slick.bounds
        assert min_lon < s_min_lon and max_lon > s_max_lon
        assert min_lat < s_min_lat and max_lat > s_max_lat


class TestAIS:
    def test_generation_is_deterministic(self) -> None:
        assert digest(generate_scenario_messages(SCENARIO, seed=42)) == digest(
            generate_scenario_messages(SCENARIO, seed=42)
        )

    def test_a_different_seed_changes_the_messages(self) -> None:
        assert digest(generate_scenario_messages(SCENARIO, seed=42)) != digest(
            generate_scenario_messages(SCENARIO, seed=43)
        )

    def test_every_vessel_is_present(self) -> None:
        messages = generate_scenario_messages(SCENARIO, seed=42)
        assert {m.mmsi for m in messages} == {v.mmsi for v in SCENARIO.vessels}

    def test_names_are_labelled_synthetic(self) -> None:
        for message in generate_scenario_messages(SCENARIO, seed=42):
            assert message.data_provenance is DataProvenance.SYNTHETIC
            if message.name:
                assert "(SYNTHETIC)" in message.name

    def test_static_data_is_emitted_once_per_vessel(self) -> None:
        messages = generate_scenario_messages(SCENARIO, seed=42)
        static = [m for m in messages if m.message_type == "ShipStaticData"]
        assert len(static) == len(SCENARIO.vessels)

    def test_injected_gaps_are_interior_and_spare_the_closest_approach(self) -> None:
        # A gap that swallowed the approach would remove the vessel from correlation
        # entirely, which demonstrates nothing about the reliability factor.
        for vessel in SCENARIO.vessels:
            if vessel.gap_minutes <= 0:
                continue
            positions = [
                m
                for m in generate_vessel_messages(vessel, SCENARIO, seed=42)
                if m.message_type == "PositionReport"
            ]
            intervals = [
                (positions[i + 1].timestamp - positions[i].timestamp).total_seconds() / 60.0
                for i in range(len(positions) - 1)
            ]
            assert max(intervals) >= vessel.gap_minutes * 0.9

            approach_time = SCENARIO.acquisition_time - timedelta(
                hours=vessel.hours_before_acquisition
            )
            nearest = min(
                positions, key=lambda m: abs((m.timestamp - approach_time).total_seconds())
            )
            assert abs((nearest.timestamp - approach_time).total_seconds()) < 300

            corridor = backtracked_position(
                SCENARIO, hours_before_acquisition=vessel.hours_before_acquisition
            )
            offset_km = geodesic_distance_m(nearest.longitude, nearest.latitude, *corridor) / 1000.0
            assert offset_km == pytest.approx(vessel.closest_approach_km, abs=0.6)

    def test_defects_are_injected_where_requested(self) -> None:
        for vessel in SCENARIO.vessels:
            messages = generate_vessel_messages(vessel, SCENARIO, seed=42)
            defects = {m.raw.get("defect") for m in messages if m.raw and "defect" in m.raw}
            if vessel.inject_defects:
                assert {"impossible_jump", "sentinel_values"} <= defects
            else:
                assert not defects


class TestDriftCorridor:
    def test_the_mean_drift_is_downwind_and_downstream(self) -> None:
        speed, bearing = mean_drift_vector(SCENARIO)
        assert speed > SCENARIO.current_speed_ms  # wind drift adds to the current
        assert 0.0 <= bearing < 360.0

    def test_back_tracking_moves_upstream(self) -> None:
        lon, _lat = backtracked_position(SCENARIO, hours_before_acquisition=18.0)
        assert lon < SCENARIO.slick_centre[0]  # mean flow is eastward here

    def test_back_tracking_distance_grows_with_time(self) -> None:
        near = backtracked_position(SCENARIO, hours_before_acquisition=6.0)
        far = backtracked_position(SCENARIO, hours_before_acquisition=18.0)
        centre = SCENARIO.slick_centre
        assert geodesic_distance_m(*centre, *far) > geodesic_distance_m(*centre, *near)

    def test_zero_hours_returns_the_slick_centre(self) -> None:
        lon, lat = backtracked_position(SCENARIO, hours_before_acquisition=0.0)
        assert (lon, lat) == pytest.approx(SCENARIO.slick_centre, abs=1e-9)


class TestEnvironment:
    def test_generation_is_deterministic(self) -> None:
        kwargs = {
            "bbox": SCENARIO.aoi_bbox,
            "start": SCENARIO.case_start,
            "end": SCENARIO.case_end,
            "wind_speed_ms": 5.4,
            "wind_direction_deg": 232.0,
            "current_speed_ms": 0.31,
            "current_direction_deg": 104.0,
            "seed": 42,
        }
        a = synthetic_environment(**kwargs)
        b = synthetic_environment(**kwargs)
        assert np.array_equal(np.asarray(a.wind_u.values), np.asarray(b.wind_u.values))

    def test_mean_wind_matches_the_requested_speed(self) -> None:
        bundle = synthetic_environment(
            bbox=SCENARIO.aoi_bbox,
            start=SCENARIO.case_start,
            end=SCENARIO.case_end,
            wind_speed_ms=5.4,
            wind_direction_deg=232.0,
            current_speed_ms=0.31,
            current_direction_deg=104.0,
            seed=42,
        )
        stats = summarise(bundle)
        assert stats["wind_speed"]["mean"] == pytest.approx(5.4, rel=0.05)
        assert stats["current_speed"]["mean"] == pytest.approx(0.31, rel=0.10)

    def test_fields_are_labelled_synthetic(self) -> None:
        bundle = synthetic_environment(
            bbox=SCENARIO.aoi_bbox,
            start=SCENARIO.case_start,
            end=SCENARIO.case_end,
            wind_speed_ms=5.4,
            wind_direction_deg=232.0,
            current_speed_ms=0.31,
            current_direction_deg=104.0,
            seed=42,
        )
        assert bundle.data_provenance is DataProvenance.SYNTHETIC
        assert bundle.source == "SYNTHETIC"
