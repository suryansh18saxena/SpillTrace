"""Repository base class and pagination envelope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spilltrace.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


@dataclass(slots=True)
class Page(Generic[ModelT]):
    items: list[ModelT]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class Repository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def paginate(self, statement: Select[Any], *, limit: int, offset: int) -> Page[ModelT]:
        """Run a statement with a matching COUNT.

        The count subquery drops ORDER BY so PostgreSQL does not sort rows it is only
        going to count.
        """
        count_stmt = select(func.count()).select_from(statement.order_by(None).subquery())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        rows = (
            (await self.session.execute(statement.limit(limit).offset(offset)))
            .scalars()
            .unique()
            .all()
        )
        return Page(items=list(rows), total=total, limit=limit, offset=offset)


__all__ = ["Page", "Repository"]
