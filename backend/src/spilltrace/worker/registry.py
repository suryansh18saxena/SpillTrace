"""Handler registry.

Handlers are plain async functions taking a :class:`JobContext` and returning a
``result_ref`` dict.  Registration by decorator keeps the dispatch table in one place and
lets tests register fakes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from spilltrace.core.enums import JobType
from spilltrace.worker.context import JobContext

Handler = Callable[[JobContext], Awaitable[dict[str, Any]]]

_HANDLERS: dict[JobType, Handler] = {}


def register(job_type: JobType) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        if job_type in _HANDLERS:
            raise RuntimeError(f"A handler for {job_type.value} is already registered.")
        _HANDLERS[job_type] = fn
        return fn

    return decorator


def get_handler(job_type: JobType) -> Handler | None:
    return _HANDLERS.get(job_type)


def registered_types() -> list[JobType]:
    return sorted(_HANDLERS, key=lambda t: t.value)


def load_handlers() -> None:
    """Import the handler modules so their decorators run."""
    from spilltrace.worker import handlers  # noqa: F401  (side-effecting import)


__all__ = ["Handler", "get_handler", "load_handlers", "register", "registered_types"]
