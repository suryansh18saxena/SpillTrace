"""Server-sent job events (NFR-003).

Polling a job list works but is wasteful and laggy; SSE gives the progress bar something
to react to.  ``EventSource`` cannot send an Authorization header, so the token is
accepted as a query parameter here — narrowly, for this one read-only endpoint, and
documented as such.

Every stream is served from a **single** process-wide Redis subscription
(:mod:`spilltrace.api.events_broker`). An earlier version opened one Redis connection per
client, which made the API unhealthy once a handful of tabs were open — the cost scaled
with viewers instead of with work.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import orjson
from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from spilltrace.api.auth import current_user
from spilltrace.api.deps import SessionDep, SettingsDep
from spilltrace.api.events_broker import get_broker
from spilltrace.core.errors import AuthenticationError
from spilltrace.core.security import decode_access_token
from spilltrace.db.models import User
from spilltrace.db.repositories.cases import CaseRepository
from spilltrace.db.repositories.users import UserRepository
from spilltrace.logging import get_logger

router = APIRouter(prefix="/api/v1/cases", tags=["events"])
log = get_logger(__name__)

TokenQuery = Annotated[
    str | None,
    Query(
        alias="access_token",
        description=(
            "EventSource cannot set an Authorization header, so this read-only stream "
            "accepts the access token as a query parameter."
        ),
    ),
]

#: Sent when nothing has happened, so proxies do not close an idle connection.
KEEPALIVE_SECONDS = 20.0


@router.get("/{case_id}/events", summary="Live job progress (SSE)")
async def case_events(
    case_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    access_token: TokenQuery = None,
) -> EventSourceResponse:
    user = await _authenticate(request, session, settings, access_token)
    await CaseRepository(session).get_for_user(case_id, user)

    broker = get_broker()
    subscriber = await broker.subscribe(str(case_id))

    async def stream() -> AsyncIterator[dict[str, str]]:
        try:
            yield {"event": "open", "data": orjson.dumps({"case_id": str(case_id)}).decode()}
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(
                        subscriber.queue.get(), timeout=KEEPALIVE_SECONDS
                    )
                except TimeoutError:
                    # Keeps proxies from closing an idle connection.
                    yield {"event": "keepalive", "data": "{}"}
                    continue
                yield {
                    "event": payload.get("type", "job"),
                    "data": orjson.dumps(payload).decode(),
                }
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a dropped stream must not 500 the app
            log.warning("event_stream_failed", error=type(exc).__name__)
        finally:
            await broker.unsubscribe(subscriber)

    return EventSourceResponse(stream())


async def _authenticate(
    request: Request, session: SessionDep, settings: SettingsDep, access_token: str | None
) -> User:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        from fastapi.security import HTTPAuthorizationCredentials

        return await current_user(
            session,
            settings,
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=header[7:]),
        )
    if not access_token:
        raise AuthenticationError("Authentication required.")
    payload = decode_access_token(access_token, secret_key=settings.secret_key)
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid credentials.") from exc
    user = await UserRepository(session).get(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid credentials.")
    return user


__all__ = ["router"]
