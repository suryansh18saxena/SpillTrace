"""Admin / system status schemas (UI-010)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from spilltrace.api.schemas.jobs import JobOut


class ComponentHealth(BaseModel):
    name: str
    status: str
    latency_ms: float | None = None
    detail: str | None = None


class ProviderInfo(BaseModel):
    port: str
    implementation: str
    mode: str = Field(description="REAL when the adapter talks to a real provider, else SYNTHETIC")
    configured: bool = Field(
        description="False when the selected real adapter is missing credentials"
    )


class ModelInfo(BaseModel):
    name: str
    version: str
    is_active: bool
    metrics: dict[str, Any] = Field(default_factory=dict)
    input_channels: int | None = None
    input_size: int | None = None


class SystemStatus(BaseModel):
    version: str
    environment: str
    components: list[ComponentHealth]
    providers: list[ProviderInfo]
    models: list[ModelInfo]
    jobs: dict[str, int]
    recent_jobs: list[JobOut]
    failed_jobs: list[JobOut]
    notices: list[str] = Field(default_factory=list)


__all__ = ["ComponentHealth", "ModelInfo", "ProviderInfo", "SystemStatus"]
