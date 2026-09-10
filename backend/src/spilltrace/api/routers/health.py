"""Liveness and readiness probes."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from spilltrace.config import get_settings
from spilltrace.core.enums import ComponentStatus
from spilltrace.db.session import get_sessionmaker
from spilltrace.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "spilltrace-api",
        "version": settings.version,
        "environment": settings.environment,
        "role": settings.role,
    }


async def _check_database() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        async with get_sessionmaker()() as session:
            postgis = (await session.execute(text("SELECT postgis_version()"))).scalar_one()
        return {
            "name": "database",
            "status": ComponentStatus.UP.value,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "detail": f"PostGIS {postgis}",
        }
    except Exception as exc:
        log.warning("health_database_down", error=str(exc))
        return {
            "name": "database",
            "status": ComponentStatus.DOWN.value,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "detail": type(exc).__name__,
        }


async def _check_redis() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(get_settings().redis_url)
        try:
            await client.ping()
        finally:
            await client.aclose()
        return {
            "name": "redis",
            "status": ComponentStatus.UP.value,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "detail": None,
        }
    except Exception as exc:
        log.warning("health_redis_down", error=str(exc))
        return {
            "name": "redis",
            "status": ComponentStatus.DOWN.value,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "detail": type(exc).__name__,
        }


async def _check_storage() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        from spilltrace.adapters.storage import build_object_store

        store = build_object_store()
        await store.healthcheck()
        return {
            "name": "object_storage",
            "status": ComponentStatus.UP.value,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "detail": store.describe(),
        }
    except Exception as exc:
        log.warning("health_storage_down", error=str(exc))
        return {
            "name": "object_storage",
            "status": ComponentStatus.DOWN.value,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "detail": type(exc).__name__,
        }


@router.get("/health/ready", summary="Readiness probe")
async def readiness(response: Response) -> dict[str, Any]:
    components = [await _check_database(), await _check_redis(), await _check_storage()]
    ready = all(c["status"] == ComponentStatus.UP.value for c in components)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "not_ready", "components": components}


__all__ = ["router"]
