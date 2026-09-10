"""Redis-backed fixed-window rate limiting.

Applied to authentication and to job creation (NFR-010).  Fixed window rather than a
sliding log because the limits here are coarse and the simpler structure has no
unbounded memory growth.  Fails **open** with a warning if Redis is unavailable: losing
rate limiting is bad, but refusing all logins because a cache is down is worse.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from spilltrace.config import get_settings
from spilltrace.core.errors import RateLimitError
from spilltrace.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimit:
    limit: int
    window_seconds: int
    scope: str


LOGIN_LIMIT = RateLimit(limit=10, window_seconds=300, scope="auth:login")
REFRESH_LIMIT = RateLimit(limit=60, window_seconds=300, scope="auth:refresh")
JOB_LIMIT = RateLimit(limit=60, window_seconds=60, scope="jobs:create")


def client_key(request: Request, extra: str = "") -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    return f"{client_ip}:{extra}" if extra else client_ip


async def enforce(limit: RateLimit, key: str) -> None:
    settings = get_settings()
    redis_key = f"ratelimit:{limit.scope}:{key}"
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        try:
            pipe = client.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, limit.window_seconds, nx=True)
            count, _ = await pipe.execute()
        finally:
            await client.aclose()
    except Exception as exc:
        log.warning("ratelimit_unavailable", scope=limit.scope, error=type(exc).__name__)
        return

    if int(count) > limit.limit:
        raise RateLimitError(
            "Too many requests. Please wait a moment and try again.",
            scope=limit.scope,
            retry_after_seconds=limit.window_seconds,
        )


__all__ = ["JOB_LIMIT", "LOGIN_LIMIT", "REFRESH_LIMIT", "RateLimit", "client_key", "enforce"]
