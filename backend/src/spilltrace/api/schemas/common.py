"""Shared response envelopes and GeoJSON models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

ItemT = TypeVar("ItemT")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PageResponse(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    total: int = Field(description="Total rows matching the filter, ignoring pagination")
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class GeoJSONPolygon(BaseModel):
    """A GeoJSON polygon in EPSG:4326, longitude first."""

    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[float, float]]] = Field(
        description="Linear rings; the first is the exterior ring and must be closed.",
        examples=[[[(68.9, 22.3), (70.4, 22.3), (70.4, 23.2), (68.9, 23.2), (68.9, 22.3)]]],
    )


class GeoJSONGeometry(BaseModel):
    type: str
    coordinates: Any


class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any] | None
    properties: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class FeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class TimeWindow(BaseModel):
    start_time: datetime
    end_time: datetime


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    role: str


__all__ = [
    "ErrorBody",
    "ErrorResponse",
    "FeatureCollection",
    "GeoJSONFeature",
    "GeoJSONGeometry",
    "GeoJSONPolygon",
    "HealthResponse",
    "ORMModel",
    "PageResponse",
    "TimeWindow",
]
