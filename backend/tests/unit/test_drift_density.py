"""Reverse drift, particle density and the origin probability region.

AC-07 requires a *reproducible* origin region, so determinism is tested by hashing the
result rather than by eyeballing it.  CON-008 requires the output to be a region, so the
nesting and monotonicity of the probability contours are tested too.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import numpy as np
import pytest
from shapely.geometry import mapping

from spilltrace.adapters.drift.analytical import AnalyticalDriftEngine
from spilltrace.core.density import (
    DEFAULT_CONTOUR_LEVELS,
    containing_probability,
    contour_polygons,
    contours_to_geojson,
    density_threshold_for_mass,
    particle_density,
    probability_contours,
)
from spilltrace.core.enums import DriftMode
from spilltrace.core.geometry import geodesic_area_km2, geodesic_distance_m
from spilltrace.demo.environment import synthetic_environment
from spilltrace.demo.slick import synthetic_slick

START = datetime(2026, 8, 14, 1, 12, tzinfo=UTC)
BBOX = (68.6, 21.9, 70.4, 23.1)
SLICK = synthetic_slick(
    centre=(69.42, 22.44), length_km=42.0, width_km=2.6, bearing_deg=118.0, seed=42
)


def environment(seed: int = 42):
    return synthetic_environment(
        bbox=BBOX,
        start=START - timedelta(hours=30),
        end=START + timedelta(hours=2),
        wind_speed_ms=5.4,
        wind_direction_deg=232.0,
        current_speed_ms=0.31,
        current_direction_deg=104.0,
        seed=seed,
    )


def run_drift(
    *,
    seed: int = 42,
    mode: DriftMode = DriftMode.BACKWARD,
    particles: int = 600,
    members: int = 2,
    hours: float = 12.0,
):
    engine = AnalyticalDriftEngine()
    return asyncio.run(
        engine.simulate(
            seed_geojson=mapping(SLICK),
            start_time=START,
            mode=mode,
            duration_hours=hours,
            time_step_seconds=900,
            number_of_particles=particles,
            environment=environment(),
            seed=seed,
            ensemble_members=members,
        )
    )


def fingerprint(result) -> str:
    payload = [
        (p.particle_id, p.step_index, round(p.lon, 9), round(p.lat, 9)) for p in result.particles
    ]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


class TestReproducibility:
    def test_identical_inputs_give_an_identical_run(self) -> None:
        # This is AC-07: an origin region an investigator cannot reproduce is not evidence.
        assert fingerprint(run_drift(seed=42)) == fingerprint(run_drift(seed=42))

    def test_a_different_seed_gives_a_different_run(self) -> None:
        assert fingerprint(run_drift(seed=42)) != fingerprint(run_drift(seed=43))

    def test_the_seed_is_recorded_on_the_result(self) -> None:
        assert run_drift(seed=7).seed == 7

    def test_parameters_are_recorded_for_reproduction(self) -> None:
        params = run_drift().parameters
        for key in (
            "wind_drift_factor",
            "horizontal_diffusivity",
            "time_step_seconds",
            "duration_hours",
            "ensemble_members",
        ):
            assert key in params


class TestDirection:
    def test_backward_runs_go_back_in_time(self) -> None:
        result = run_drift(mode=DriftMode.BACKWARD)
        assert result.times[-1] < result.times[0]
        assert result.times[0] == START

    def test_forward_runs_go_forward_in_time(self) -> None:
        result = run_drift(mode=DriftMode.FORWARD)
        assert result.times[-1] > result.times[0]

    def test_backward_displacement_opposes_forward(self) -> None:
        forward = run_drift(mode=DriftMode.FORWARD, members=1, particles=200)
        backward = run_drift(mode=DriftMode.BACKWARD, members=1, particles=200)

        def mean_end(result) -> tuple[float, float]:
            last = max(p.step_index for p in result.particles)
            ends = [p for p in result.particles if p.step_index == last]
            return (
                float(np.mean([p.lon for p in ends])),
                float(np.mean([p.lat for p in ends])),
            )

        start_lon = SLICK.centroid.x
        f_lon, _ = mean_end(forward)
        b_lon, _ = mean_end(backward)
        # The mean flow is eastward, so forward drifts east of the seed and backward west.
        assert f_lon > start_lon > b_lon


class TestHonesty:
    def test_the_engine_states_what_it_does_not_model(self) -> None:
        notes = " ".join(run_drift().notes).lower()
        for omitted in ("weathering", "evaporation", "stokes"):
            assert omitted in notes

    def test_provenance_follows_the_forcing(self) -> None:
        assert str(run_drift().data_provenance) == "SYNTHETIC"

    def test_diffusion_spreads_the_cloud(self) -> None:
        result = run_drift(hours=18.0, members=1, particles=400)
        last = max(p.step_index for p in result.particles)
        first_spread = np.std([p.lon for p in result.particles if p.step_index == 0])
        last_spread = np.std([p.lon for p in result.particles if p.step_index == last])
        assert last_spread > first_spread


class TestDensity:
    @staticmethod
    def cloud(n: int = 6000, seed: int = 7):
        rng = np.random.default_rng(seed)
        return rng.normal(69.6, 0.06, n), rng.normal(22.4, 0.045, n)

    def test_density_normalises_to_one(self) -> None:
        grid = particle_density(*self.cloud(), resolution_deg=0.01)
        assert float(grid.values.sum()) == pytest.approx(1.0, abs=1e-9)

    def test_zero_particles_is_an_error_not_an_empty_region(self) -> None:
        with pytest.raises(ValueError, match="zero particles"):
            particle_density(np.array([]), np.array([]))

    def test_contours_are_nested(self) -> None:
        grid = particle_density(*self.cloud(), resolution_deg=0.01)
        contours = probability_contours(grid)
        assert [level for level, _ in contours] == sorted(DEFAULT_CONTOUR_LEVELS, reverse=True)
        for (outer_level, outer), (inner_level, inner) in pairwise(contours):
            assert outer_level > inner_level
            assert outer.covers(inner)
            assert geodesic_area_km2(outer) > geodesic_area_km2(inner)

    def test_higher_mass_needs_a_lower_threshold(self) -> None:
        grid = particle_density(*self.cloud(), resolution_deg=0.01)
        assert density_threshold_for_mass(grid, 0.9) < density_threshold_for_mass(grid, 0.5)

    def test_an_impossible_threshold_yields_an_empty_region(self) -> None:
        grid = particle_density(*self.cloud(), resolution_deg=0.01)
        assert contour_polygons(grid, threshold=1.0).is_empty

    def test_containing_probability_prefers_the_tightest_contour(self) -> None:
        grid = particle_density(*self.cloud(), resolution_deg=0.01)
        contours = probability_contours(grid)
        assert containing_probability(contours, 69.6, 22.4) == min(DEFAULT_CONTOUR_LEVELS)
        assert containing_probability(contours, 71.0, 24.0) is None

    def test_geojson_carries_the_probability_mass(self) -> None:
        grid = particle_density(*self.cloud(), resolution_deg=0.01)
        collection = contours_to_geojson(probability_contours(grid))
        assert collection["type"] == "FeatureCollection"
        masses = [f["properties"]["probability_mass"] for f in collection["features"]]
        assert masses == sorted(masses, reverse=True)
        for feature in collection["features"]:
            assert "% probability region" in feature["properties"]["label"]

    def test_a_region_is_produced_not_a_point(self) -> None:
        # CON-008: the answer must have extent.
        grid = particle_density(*self.cloud(), resolution_deg=0.01)
        tightest = probability_contours(grid)[-1][1]
        assert geodesic_area_km2(tightest) > 1.0


class TestEndToEndOrigin:
    def test_backtracked_region_lies_upstream_of_the_slick(self) -> None:
        result = run_drift(hours=18.0, particles=1200, members=3)
        last = max(p.step_index for p in result.particles)
        ends = [p for p in result.particles if p.step_index == last]
        grid = particle_density(
            np.array([p.lon for p in ends]), np.array([p.lat for p in ends]), resolution_deg=0.01
        )
        region = probability_contours(grid)[0][1]
        centroid = region.centroid
        # The mean flow is eastward, so the origin must be west of where the oil was seen.
        assert centroid.x < SLICK.centroid.x
        displacement_km = (
            geodesic_distance_m(SLICK.centroid.x, SLICK.centroid.y, centroid.x, centroid.y) / 1000.0
        )
        assert 10.0 < displacement_km < 60.0
