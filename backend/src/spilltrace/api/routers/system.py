"""System status for the Admin page (UI-010).

The most important field on this page is not uptime — it is which adapter is behind each
data source and whether that adapter produces real observations. An analyst looking at a
map needs to be able to answer "is any of this real?" without reading the code.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from spilltrace.api.auth import CurrentAdmin, CurrentUser
from spilltrace.api.deps import SessionDep, SettingsDep
from spilltrace.api.routers.health import _check_database, _check_redis, _check_storage
from spilltrace.api.schemas.jobs import JobOut
from spilltrace.core.enums import ComponentStatus, JobStatus
from spilltrace.core.time import isoformat_utc, utcnow
from spilltrace.db.models import ModelVersion
from spilltrace.db.repositories.jobs import JobRepository
from spilltrace.logging import get_logger
from spilltrace.worker.queue import JobQueue

router = APIRouter(prefix="/api/v1/system", tags=["system"])
log = get_logger(__name__)


@router.get("/providers", summary="Which adapter backs each data source")
async def providers(user: CurrentUser, settings: SettingsDep) -> dict[str, Any]:
    """Available to every analyst, not just admins.

    Whether the vessels on their screen came from a real feed is not an administrative
    detail; it changes how the whole case should be read.
    """
    missing = set(settings.missing_credentials())
    modes = settings.provider_modes()
    entries = []
    for port, info in modes.items():
        needs = {
            "satellite": "CDSE_USERNAME/CDSE_PASSWORD",
            "environment": "COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD",
            "ais": "AISSTREAM_API_KEY",
        }.get(port)
        entries.append(
            {
                "port": port,
                "implementation": info["implementation"],
                "mode": info["mode"],
                "configured": info["mode"] == "SYNTHETIC" or needs not in missing,
                "requires": needs if info["mode"] == "REAL" else None,
            }
        )
    return {
        "providers": entries,
        "any_synthetic": any(e["mode"] == "SYNTHETIC" for e in entries),
        "notice": (
            "Sources marked SYNTHETIC produce deterministic demonstration data. They do "
            "not represent any real vessel, spill or measurement."
        ),
    }


@router.get("/status", summary="Operational status")
async def status(admin: CurrentAdmin, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    components = [await _check_database(), await _check_redis(), await _check_storage()]
    components.append(await _check_queue(settings))
    components.append(await _check_worker(session))

    jobs = JobRepository(session)
    stats = await jobs.stats(hours=24)
    recent = await jobs.recent(limit=10)
    failed = await jobs.recent(limit=10, status=JobStatus.FAILED)

    models = (
        (await session.execute(select(ModelVersion).order_by(ModelVersion.created_at.desc())))
        .scalars()
        .all()
    )

    notices: list[str] = []
    if missing := settings.missing_credentials():
        notices.append(
            "These credentials are required by the currently selected providers and are "
            f"not set: {', '.join(missing)}."
        )
    if any(m["mode"] == "SYNTHETIC" for m in settings.provider_modes().values()):
        notices.append(
            "At least one data source is running in SYNTHETIC mode; artifacts it produces "
            "are labelled accordingly."
        )
    if any(c["status"] != ComponentStatus.UP.value for c in components):
        notices.append("One or more components are not healthy; see the component table.")
    if not any(m.is_active for m in models):
        notices.append(
            "No detection model is marked active. Detection will use the deterministic "
            "analytical detector, whose output is labelled SYNTHETIC."
        )

    return {
        "version": settings.version,
        "environment": settings.environment,
        "generated_at": isoformat_utc(utcnow()),
        "components": components,
        "providers": (await providers(admin, settings))["providers"],
        "models": [
            {
                "name": m.name,
                "version": m.version,
                "framework": m.framework,
                "task": m.task,
                "is_active": m.is_active,
                # Measured values only; an empty object means no evaluation was recorded.
                "metrics": m.metrics,
                "input_channels": m.input_channels,
                "input_size": m.input_size,
                "created_at": isoformat_utc(m.created_at),
            }
            for m in models
        ],
        "jobs": stats,
        "recent_jobs": [JobOut.model_validate(j).model_dump(mode="json") for j in recent],
        "failed_jobs": [JobOut.model_validate(j).model_dump(mode="json") for j in failed],
        "notices": notices,
    }


async def _check_queue(settings: SettingsDep) -> dict[str, Any]:
    import time

    started = time.perf_counter()
    queue = JobQueue(settings)
    try:
        depth = await queue.depth()
        return {
            "name": "job_queue",
            "status": ComponentStatus.UP.value,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "detail": f"{depth} job(s) waiting",
        }
    except Exception as exc:  # status must never raise
        return {
            "name": "job_queue",
            "status": ComponentStatus.DOWN.value,
            "latency_ms": None,
            "detail": type(exc).__name__,
        }
    finally:
        await queue.close()


async def _check_worker(session: SessionDep) -> dict[str, Any]:
    """Inferred from job activity rather than from a heartbeat the worker self-reports.

    A worker that says it is alive while failing to claim anything is not useful; the
    question that matters is whether queued work is being picked up.
    """
    from datetime import timedelta

    from sqlalchemy import func

    from spilltrace.db.models import Job

    running = int(
        (
            await session.execute(
                select(func.count()).select_from(Job).where(Job.status == JobStatus.RUNNING.value)
            )
        ).scalar_one()
    )
    stale_cutoff = utcnow() - timedelta(minutes=5)
    stuck = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.status == JobStatus.RUNNING.value,
                    Job.heartbeat_at < stale_cutoff,
                )
            )
        ).scalar_one()
    )
    waiting = int(
        (
            await session.execute(
                select(func.count()).select_from(Job).where(Job.status == JobStatus.QUEUED.value)
            )
        ).scalar_one()
    )
    if stuck:
        state, detail = ComponentStatus.DEGRADED.value, f"{stuck} job(s) past their heartbeat"
    elif waiting and not running:
        state, detail = ComponentStatus.DEGRADED.value, f"{waiting} job(s) queued, none running"
    else:
        state, detail = ComponentStatus.UP.value, f"{running} running, {waiting} queued"
    return {"name": "workers", "status": state, "latency_ms": None, "detail": detail}


__all__ = ["router"]
