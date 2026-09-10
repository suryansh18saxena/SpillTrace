"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from spilltrace.api.errors import register_exception_handlers
from spilltrace.api.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from spilltrace.api.routers import (
    auth,
    cases,
    demo,
    events,
    health,
    investigation,
    jobs,
    layers,
    system,
)
from spilltrace.config import Settings, get_settings
from spilltrace.db.session import dispose_engine
from spilltrace.logging import configure_logging, get_logger

log = get_logger(__name__)

DESCRIPTION = """
SPILLTRACE correlates Sentinel-1 SAR oil-slick detections with reverse-drift origin
regions and AIS vessel trajectories, then ranks candidate vessels with an explainable,
factor-by-factor score.

**Attribution produced by this system is investigative/probabilistic evidence and is not
automatic legal proof.**
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    log.info(
        "startup",
        version=settings.version,
        environment=settings.environment,
        role=settings.role,
        providers=settings.provider_modes(),
    )
    if missing := settings.missing_credentials():
        log.warning("missing_credentials_for_selected_providers", missing=missing)
    yield
    from spilltrace.api.events_broker import shutdown_broker

    await shutdown_broker()
    await dispose_engine()
    log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.environment != "development")

    app = FastAPI(
        title="SPILLTRACE API",
        version=settings.version,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "Team OnlyBans — SIH26143"},
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(app)
    for module in (health, auth, cases, jobs, demo, layers, investigation, events, system):
        app.include_router(module.router)

    return app


app = create_app()

__all__ = ["app", "create_app"]
