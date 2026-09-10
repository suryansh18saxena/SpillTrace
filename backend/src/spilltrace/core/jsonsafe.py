"""Convert arbitrary Python values into something a JSONB column will accept.

Handlers assemble result payloads out of whatever the domain layer produced —
``datetime``, ``StrEnum``, ``UUID``, ``Decimal``, numpy scalars, dataclasses, sets.
asyncpg rejects most of those, and because the failure happens at flush time it surfaces
far away from the handler that caused it.  Normalising centrally means no handler can
break persistence by returning a rich object.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

MAX_DEPTH = 12


def to_json_safe(value: Any, *, _depth: int = 0) -> Any:
    if _depth > MAX_DEPTH:
        return str(value)

    # Enum must be checked first: StrEnum and IntEnum members *are* str/int instances,
    # so an isinstance(str) check would pass the member through unconverted and JSONB
    # would receive its repr.
    if isinstance(value, Enum):
        return to_json_safe(value.value, _depth=_depth + 1)
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        # NaN and infinity are valid Python floats but not valid JSON.
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, datetime):
        from spilltrace.core.time import isoformat_utc

        return isoformat_utc(value) if value.tzinfo else value.isoformat()
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): to_json_safe(v, _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_json_safe(v, _depth=_depth + 1) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_json_safe(dataclasses.asdict(value), _depth=_depth + 1)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return to_json_safe(value.to_dict(), _depth=_depth + 1)
    # numpy scalars and anything else that quacks like a number.
    if hasattr(value, "item") and callable(value.item):
        try:
            return to_json_safe(value.item(), _depth=_depth + 1)
        except (ValueError, TypeError):
            pass
    return str(value)


__all__ = ["MAX_DEPTH", "to_json_safe"]
