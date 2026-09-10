"""Track cleaning (FR-012, P17-001…P17-007).

Cleaning here means *annotating*, not deleting.  Every message that arrives comes back
out, in time order, carrying a verdict and — when the verdict is negative — a sentence
saying why.  Deleting a suspect position would destroy evidence and, worse, would make
the deletion itself invisible: an analyst could never tell a quiet vessel from a quiet
filter.  The database enforces the same discipline with ``is_valid`` and a reason
column rather than a ``DELETE``.

Order matters.  Each rule assumes the previous one has run, and each sequence rule
compares against the last position still considered valid, so a single corrupt fix
cannot poison the fixes after it.

The functions here are pure: same messages plus same ``now`` gives the same verdicts,
in a test, in a re-run, and in an evidence report six months later.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from spilltrace.core.ais.constants import (
    COG_CONSISTENCY_MAX_DEVIATION_DEG,
    COG_CONSISTENCY_MIN_DISPLACEMENT_M,
    COG_CONSISTENCY_MIN_SOG_KNOTS,
    DEDUP_COORDINATE_DECIMALS,
    MAX_ACCELERATION_MS2,
    MAX_IMPLIED_SOG_KNOTS,
    MAX_REPORTED_SOG_KNOTS,
    SAME_INSTANT_DISPLACEMENT_TOLERANCE_M,
)
from spilltrace.core.ais.validate import ensure_utc, validate_coordinates, validate_timestamp
from spilltrace.core.enums import AISQualityFlag
from spilltrace.core.geometry import (
    angular_difference_deg,
    haversine_m,
    initial_bearing_deg,
    knots_to_ms,
    ms_to_knots,
)
from spilltrace.core.ports import AISMessage


@dataclass(slots=True)
class CleanedPosition:
    """One AIS message plus the cleaner's verdict on it.

    ``flags`` accumulates every observation made about the position, even after it has
    been rejected, because the *combination* of flags is what identifies a failure mode
    — a duplicate that is also a null island is a broken decoder, not a busy port.

    ``rejection_reason`` holds the **first** reason the position was rejected.  The
    first rule to fire is the one that explains it; the later ones are consequences.
    """

    message: AISMessage
    is_valid: bool = True
    flags: list[AISQualityFlag] = field(default_factory=list)
    rejection_reason: str | None = None

    @property
    def mmsi(self) -> int:
        return self.message.mmsi

    @property
    def timestamp(self) -> datetime:
        """Always aware UTC, so ordering and Δt never depend on where a row came from."""
        return ensure_utc(self.message.timestamp)

    @property
    def latitude(self) -> float:
        return self.message.latitude

    @property
    def longitude(self) -> float:
        return self.message.longitude

    @property
    def sog_knots(self) -> float | None:
        return self.message.sog_knots

    @property
    def cog_deg(self) -> float | None:
        return self.message.cog_deg

    def flag(self, flag: AISQualityFlag) -> None:
        """Record an observation without changing the verdict."""
        if flag not in self.flags:
            self.flags.append(flag)

    def reject(self, flag: AISQualityFlag, reason: str) -> None:
        """Mark the position unusable, keeping it and the reason it failed."""
        self.flag(flag)
        self.is_valid = False
        if self.rejection_reason is None:
            self.rejection_reason = reason


def _speed_ms(position: CleanedPosition) -> float | None:
    """Reported speed in m/s, or ``None`` when the vessel did not report one."""
    if position.sog_knots is None:
        return None
    return knots_to_ms(position.sog_knots)


def _kinematic_limit_m(speed_ms: float, dt_seconds: float) -> float:
    """Furthest a vessel at ``speed_ms`` could get in ``dt_seconds``.

    ``v·Δt + ½·a_max·Δt²`` (Sinni & Kyriazanos).  The acceleration term makes the bound
    generous for long intervals on purpose: over half an hour almost any displacement is
    physically reachable, and pretending otherwise would reject real tracks.
    """
    return speed_ms * dt_seconds + 0.5 * MAX_ACCELERATION_MS2 * dt_seconds**2


def _dedup_key(position: CleanedPosition) -> tuple[int, int, float, float]:
    """Identity of a fix for duplicate purposes.

    Time is bucketed to the second and coordinates to five decimals because AISStream
    re-delivers the same report with a different sub-second *receipt* time (AD-21);
    treating those as distinct fixes would inflate density and coverage — the two
    statistics that are supposed to measure how much we actually saw.
    """
    return (
        position.mmsi,
        int(position.timestamp.timestamp()),
        round(position.latitude, DEDUP_COORDINATE_DECIMALS),
        round(position.longitude, DEDUP_COORDINATE_DECIMALS),
    )


def _deduplicate(positions: Sequence[CleanedPosition]) -> None:
    seen: set[tuple[int, int, float, float]] = set()
    for position in positions:
        key = _dedup_key(position)
        if key in seen:
            position.reject(
                AISQualityFlag.DUPLICATE,
                "Identical MMSI, second and position as an earlier message in this track.",
            )
            continue
        seen.add(key)


def _check_coordinates(positions: Sequence[CleanedPosition]) -> None:
    for position in positions:
        if not position.is_valid:
            continue
        ok, flags = validate_coordinates(position.latitude, position.longitude)
        if ok:
            continue
        for flag in flags:
            position.flag(flag)
        if AISQualityFlag.NULL_ISLAND in flags:
            reason = "Position is exactly (0, 0), which decoders emit when they have no fix."
        elif AISQualityFlag.SENTINEL_POSITION in flags:
            reason = "Position is the AIS 'not available' sentinel (latitude 91 / longitude 181)."
        else:
            reason = "Latitude or longitude is outside the valid range."
        position.reject(flags[0], reason)


def _check_timestamps(positions: Sequence[CleanedPosition], *, now: datetime) -> None:
    for position in positions:
        if not position.is_valid:
            continue
        ok, flags = validate_timestamp(position.timestamp, now=now)
        if ok:
            continue
        for flag in flags:
            position.flag(flag)
        if AISQualityFlag.FUTURE_TIMESTAMP in flags:
            reason = "Timestamp is more than five minutes in the future of the analysis clock."
        else:
            reason = "Timestamp is at or before the Unix epoch, or predates AIS itself."
        position.reject(flags[0], reason)


def _check_reported_speed(positions: Sequence[CleanedPosition]) -> None:
    for position in positions:
        if not position.is_valid or position.sog_knots is None:
            continue
        if position.sog_knots > MAX_REPORTED_SOG_KNOTS:
            position.reject(
                AISQualityFlag.IMPLAUSIBLE_SOG,
                f"Reported speed {position.sog_knots:.1f} kn exceeds the "
                f"{MAX_REPORTED_SOG_KNOTS:.0f} kn plausibility limit for surface vessels.",
            )


def _check_implied_speed(positions: Sequence[CleanedPosition]) -> None:
    """Reject fixes that could only be reached by travelling faster than any ship.

    Compared against the last *valid* fix, not the previous row: otherwise one bad
    position would drag its innocent successor over the threshold as well.
    """
    previous: CleanedPosition | None = None
    for position in positions:
        if not position.is_valid:
            continue
        if previous is None:
            previous = position
            continue

        dt_seconds = (position.timestamp - previous.timestamp).total_seconds()
        distance_m = haversine_m(
            previous.longitude, previous.latitude, position.longitude, position.latitude
        )
        if dt_seconds <= 0.0:
            if distance_m > SAME_INSTANT_DISPLACEMENT_TOLERANCE_M:
                position.reject(
                    AISQualityFlag.IMPOSSIBLE_JUMP,
                    f"Two positions {distance_m:.0f} m apart share one instant; a single "
                    "MMSI cannot be in two places at once.",
                )
                continue
            previous = position
            continue

        implied_knots = ms_to_knots(distance_m / dt_seconds)
        if implied_knots > MAX_IMPLIED_SOG_KNOTS:
            position.reject(
                AISQualityFlag.IMPOSSIBLE_JUMP,
                f"Reaching this position from the previous valid fix would require "
                f"{implied_knots:.1f} kn, above the {MAX_IMPLIED_SOG_KNOTS:.0f} kn "
                "impossible-jump threshold.",
            )
            continue
        previous = position


def _kinematic_rejection_reason(
    previous: CleanedPosition,
    current: CleanedPosition,
    following: CleanedPosition | None,
    *,
    speed_before_ms: float | None,
) -> str | None:
    """Why ``current`` looks like a bad fix rather than a manoeuvre, or ``None``.

    ``None`` covers both "consistent" and "cannot tell": without a previous speed, a
    positive Δt or a following segment there is nothing to corroborate against, and an
    unevaluable check must not become a rejection.
    """
    dt_in = (current.timestamp - previous.timestamp).total_seconds()
    if speed_before_ms is None or dt_in <= 0.0 or following is None:
        return None

    distance_in = haversine_m(
        previous.longitude, previous.latitude, current.longitude, current.latitude
    )
    limit_in = _kinematic_limit_m(speed_before_ms, dt_in)
    if distance_in <= limit_in:
        return None

    # The vessel's *reported* speed at the suspect fix, never the speed implied through
    # it: a bad fix would otherwise supply the very speed that excuses it.
    speed_at_current_ms = _speed_ms(current)
    if speed_at_current_ms is None:
        speed_at_current_ms = speed_before_ms

    dt_out = (following.timestamp - current.timestamp).total_seconds()
    if dt_out <= 0.0:
        return None
    distance_out = haversine_m(
        current.longitude, current.latitude, following.longitude, following.latitude
    )
    if distance_out <= _kinematic_limit_m(speed_at_current_ms, dt_out):
        # Only the incoming segment is impossible: a manoeuvre, or a stale speed field.
        return None

    return (
        f"Displacement of {distance_in:.0f} m in {dt_in:.0f} s exceeds the "
        f"{limit_in:.0f} m reachable at the previous reported speed, and the following "
        f"segment ({distance_out:.0f} m in {dt_out:.0f} s) is impossible too - the "
        "signature of one bad fix rather than a manoeuvre."
    )


def _check_kinematics(positions: Sequence[CleanedPosition]) -> None:
    """Flag fixes that break the acceleration bound on **two** consecutive segments.

    This is the subtle rule (AD-23).  A single corrupt fix sits off the track, so the
    leg into it *and* the leg back out of it are both impossible.  A genuine manoeuvre -
    or a stale speed field on the previous report - breaks only the leg into it, and the
    vessel then behaves consistently afterwards.  Correcting on one violation therefore
    deletes real course changes, which is why the following segment is checked first.

    One consequence is deliberate: the last fix in a track is never rejected by this
    rule, because there is no following segment to corroborate it.  The implied-speed
    rule remains the backstop for gross errors there.
    """
    valid = [position for position in positions if position.is_valid]
    if len(valid) < 3:
        return

    kept: list[CleanedPosition] = [valid[0]]
    last_known_speed_ms = _speed_ms(valid[0])

    for index in range(1, len(valid)):
        current = valid[index]
        previous = kept[-1]
        following = valid[index + 1] if index + 1 < len(valid) else None

        speed_before_ms = _speed_ms(previous)
        if speed_before_ms is None:
            speed_before_ms = last_known_speed_ms

        reason = _kinematic_rejection_reason(
            previous, current, following, speed_before_ms=speed_before_ms
        )
        if reason is not None:
            current.reject(AISQualityFlag.KINEMATIC_OUTLIER, reason)
            continue

        kept.append(current)
        speed_now = _speed_ms(current)
        if speed_now is not None:
            last_known_speed_ms = speed_now


def _check_cog_consistency(positions: Sequence[CleanedPosition]) -> None:
    """Flag — but do not reject — a course that contradicts the observed bearing.

    A disagreement discredits the ``COG`` *field*, not the fix: the vessel was still
    somewhere, and throwing the position away would delete a real observation to punish
    a bad number.  Downstream consumers that use ``COG`` check for the flag.
    """
    previous: CleanedPosition | None = None
    for position in positions:
        if not position.is_valid:
            continue
        if previous is None:
            previous = position
            continue

        speed = position.sog_knots
        distance_m = haversine_m(
            previous.longitude, previous.latitude, position.longitude, position.latitude
        )
        if (
            position.cog_deg is not None
            and speed is not None
            and speed > COG_CONSISTENCY_MIN_SOG_KNOTS
            and distance_m > COG_CONSISTENCY_MIN_DISPLACEMENT_M
        ):
            bearing = initial_bearing_deg(
                previous.longitude, previous.latitude, position.longitude, position.latitude
            )
            deviation = angular_difference_deg(position.cog_deg, bearing)
            if deviation > COG_CONSISTENCY_MAX_DEVIATION_DEG:
                position.flag(AISQualityFlag.COG_INCONSISTENT)
        previous = position


def clean_track(messages: Sequence[AISMessage], *, now: datetime) -> list[CleanedPosition]:
    """Clean one vessel's messages, returning every one of them in time order.

    ``now`` is a parameter, not ``datetime.now()``: cleaning must be reproducible, and a
    rule that reads the wall clock silently changes its verdicts between runs.

    All messages must share an MMSI.  Mixing vessels would make every sequence rule
    compare one ship's position against another's — a silent corruption that produces
    plausible-looking nonsense, so it fails loudly instead.
    """
    if not messages:
        return []

    distinct_mmsi = {message.mmsi for message in messages}
    if len(distinct_mmsi) > 1:
        raise ValueError(
            f"clean_track expects one vessel's messages; got {len(distinct_mmsi)} MMSIs. "
            "Group by MMSI before cleaning."
        )

    # ``sorted`` is stable, so messages sharing a timestamp keep the order the feed
    # delivered them and the result never depends on sort internals.
    positions = sorted(
        (CleanedPosition(message=message) for message in messages),
        key=lambda position: position.timestamp,
    )

    _deduplicate(positions)
    _check_coordinates(positions)
    _check_timestamps(positions, now=now)
    _check_reported_speed(positions)
    _check_implied_speed(positions)
    _check_kinematics(positions)
    _check_cog_consistency(positions)
    return positions


def cleaning_summary(positions: Sequence[CleanedPosition]) -> dict[str, int]:
    """Counts per outcome, for the honest-coverage reporting required by CON-007.

    An analyst needs to know whether a thin track means a quiet vessel or a noisy feed,
    and that difference is only visible if rejections are counted and shown.
    """
    summary = {
        "total": len(positions),
        "valid": sum(1 for position in positions if position.is_valid),
        "rejected": sum(1 for position in positions if not position.is_valid),
    }
    for flag in AISQualityFlag:
        count = sum(1 for position in positions if flag in position.flags)
        if count:
            summary[flag.value] = count
    return summary


__all__ = ["CleanedPosition", "clean_track", "cleaning_summary"]
