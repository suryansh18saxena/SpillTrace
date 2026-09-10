"""User and refresh-token persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update

from spilltrace.core.enums import UserRole
from spilltrace.core.security import hash_password, hash_refresh_token
from spilltrace.core.time import utcnow
from spilltrace.db.models import RefreshToken, User
from spilltrace.db.repositories.base import Repository


class UserRepository(Repository[User]):
    model = User

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        email: str,
        password: str,
        full_name: str | None = None,
        role: UserRole = UserRole.ANALYST,
    ) -> User:
        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role=role.value,
            is_active=True,
        )
        return await self.add(user)

    async def touch_login(self, user: User) -> None:
        user.last_login_at = utcnow()
        await self.session.flush()

    # ------------------------------------------------------------------ refresh
    async def issue_refresh_token(
        self, *, user: User, token: str, ttl_seconds: int, user_agent: str | None = None
    ) -> RefreshToken:
        # Added directly rather than through Repository.add, which is typed for User.
        record = RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(token),
            expires_at=utcnow() + timedelta(seconds=ttl_seconds),
            user_agent=(user_agent or "")[:300] or None,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def find_active_refresh_token(self, token: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(token),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > utcnow(),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def revoke_refresh_token(
        self, record: RefreshToken, *, replaced_by: uuid.UUID | None = None
    ) -> None:
        record.revoked_at = utcnow()
        record.replaced_by = replaced_by
        await self.session.flush()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        """Used on logout-everywhere and on detection of refresh-token reuse."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(getattr(result, "rowcount", 0) or 0)

    async def purge_expired(self, *, before: datetime | None = None) -> int:
        cutoff = before or utcnow()
        stmt = select(RefreshToken).where(RefreshToken.expires_at < cutoff)
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            await self.session.delete(row)
        await self.session.flush()
        return len(rows)


__all__ = ["UserRepository"]
