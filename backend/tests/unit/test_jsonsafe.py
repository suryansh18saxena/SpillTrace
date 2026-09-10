"""JSONB normalisation.

The bug this prevents is remote: a handler returns a rich object, and persistence fails
at flush time with a message that names neither the handler nor the field.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import IntEnum, StrEnum

import numpy as np
import pytest

from spilltrace.core.jsonsafe import to_json_safe


class Colour(StrEnum):
    RED = "red"


class Level(IntEnum):
    HIGH = 3


@dataclass
class Sample:
    name: str
    when: datetime


class Renderable:
    def to_dict(self) -> dict[str, object]:
        return {"kind": "renderable", "at": datetime(2026, 1, 1, tzinfo=UTC)}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, True),
        (7, 7),
        ("text", "text"),
        (1.5, 1.5),
        (Colour.RED, "red"),
        (Level.HIGH, 3),
        (Decimal("2.50"), 2.5),
        (timedelta(minutes=90), 5400.0),
        (date(2026, 8, 14), "2026-08-14"),
        (time(1, 12), "01:12:00"),
        (b"bytes", "bytes"),
    ],
)
def test_scalars(value: object, expected: object) -> None:
    assert to_json_safe(value) == expected


def test_str_enum_is_converted_not_passed_through() -> None:
    # StrEnum members are str instances, so an isinstance(str) check first would leak
    # the member's repr into the column.
    assert to_json_safe(Colour.RED).__class__ is str
    assert to_json_safe({"c": Colour.RED}) == {"c": "red"}


def test_aware_datetime_uses_utc_z_suffix() -> None:
    assert to_json_safe(datetime(2026, 8, 14, 1, 12, tzinfo=UTC)) == "2026-08-14T01:12:00Z"


def test_naive_datetime_is_still_serialised() -> None:
    assert to_json_safe(datetime(2026, 8, 14, 1, 12)) == "2026-08-14T01:12:00"  # noqa: DTZ001


def test_uuid_becomes_a_string() -> None:
    value = uuid.uuid4()
    assert to_json_safe(value) == str(value)


def test_nan_and_infinity_become_null() -> None:
    # Valid Python floats, invalid JSON.
    assert to_json_safe(float("nan")) is None
    assert to_json_safe(float("inf")) is None
    assert to_json_safe(float("-inf")) is None


def test_collections_are_normalised_recursively() -> None:
    assert to_json_safe({"s": {2, 1}, "t": (Colour.RED,), "l": [[Level.HIGH]]}) == {
        "s": [1, 2],
        "t": ["red"],
        "l": [[3]],
    }


def test_dataclasses_are_expanded() -> None:
    assert to_json_safe(Sample("a", datetime(2026, 1, 1, tzinfo=UTC))) == {
        "name": "a",
        "when": "2026-01-01T00:00:00Z",
    }


def test_objects_with_to_dict_are_used() -> None:
    assert to_json_safe(Renderable()) == {"kind": "renderable", "at": "2026-01-01T00:00:00Z"}


def test_numpy_scalars_are_unwrapped() -> None:
    assert to_json_safe(np.float32(1.5)) == 1.5
    assert to_json_safe(np.int64(9)) == 9


def test_non_string_keys_become_strings() -> None:
    # StrEnum.__str__ returns the value, which is the sensible key form here.
    assert to_json_safe({1: "a", Colour.RED: "b"}) == {"1": "a", "red": "b"}


def test_deep_nesting_terminates() -> None:
    value: object = "leaf"
    for _ in range(40):
        value = [value]
    json.dumps(to_json_safe(value))  # must not recurse past the depth limit


def test_output_is_always_json_serialisable() -> None:
    payload = {
        "when": datetime.now(UTC),
        "id": uuid.uuid4(),
        "enum": Colour.RED,
        "np": np.float64(2.25),
        "nested": [{"set": {1, 2}, "dc": Sample("x", datetime.now(UTC))}],
        "bad": float("nan"),
    }
    json.dumps(to_json_safe(payload))
