"""Field-level AIS validation: sentinels, identity, time and position.

This module is the boundary between "what the wire said" and "what we are willing to
call a measurement".  Its bias is deliberate and one-directional: when a field could be
either a value or an absence, it becomes an absence.  A ``NULL`` propagates honestly
through the rest of the pipeline; a fabricated number does not (CON-009).

Nothing here does I/O, and nothing here decides guilt — the flags are descriptive
(CON-002).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum

from spilltrace.core.ais.constants import (
    COG_SENTINEL_DEG,
    DIMENSION_AB_SENTINEL_M,
    DIMENSION_CD_SENTINEL_M,
    EPOCH_ZERO_UTC,
    ETA_DAY_SENTINEL,
    ETA_HOUR_SENTINEL,
    ETA_MINUTE_SENTINEL,
    ETA_MONTH_SENTINEL,
    FUTURE_TIMESTAMP_TOLERANCE_MINUTES,
    HEADING_SENTINEL_DEG,
    LATITUDE_SENTINEL_DEG,
    LONGITUDE_SENTINEL_DEG,
    MAX_LATITUDE_DEG,
    MAX_LONGITUDE_DEG,
    MAX_SECOND_OF_MINUTE,
    MIN_PLAUSIBLE_TIMESTAMP_UTC,
    MMSI_DIGITS,
    MMSI_MAX,
    MMSI_MID_MAX,
    MMSI_MID_MIN,
    MMSI_MIN,
    NULL_ISLAND_TOLERANCE_DEG,
    ROT_AIS_SCALE,
    ROT_SENTINEL,
    SHIP_TYPE_MAX,
    SHIP_TYPE_MIN,
    SOG_SENTINEL_KNOTS,
)
from spilltrace.core.enums import AISQualityFlag
from spilltrace.core.errors import ValidationError

Number = float | int


# --------------------------------------------------------------------------- helpers
def _finite(value: Number | None) -> float | None:
    """``value`` as a float, or ``None`` when it cannot be arithmetic.

    ``None``, NaN and ±inf all mean "no measurement".  Collapsing them here means no
    validator downstream has to remember that ``float("nan") < 30`` is ``False``.
    """
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def ensure_utc(moment: datetime) -> datetime:
    """Return ``moment`` as an aware UTC datetime.

    Naive input is *assumed* UTC rather than rejected: AIS is a UTC-only system and
    database drivers routinely hand back naive values.  Assuming a different zone would
    silently move vessels in time, which is far worse than an explicit assumption.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


# --------------------------------------------------------------------------- sentinels
def normalise_sog(raw: Number | None) -> float | None:
    """Speed over ground in knots, or ``None``.

    ``≥ 102.2`` is the ITU-R M.1371 "not available / at or above" encoding — a bound,
    not a speed — and a negative speed is a decoder fault.
    """
    value = _finite(raw)
    if value is None or value >= SOG_SENTINEL_KNOTS or value < 0.0:
        return None
    return value


def normalise_cog(raw: Number | None) -> float | None:
    """Course over ground in degrees, or ``None`` (``360`` means not available)."""
    value = _finite(raw)
    if value is None or value >= COG_SENTINEL_DEG or value < 0.0:
        return None
    return value


def normalise_heading(raw: Number | None) -> float | None:
    """True heading in degrees, or ``None`` (``511`` means not available)."""
    value = _finite(raw)
    if value is None or value == float(HEADING_SENTINEL_DEG) or not 0.0 <= value <= 359.0:
        return None
    return value


def normalise_latitude(raw: Number | None) -> float | None:
    """Latitude in degrees, or ``None`` (``91`` means not available)."""
    value = _finite(raw)
    if value is None or abs(value) > MAX_LATITUDE_DEG:
        return None
    return value


def normalise_longitude(raw: Number | None) -> float | None:
    """Longitude in degrees, or ``None`` (``181`` means not available)."""
    value = _finite(raw)
    if value is None or abs(value) > MAX_LONGITUDE_DEG:
        return None
    return value


def normalise_rot(raw: Number | None) -> float | None:
    """Rate-of-turn field as transmitted, or ``None``.

    ``-128`` is "not available".  ``±127`` means "turning faster than 5°/30 s, no turn
    indicator" — a saturated bound rather than a measurement, so it is dropped for the
    same reason the saturated dimension values are.  Anything outside the signed 8-bit
    field never came from an AIS decoder.
    """
    value = _finite(raw)
    if value is None or value == float(ROT_SENTINEL) or abs(value) >= 127.0:
        return None
    return value


def decode_rate_of_turn(raw: Number | None) -> float | None:
    """Decode the raw AIS rate-of-turn field to degrees per minute.

    ``ROT_AIS = 4.733·√(ROT_sensor)``, so the inverse is ``sign(x)·(x/4.733)²``.

    **UNCERTAIN (AD-22):** the AISStream schema types ``RateOfTurn`` as an integer but
    does not document whether the value is already decoded.  If it is, applying this
    function a second time is wrong.  The decoded value is therefore recorded for
    empirical validation only and **ROT is never used in scoring** — no attribution
    result may depend on a number whose units we cannot confirm.
    """
    value = normalise_rot(raw)
    if value is None:
        return None
    return math.copysign((abs(value) / ROT_AIS_SCALE) ** 2, value)


def normalise_second_of_minute(raw: Number | None) -> int | None:
    """UTC second of the position report, or ``None``.

    ``60``-``63`` are receiver status codes (not available, manual input, dead
    reckoning, inoperative); read as a time they would put the fix a minute late.
    """
    value = _finite(raw)
    if value is None or not 0 <= int(value) <= MAX_SECOND_OF_MINUTE:
        return None
    return int(value)


def normalise_ship_type(raw: Number | None) -> int | None:
    """Ship-and-cargo type code, or ``None`` (``0`` and ``> 99`` are not a type)."""
    value = _finite(raw)
    if value is None or not SHIP_TYPE_MIN <= int(value) <= SHIP_TYPE_MAX:
        return None
    return int(value)


def normalise_dimension(raw: Number | None, *, sentinel: float) -> float | None:
    """A reference-point dimension in metres, or ``None``.

    ``511`` (A/B) and ``63`` (C/D) mean "at or above" — a saturated bound.  Storing the
    bound as if it were the hull dimension would silently shrink large vessels.
    """
    value = _finite(raw)
    if value is None or value < 0.0 or value >= sentinel:
        return None
    return value


@dataclass(frozen=True, slots=True)
class ETAParts:
    """The four ETA fields, each independently present or absent."""

    month: int | None = None
    day: int | None = None
    hour: int | None = None
    minute: int | None = None

    @property
    def is_complete(self) -> bool:
        return None not in (self.month, self.day, self.hour, self.minute)


def normalise_eta(
    *,
    month: Number | None = None,
    day: Number | None = None,
    hour: Number | None = None,
    minute: Number | None = None,
) -> ETAParts:
    """Normalise the ETA fields, each of which has its own "not available" encoding.

    They are normalised independently because AIS transmits them independently: a
    vessel may broadcast a valid day with an unset hour, and collapsing the whole ETA to
    ``None`` would discard information we actually received.
    """

    def _keep(raw: Number | None, sentinel: int, low: int, high: int) -> int | None:
        number = _finite(raw)
        if number is None:
            return None
        value = int(number)
        if value == sentinel or not low <= value <= high:
            return None
        return value

    return ETAParts(
        month=_keep(month, ETA_MONTH_SENTINEL, 1, 12),
        day=_keep(day, ETA_DAY_SENTINEL, 1, 31),
        hour=_keep(hour, ETA_HOUR_SENTINEL, 0, 23),
        minute=_keep(minute, ETA_MINUTE_SENTINEL, 0, 59),
    )


@dataclass(frozen=True, slots=True)
class NormalisedFields:
    """Every AIS field after sentinel filtering, plus a record of what was dropped.

    ``dropped`` exists so the ingestor can report *how much* of a feed is unusable.
    Silently nulling fields would hide a broken decoder behind a healthy-looking stream.
    """

    latitude: float | None = None
    longitude: float | None = None
    sog_knots: float | None = None
    cog_deg: float | None = None
    heading_deg: float | None = None
    rot_raw: float | None = None
    rot_deg_per_min: float | None = None
    second_of_minute: int | None = None
    ship_type: int | None = None
    dimension_a_m: float | None = None
    dimension_b_m: float | None = None
    dimension_c_m: float | None = None
    dimension_d_m: float | None = None
    eta: ETAParts = field(default_factory=ETAParts)
    dropped: tuple[str, ...] = ()

    @property
    def length_m(self) -> float | None:
        """Overall length, only when both bow and stern distances are real values."""
        if self.dimension_a_m is None or self.dimension_b_m is None:
            return None
        return self.dimension_a_m + self.dimension_b_m

    @property
    def width_m(self) -> float | None:
        if self.dimension_c_m is None or self.dimension_d_m is None:
            return None
        return self.dimension_c_m + self.dimension_d_m


def normalise_sentinels(
    *,
    latitude: Number | None = None,
    longitude: Number | None = None,
    sog_knots: Number | None = None,
    cog_deg: Number | None = None,
    heading_deg: Number | None = None,
    rot: Number | None = None,
    second_of_minute: Number | None = None,
    ship_type: Number | None = None,
    dimension_a_m: Number | None = None,
    dimension_b_m: Number | None = None,
    dimension_c_m: Number | None = None,
    dimension_d_m: Number | None = None,
    eta_month: Number | None = None,
    eta_day: Number | None = None,
    eta_hour: Number | None = None,
    eta_minute: Number | None = None,
) -> NormalisedFields:
    """Convert every ITU-R M.1371 "not available" encoding to ``None``.

    AISStream delivers decoded physical units but does not document whether it filters
    sentinels (AD-22), so this runs unconditionally at the boundary.  Filtering an
    already-filtered value is a no-op; failing to filter one puts a vessel at 91° N
    doing 102.3 knots into the evidence base.
    """
    raw_inputs: dict[str, Number | None] = {
        "latitude": latitude,
        "longitude": longitude,
        "sog_knots": sog_knots,
        "cog_deg": cog_deg,
        "heading_deg": heading_deg,
        "rot": rot,
        "second_of_minute": second_of_minute,
        "ship_type": ship_type,
        "dimension_a_m": dimension_a_m,
        "dimension_b_m": dimension_b_m,
        "dimension_c_m": dimension_c_m,
        "dimension_d_m": dimension_d_m,
    }
    normalised: dict[str, float | int | None] = {
        "latitude": normalise_latitude(latitude),
        "longitude": normalise_longitude(longitude),
        "sog_knots": normalise_sog(sog_knots),
        "cog_deg": normalise_cog(cog_deg),
        "heading_deg": normalise_heading(heading_deg),
        "rot": normalise_rot(rot),
        "second_of_minute": normalise_second_of_minute(second_of_minute),
        "ship_type": normalise_ship_type(ship_type),
        "dimension_a_m": normalise_dimension(dimension_a_m, sentinel=DIMENSION_AB_SENTINEL_M),
        "dimension_b_m": normalise_dimension(dimension_b_m, sentinel=DIMENSION_AB_SENTINEL_M),
        "dimension_c_m": normalise_dimension(dimension_c_m, sentinel=DIMENSION_CD_SENTINEL_M),
        "dimension_d_m": normalise_dimension(dimension_d_m, sentinel=DIMENSION_CD_SENTINEL_M),
    }
    eta = normalise_eta(month=eta_month, day=eta_day, hour=eta_hour, minute=eta_minute)

    dropped = tuple(
        name for name, value in raw_inputs.items() if value is not None and normalised[name] is None
    )
    for name, raw_value, kept in (
        ("eta_month", eta_month, eta.month),
        ("eta_day", eta_day, eta.day),
        ("eta_hour", eta_hour, eta.hour),
        ("eta_minute", eta_minute, eta.minute),
    ):
        if raw_value is not None and kept is None:
            dropped = (*dropped, name)

    rot_raw = normalised["rot"]
    return NormalisedFields(
        latitude=normalised["latitude"],
        longitude=normalised["longitude"],
        sog_knots=normalised["sog_knots"],
        cog_deg=normalised["cog_deg"],
        heading_deg=normalised["heading_deg"],
        rot_raw=None if rot_raw is None else float(rot_raw),
        rot_deg_per_min=decode_rate_of_turn(rot),
        second_of_minute=(
            None if normalised["second_of_minute"] is None else int(normalised["second_of_minute"])
        ),
        ship_type=None if normalised["ship_type"] is None else int(normalised["ship_type"]),
        dimension_a_m=normalised["dimension_a_m"],
        dimension_b_m=normalised["dimension_b_m"],
        dimension_c_m=normalised["dimension_c_m"],
        dimension_d_m=normalised["dimension_d_m"],
        eta=eta,
        dropped=dropped,
    )


# --------------------------------------------------------------------------- MMSI
class MMSIClass(StrEnum):
    """Which kind of radio station an MMSI identifies.

    Only ``SHIP`` may be used for vessel attribution (AD-25).  The rest are recorded
    rather than discarded: an AtoN or a SART in the AOI is context an analyst wants,
    and a track that turns out to be a navigation buoy explains itself immediately.
    """

    SHIP = "SHIP"
    GROUP_OF_SHIPS = "GROUP_OF_SHIPS"
    COAST_STATION = "COAST_STATION"
    SAR_AIRCRAFT = "SAR_AIRCRAFT"
    AID_TO_NAVIGATION = "AID_TO_NAVIGATION"
    AUXILIARY_CRAFT = "AUXILIARY_CRAFT"
    SART = "SART"
    MOB = "MOB"
    EPIRB = "EPIRB"
    DIVER_RADIO = "DIVER_RADIO"
    INVALID = "INVALID"


def _mmsi_digits(mmsi: int | str | None) -> str | None:
    """Nine digits with leading zeros restored, or ``None`` if this cannot be an MMSI.

    An MMSI is a nine-digit *string* transmitted as a 30-bit number, so a coast station
    ``002419001`` survives a round trip through an integer column as ``2419001``.
    Zero-padding restores the prefix that carries the station class; without it every
    coast station and group identifier would be misread as an invalid ship.
    """
    if mmsi is None:
        return None
    if isinstance(mmsi, str):
        text = mmsi.strip()
        if not text.isdigit() or len(text) > MMSI_DIGITS:
            return None
        value = int(text)
        # A written-out MMSI already carries its leading zeros; a shorter string is
        # zero-padded below, exactly as an integer would be.
        if len(text) == MMSI_DIGITS:
            return text if value >= MMSI_MIN else None
    else:
        value = mmsi
    if not MMSI_MIN <= value <= MMSI_MAX:
        return None
    return f"{value:0{MMSI_DIGITS}d}"


#: ``(prefix, station class, offset of the embedded MID)`` — the reserved-prefix table
#: from ITU-R M.585 as summarised in AD-25.  Order is significant: the longer prefixes
#: are listed first so that ``00`` (coast station) is not swallowed by ``0`` (group of
#: ships).  ``None`` marks the emergency-beacon ranges, whose digits after the prefix
#: are a manufacturer id rather than a MID.
_RESERVED_PREFIXES: tuple[tuple[str, MMSIClass, int | None], ...] = (
    ("00", MMSIClass.COAST_STATION, 2),
    ("111", MMSIClass.SAR_AIRCRAFT, 3),
    ("0", MMSIClass.GROUP_OF_SHIPS, 1),
    ("970", MMSIClass.SART, None),
    ("972", MMSIClass.MOB, None),
    ("974", MMSIClass.EPIRB, None),
    ("99", MMSIClass.AID_TO_NAVIGATION, 2),
    ("98", MMSIClass.AUXILIARY_CRAFT, 2),
    ("8", MMSIClass.DIVER_RADIO, 1),
)


def _mid_at(digits: str, offset: int) -> int | None:
    """The three MID digits at ``offset``, or ``None`` if they are not a real MID."""
    mid = int(digits[offset : offset + 3])
    return mid if MMSI_MID_MIN <= mid <= MMSI_MID_MAX else None


def classify_mmsi(mmsi: int | str | None) -> MMSIClass:
    """Classify an MMSI by its reserved prefix (AD-25, docs/AIS_PIPELINE.md §2).

    Every class that structurally contains a MID must contain a *valid* one: without
    that check a five-digit fragment zero-pads into ``000012345`` and is confidently
    reported as a coast station, which is how noise becomes a station in a report.
    """
    digits = _mmsi_digits(mmsi)
    if digits is None:
        return MMSIClass.INVALID

    for prefix, station, mid_offset in _RESERVED_PREFIXES:
        if not digits.startswith(prefix):
            continue
        if mid_offset is not None and _mid_at(digits, mid_offset) is None:
            return MMSIClass.INVALID
        return station

    return MMSIClass.SHIP if _mid_at(digits, 0) is not None else MMSIClass.INVALID


def mmsi_mid(mmsi: int | str | None) -> int | None:
    """The Maritime Identification Digits (flag state), wherever the class puts them.

    Returned for the classes that actually carry a MID; ``None`` otherwise.  The MID is
    the flag state *at the time the identity was issued* — MMSIs are reassigned, so it
    is a hint about a vessel's registry, never proof of it.
    """
    digits = _mmsi_digits(mmsi)
    if digits is None or classify_mmsi(digits) is MMSIClass.INVALID:
        return None
    for prefix, _station, mid_offset in _RESERVED_PREFIXES:
        if digits.startswith(prefix):
            return None if mid_offset is None else _mid_at(digits, mid_offset)
    return _mid_at(digits, 0)


def is_attributable_vessel_mmsi(mmsi: int | str | None) -> bool:
    """True only for a ship MMSI — the single form that may name a candidate vessel.

    Note the caveat that survives even a ``True`` here: MMSI is a radio identifier that
    is reassigned over time and is trivially spoofable, so IMO from ``ShipStaticData``
    is the durable key and the report always states which identifier was used (AD-25).
    """
    return classify_mmsi(mmsi) is MMSIClass.SHIP


def validate_mmsi(mmsi: int | str | None) -> tuple[bool, list[AISQualityFlag]]:
    """``(usable_for_attribution, flags)``.

    A non-ship station is *not* an error in the feed — it is a correctly received
    transmission from something that is not a vessel — so it gets its own flag rather
    than being called invalid.
    """
    station = classify_mmsi(mmsi)
    if station is MMSIClass.INVALID:
        return False, [AISQualityFlag.INVALID_MMSI]
    if station is not MMSIClass.SHIP:
        return False, [AISQualityFlag.NON_SHIP_STATION]
    return True, []


# --------------------------------------------------------------------------- time
def validate_timestamp(ts: datetime, *, now: datetime) -> tuple[bool, list[AISQualityFlag]]:
    """``(ok, flags)`` for a position timestamp.

    ``now`` is injected rather than read from the clock so that cleaning a track is a
    pure function of its inputs: the same messages must always produce the same
    verdicts, in a test, in a re-run and in an evidence report.
    """
    flags: list[AISQualityFlag] = []
    moment = ensure_utc(ts)
    reference = ensure_utc(now)

    if moment <= EPOCH_ZERO_UTC or moment < MIN_PLAUSIBLE_TIMESTAMP_UTC:
        flags.append(AISQualityFlag.BAD_TIMESTAMP)
    if moment > reference + timedelta(minutes=FUTURE_TIMESTAMP_TOLERANCE_MINUTES):
        flags.append(AISQualityFlag.FUTURE_TIMESTAMP)
    return not flags, flags


#: Go's ``time.Time.String()``: ``2026-08-01 18:20:43.237370229 +0000 UTC``.  The
#: fraction is variable-length because Go trims trailing zeros — it may be absent
#: entirely, or up to 9 digits — which is precisely why ``datetime.fromisoformat``
#: cannot parse this format (AD-21).
_GO_TIMESTAMP_RE = re.compile(
    r"""^\s*
    (?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})
    [ T]
    (?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})
    (?:\.(?P<fraction>\d{1,9}))?
    (?:\s*(?P<offset>Z|[+-]\d{2}:?\d{2}))?
    (?:\s+(?P<zone>[A-Za-z][A-Za-z0-9_/+-]*))?
    \s*$""",
    re.VERBOSE,
)


def parse_aisstream_timestamp(value: str) -> datetime:
    """Parse ``MetaData.time_utc`` into an aware UTC datetime.

    Handles the fraction being absent, 3 digits, 9 digits or anything between, and
    tolerates an ISO ``T`` separator and a trailing zone name.  Sub-microsecond digits
    are truncated, not rounded: this field is the *server receipt time*, not the vessel
    transmit time (AD-21), so nanosecond precision is spurious anyway and truncation
    keeps parsing deterministic.

    Raises ``ValidationError`` rather than returning a fallback, because a timestamp we
    cannot read must not become a timestamp we invented.
    """
    match = _GO_TIMESTAMP_RE.match(value)
    if match is None:
        raise ValidationError(
            "AIS timestamp is not in the expected format "
            "'YYYY-MM-DD HH:MM:SS[.fraction] [+0000] [UTC]'.",
            field="time_utc",
            value=value,
        )

    fraction = match.group("fraction") or ""
    microsecond = int(fraction.ljust(6, "0")[:6]) if fraction else 0

    offset_text = match.group("offset")
    if offset_text in (None, "Z"):
        # Go always prints an offset; when it is missing the field is documented UTC.
        tz = UTC
    else:
        sign = -1 if offset_text[0] == "-" else 1
        body = offset_text[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4])))

    try:
        parsed = datetime(
            year=int(match.group("year")),
            month=int(match.group("month")),
            day=int(match.group("day")),
            hour=int(match.group("hour")),
            minute=int(match.group("minute")),
            second=int(match.group("second")),
            microsecond=microsecond,
            tzinfo=tz,
        )
    except ValueError as exc:
        raise ValidationError(
            f"AIS timestamp has an impossible calendar value: {exc}",
            field="time_utc",
            value=value,
        ) from exc
    return parsed.astimezone(UTC)


# --------------------------------------------------------------------------- position
def validate_coordinates(
    latitude: float | None, longitude: float | None
) -> tuple[bool, list[AISQualityFlag]]:
    """``(ok, flags)`` for a latitude/longitude pair.

    The AIS sentinels (91, 181) get their own flag on top of ``INVALID_COORDINATE``:
    both are unusable, but "the transmitter said it had no fix" and "the coordinate is
    corrupt" are different stories, and an analyst is owed the difference.
    """
    flags: list[AISQualityFlag] = []
    lat = _finite(latitude)
    lon = _finite(longitude)
    if lat is None or lon is None:
        return False, [AISQualityFlag.INVALID_COORDINATE]

    if lat == LATITUDE_SENTINEL_DEG or lon == LONGITUDE_SENTINEL_DEG:
        flags.append(AISQualityFlag.SENTINEL_POSITION)
    if abs(lat) > MAX_LATITUDE_DEG or abs(lon) > MAX_LONGITUDE_DEG:
        flags.append(AISQualityFlag.INVALID_COORDINATE)
    elif abs(lat) <= NULL_ISLAND_TOLERANCE_DEG and abs(lon) <= NULL_ISLAND_TOLERANCE_DEG:
        # Exactly (0, 0) is what a decoder emits when it has nothing; the Gulf of
        # Guinea does not, in practice, contain that many vessels.
        flags.append(AISQualityFlag.NULL_ISLAND)
    return not flags, flags


__all__ = [
    "ETAParts",
    "MMSIClass",
    "NormalisedFields",
    "classify_mmsi",
    "decode_rate_of_turn",
    "ensure_utc",
    "is_attributable_vessel_mmsi",
    "mmsi_mid",
    "normalise_cog",
    "normalise_dimension",
    "normalise_eta",
    "normalise_heading",
    "normalise_latitude",
    "normalise_longitude",
    "normalise_rot",
    "normalise_second_of_minute",
    "normalise_sentinels",
    "normalise_ship_type",
    "normalise_sog",
    "parse_aisstream_timestamp",
    "validate_coordinates",
    "validate_mmsi",
    "validate_timestamp",
]
