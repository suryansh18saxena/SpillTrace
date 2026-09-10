"""Scenario definitions.

A scenario fixes the geography, timing and cast of vessels.  The seed fixes every random
draw within it.  Together they make a demonstration reproducible, which matters because
the same reproducibility machinery is what AC-07 requires of real drift runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from spilltrace.core.errors import NotFoundError


@dataclass(frozen=True, slots=True)
class VesselProfile:
    """A vessel in the scenario, and the role it plays in the evidence picture."""

    mmsi: int
    name: str
    ship_type: int
    ship_type_name: str
    flag_country: str
    length_m: float
    width_m: float
    #: Perpendicular distance in km from the drift corridor at closest approach.
    closest_approach_km: float
    #: Hours before the scene acquisition at which the vessel makes that approach.  The
    #: approach *position* is the back-tracked location of the oil at that same moment,
    #: so a vessel with a small offset here is genuinely where a discharge would have
    #: had to happen to produce the observed slick.
    hours_before_acquisition: float
    #: Course over ground held through the area, degrees true.
    course_deg: float
    speed_knots: float
    #: Reporting gap injected into this vessel's track, in minutes (0 = none).
    gap_minutes: float = 0.0
    #: Whether to inject duplicate messages and one impossible position jump, so the
    #: cleaning stage has something real to remove.
    inject_defects: bool = False
    imo: int | None = None
    role: str = ""


@dataclass(frozen=True, slots=True)
class Scenario:
    key: str
    title: str
    description: str
    #: (min_lon, min_lat, max_lon, max_lat)
    aoi_bbox: tuple[float, float, float, float]
    #: Where the slick is observed.
    slick_centre: tuple[float, float]
    slick_length_km: float
    slick_width_km: float
    slick_bearing_deg: float
    #: Scene acquisition time — the moment the slick was observed.
    acquisition_time: datetime
    #: Hours before acquisition that the discharge is presumed to have happened.
    discharge_lag_hours: float
    wind_speed_ms: float
    wind_direction_deg: float
    current_speed_ms: float
    current_direction_deg: float
    vessels: tuple[VesselProfile, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def case_start(self) -> datetime:
        # Wide enough to contain the earliest vessel offset relative to the back-tracked
        # origin time, with room to spare; a window that clipped a track would make the
        # scenario's intent unreachable.
        earliest = max((v.hours_before_acquisition for v in self.vessels), default=0.0)
        return self.acquisition_time - timedelta(hours=earliest + 8.0)

    @property
    def case_end(self) -> datetime:
        return self.acquisition_time + timedelta(hours=6)

    @property
    def discharge_time(self) -> datetime:
        return self.acquisition_time - timedelta(hours=self.discharge_lag_hours)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "aoi_bbox": list(self.aoi_bbox),
            "acquisition_time": self.acquisition_time.isoformat(),
            "vessel_count": len(self.vessels),
            "notes": list(self.notes),
        }


#: Gulf of Kutch — a busy Indian tanker approach with a plausible discharge geometry.
#: Chosen because it is exactly the kind of water the PRD targets, and because it gives
#: a realistic mix of strong, weak and irrelevant candidates.
KUTCH_01 = Scenario(
    key="kutch-01",
    title="Gulf of Kutch — suspected operational discharge",
    description=(
        "A 42 km oil-like slick observed by Sentinel-1 south-west of the Gulf of Kutch "
        "approaches. Six vessels were transiting the area within the inferred discharge "
        "window."
    ),
    aoi_bbox=(68.60, 21.90, 70.40, 23.10),
    slick_centre=(69.42, 22.44),
    slick_length_km=42.0,
    slick_width_km=2.6,
    slick_bearing_deg=118.0,
    acquisition_time=datetime(2026, 8, 14, 1, 12, 0, tzinfo=UTC),
    discharge_lag_hours=18.0,
    wind_speed_ms=5.4,  # inside the 4-10 m/s detection window
    wind_direction_deg=232.0,  # south-westerly, typical late monsoon
    current_speed_ms=0.31,
    current_direction_deg=104.0,
    vessels=(
        VesselProfile(
            mmsi=419008412,
            imo=9542871,
            name="SAGAR PRABHA",
            ship_type=80,
            ship_type_name="Tanker",
            flag_country="India",
            length_m=183.0,
            width_m=32.2,
            closest_approach_km=1.4,
            hours_before_acquisition=13.5,
            course_deg=121.0,
            speed_knots=11.2,
            role="strong: inside the high-probability contour, inside the time window",
        ),
        VesselProfile(
            mmsi=477203900,
            imo=9310074,
            name="EASTERN ORCHID",
            ship_type=70,
            ship_type_name="Cargo",
            flag_country="Hong Kong",
            length_m=229.0,
            width_m=32.3,
            closest_approach_km=7.9,
            hours_before_acquisition=12.0,
            course_deg=104.0,
            speed_knots=13.6,
            gap_minutes=95.0,
            role="moderate: nearby and roughly contemporaneous, with a reporting gap",
        ),
        VesselProfile(
            mmsi=636019284,
            imo=9411660,
            name="ATLANTIC MERIDIAN",
            ship_type=80,
            ship_type_name="Tanker",
            flag_country="Liberia",
            length_m=250.0,
            width_m=44.0,
            closest_approach_km=11.2,
            hours_before_acquisition=15.5,
            course_deg=298.0,
            speed_knots=12.9,
            inject_defects=True,
            role="moderate: outbound on a reciprocal course, noisy AIS",
        ),
        VesselProfile(
            mmsi=419002315,
            imo=None,
            name="MATSYA VII",
            ship_type=30,
            ship_type_name="Fishing",
            flag_country="India",
            length_m=24.0,
            width_m=6.4,
            closest_approach_km=4.0,
            hours_before_acquisition=17.6,
            course_deg=40.0,
            speed_knots=4.1,
            gap_minutes=840.0,
            role=(
                "weak: passes closer than rank 2 but at the edge of the inferred "
                "window, and carries a long AIS gap"
            ),
        ),
        VesselProfile(
            mmsi=538008122,
            imo=9702320,
            name="PACIFIC HALCYON",
            ship_type=70,
            ship_type_name="Cargo",
            flag_country="Marshall Islands",
            length_m=199.0,
            width_m=32.3,
            closest_approach_km=34.0,
            hours_before_acquisition=13.0,
            course_deg=76.0,
            speed_knots=15.1,
            role="excluded: right time, far outside the origin region",
        ),
        VesselProfile(
            mmsi=563145700,
            imo=9356963,
            name="STRAITS VOYAGER",
            ship_type=80,
            ship_type_name="Tanker",
            flag_country="Singapore",
            length_m=176.0,
            width_m=31.0,
            closest_approach_km=27.0,
            hours_before_acquisition=27.0,
            course_deg=252.0,
            speed_knots=10.4,
            role="excluded: wrong place and wrong time — the control case",
        ),
    ),
    notes=(
        "Wind at acquisition is 5.4 m/s, inside the 4-10 m/s window in which SAR oil "
        "detection is considered reliable.",
        "One vessel carries a 14-hour reporting gap. A gap is not evidence of "
        "wrongdoing; it lowers that vessel's AIS reliability factor.",
        "One vessel passes closer to the origin region than the second-ranked "
        "candidate does, but 13 hours outside the inferred window. It therefore ranks "
        "lower: proximity alone does not decide the outcome.",
        "Two vessels transit well outside the origin region and are correctly excluded "
        "from the candidate list rather than ranked last.",
    ),
)

SCENARIOS: dict[str, Scenario] = {KUTCH_01.key: KUTCH_01}


def get_scenario(key: str) -> Scenario:
    scenario = SCENARIOS.get(key)
    if scenario is None:
        raise NotFoundError(
            f"Unknown demo scenario '{key}'.", available=sorted(SCENARIOS), scenario=key
        )
    return scenario


__all__ = ["KUTCH_01", "SCENARIOS", "Scenario", "VesselProfile", "get_scenario"]
