"""Job and pipeline schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from spilltrace.api.schemas.common import ORMModel
from spilltrace.core.enums import JobType


class JobOut(ORMModel):
    id: uuid.UUID
    case_id: uuid.UUID | None
    pipeline_id: uuid.UUID | None
    job_type: str
    status: str
    progress: int
    step: str | None
    attempt: int
    max_attempts: int
    result_ref: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class JobCreate(BaseModel):
    job_type: JobType
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=-10, le=10)


class PipelineStart(BaseModel):
    mode: Literal["DEMO", "REAL"] = Field(
        default="REAL",
        description=(
            "DEMO runs the whole chain on deterministic synthetic data with no external "
            "provider; every artifact it produces is labelled SYNTHETIC."
        ),
    )
    stages: list[JobType] | None = Field(
        default=None, description="Subset of stages to run; defaults to the full chain."
    )
    params: dict[str, Any] = Field(default_factory=dict)


class PipelineOut(BaseModel):
    pipeline_id: uuid.UUID
    case_id: uuid.UUID
    mode: str
    jobs: list[JobOut]


__all__ = ["JobCreate", "JobOut", "PipelineOut", "PipelineStart"]
