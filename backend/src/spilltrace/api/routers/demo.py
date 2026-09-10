"""Demo endpoints (FR-020, CON-009).

Everything created here is labelled ``SYNTHETIC`` end to end.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from spilltrace.api.auth import CurrentUser
from spilltrace.api.deps import SessionDep, SettingsDep
from spilltrace.api.schemas.cases import CaseOut
from spilltrace.core.disclaimers import SYNTHETIC_DATA_NOTICE
from spilltrace.core.enums import DataProvenance
from spilltrace.core.geometry import bbox_polygon
from spilltrace.db.repositories.cases import CaseRepository
from spilltrace.demo.scenarios import SCENARIOS, get_scenario
from spilltrace.logging import get_logger
from spilltrace.worker.pipeline import create_pipeline, runnable_jobs
from spilltrace.worker.queue import JobQueue

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
log = get_logger(__name__)


class DemoCaseRequest(BaseModel):
    scenario: str = Field(default="kutch-01")
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    run_pipeline: bool = Field(
        default=True, description="Immediately queue the full demonstration pipeline."
    )


class DemoCaseResponse(BaseModel):
    case: CaseOut
    scenario: dict[str, Any]
    pipeline_id: str | None
    notice: str


@router.get("/scenarios", summary="Available demonstration scenarios")
async def list_scenarios() -> dict[str, Any]:
    return {
        "scenarios": [s.to_dict() for s in SCENARIOS.values()],
        "notice": SYNTHETIC_DATA_NOTICE,
    }


@router.post(
    "/cases",
    response_model=DemoCaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fully synthetic demonstration case",
)
async def create_demo_case(
    body: DemoCaseRequest, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> DemoCaseResponse:
    scenario = get_scenario(body.scenario)
    repo = CaseRepository(session)
    case = await repo.create(
        owner=user,
        title=f"{scenario.title} (SYNTHETIC)",
        description=(f"{scenario.description}\n\n{SYNTHETIC_DATA_NOTICE}"),
        aoi=bbox_polygon(*scenario.aoi_bbox),
        start_time=scenario.case_start,
        end_time=scenario.case_end,
        provenance=DataProvenance.SYNTHETIC,
        scenario=scenario.key,
        seed=body.seed,
    )
    await session.flush()

    pipeline_id = None
    if body.run_pipeline:
        pipeline_id, _ = await create_pipeline(
            session,
            case=case,
            mode="DEMO",
            params={"scenario": scenario.key, "seed": body.seed},
        )
        ready = await runnable_jobs(session, pipeline_id)
        await session.commit()
        queue = JobQueue(settings)
        try:
            for job in ready:
                await queue.enqueue(job.id, priority=job.priority)
        finally:
            await queue.close()
    else:
        await session.commit()

    await session.refresh(case)
    from spilltrace.api.routers.cases import _to_out

    log.info("demo_case_created", case_id=str(case.id), scenario=scenario.key, seed=body.seed)
    return DemoCaseResponse(
        case=_to_out(case),
        scenario=scenario.to_dict(),
        pipeline_id=str(pipeline_id) if pipeline_id else None,
        notice=SYNTHETIC_DATA_NOTICE,
    )


__all__ = ["router"]
