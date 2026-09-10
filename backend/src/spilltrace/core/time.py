"""Time helpers.

Everything in SPILLTRACE is UTC.  A naive datetime reaching the database would silently
adopt the server's local zone, which for a forensic system is a correctness bug, not a
formatting one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from spilltrace.core.errors import InvalidTimeWindowError


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime, *, field: str = "timestamp") -> datetime:
    """Normalise to timezone-aware UTC, rejecting naive input."""
    if value.tzinfo is None:
        raise InvalidTimeWindowError(
            f"{field} must include a timezone; naive datetimes are ambiguous.", field=field
        )
    return value.astimezone(UTC)


def validate_time_window(
    start: datetime, end: datetime, *, max_days: int | None = None, field: str = "time window"
) -> tuple[datetime, datetime]:
    start = ensure_utc(start, field=f"{field}.start")
    end = ensure_utc(end, field=f"{field}.end")
    if end <= start:
        raise InvalidTimeWindowError(f"{field} end must be after start.", field=field)
    if max_days is not None and (end - start) > timedelta(days=max_days):
        raise InvalidTimeWindowError(
            f"{field} spans {(end - start).days} days which exceeds the {max_days}-day limit.",
            field=field,
            span_days=(end - start).days,
            max_days=max_days,
        )
    return start, end


def overlap_seconds(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> float:
    """Seconds of overlap between two intervals; 0 when they do not overlap."""
    latest_start = max(a_start, b_start)
    earliest_end = min(a_end, b_end)
    return max(0.0, (earliest_end - latest_start).total_seconds())


def isoformat_utc(value: datetime) -> str:
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


__all__ = [
    "ensure_utc",
    "isoformat_utc",
    "overlap_seconds",
    "utcnow",
    "validate_time_window",
]
