"""Shared FastAPI dependencies and query-parameter aliases.

Every module here uses ``from __future__ import annotations``, which turns annotations
into strings.  FastAPI resolves those with ``get_type_hints``, so an inline
``Annotated[int, Query(...)]`` in a signature becomes an unresolvable forward reference.
Declaring the annotated types as **module-level aliases** keeps them resolvable, so all
query parameters are defined here and imported by the routers.

This module deliberately does **not** use ``from __future__ import annotations``: FastAPI
evaluates the ``__init__`` signature of class-based dependencies eagerly, and a stringised
``Annotated`` alias there fails to resolve.  Everywhere else in the codebase the future
import is used as normal.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from spilltrace.config import Settings, get_settings
from spilltrace.db.session import get_session


async def db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


SessionDep = Annotated[AsyncSession, Depends(db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# --------------------------------------------------------------------------- queries
LimitQuery = Annotated[int, Query(ge=1, le=200, description="Maximum rows to return")]
OffsetQuery = Annotated[int, Query(ge=0, description="Rows to skip")]
StatusQuery = Annotated[str | None, Query(alias="status", description="Filter by status")]
SearchQuery = Annotated[
    str | None, Query(max_length=200, description="Free-text search over title and reference")
]
FromQuery = Annotated[datetime | None, Query(alias="from", description="Created at or after")]
ToQuery = Annotated[datetime | None, Query(alias="to", description="Created at or before")]


class Pagination:
    """Uniform pagination for every list endpoint (docs/API.md §1)."""

    def __init__(self, limit: LimitQuery = 50, offset: OffsetQuery = 0) -> None:
        self.limit = limit
        self.offset = offset


PaginationDep = Annotated[Pagination, Depends(Pagination)]

__all__ = [
    "FromQuery",
    "LimitQuery",
    "OffsetQuery",
    "Pagination",
    "PaginationDep",
    "SearchQuery",
    "SessionDep",
    "SettingsDep",
    "StatusQuery",
    "ToQuery",
    "db_session",
]
