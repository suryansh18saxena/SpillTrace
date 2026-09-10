"""Case schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from spilltrace.api.schemas.auth import UserOut
from spilltrace.api.schemas.common import GeoJSONPolygon, ORMModel


class CaseCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    aoi: GeoJSONPolygon
    start_time: datetime
    end_time: datetime

    @field_validator("start_time", "end_time")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Timestamps must include a timezone offset (use ...Z for UTC).")
        return value

    @model_validator(mode="after")
    def _window_order(self) -> CaseCreate:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time.")
        return self


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    aoi: GeoJSONPolygon | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None


class CaseOut(ORMModel):
    id: uuid.UUID
    case_ref: str
    title: str
    description: str | None
    status: str
    aoi: dict[str, Any]
    start_time: datetime
    end_time: datetime
    owner: UserOut | None = None
    data_provenance: str
    scenario: str | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class CaseDetailOut(CaseOut):
    aoi_area_km2: float
    counts: dict[str, int] = Field(default_factory=dict)
    notice: str | None = Field(
        default=None,
        description="Present when the case contains synthetic demonstration data.",
    )


__all__ = ["CaseCreate", "CaseDetailOut", "CaseOut", "CaseUpdate"]
