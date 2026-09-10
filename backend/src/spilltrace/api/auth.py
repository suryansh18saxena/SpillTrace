"""Authentication and authorisation dependencies.

Design notes:

* The **access token** is short-lived (default 15 min) and returned in the response body,
  so the SPA holds it in memory only.
* The **refresh token** is long-lived, stored only as a SHA-256 hash, and delivered in an
  httpOnly + SameSite cookie so browser JavaScript cannot read it.
* Refresh tokens **rotate**: every refresh issues a new one and revokes the old. Reuse of
  an already-revoked token is treated as theft and revokes the whole family.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Cookie, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from spilltrace.api.deps import SessionDep, SettingsDep
from spilltrace.config import Settings
from spilltrace.core.enums import UserRole
from spilltrace.core.errors import AuthenticationError, AuthorizationError
from spilltrace.core.security import (
    create_access_token,
    decode_access_token,
    dummy_verify,
    generate_refresh_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from spilltrace.db.models import User
from spilltrace.db.repositories.users import UserRepository
from spilltrace.logging import get_logger

log = get_logger(__name__)

REFRESH_COOKIE_NAME = "spilltrace_refresh"
_bearer = HTTPBearer(auto_error=False, description="JWT access token")


async def current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Authentication required.")
    payload = decode_access_token(credentials.credentials, secret_key=settings.secret_key)
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid credentials.") from exc

    user = await UserRepository(session).get(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid credentials.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def current_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN.value:
        raise AuthorizationError("This action requires an administrator account.")
    return user


CurrentAdmin = Annotated[User, Depends(current_admin)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)]


class AuthService:
    """Login / refresh / logout.  Kept out of the router so it can be unit-tested."""

    def __init__(self, session: SessionDep, settings: Settings) -> None:
        self.users = UserRepository(session)
        self.settings = settings

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.users.get_by_email(email)
        if user is None:
            # Equalise timing so a caller cannot enumerate registered addresses.
            dummy_verify()
            raise AuthenticationError("Incorrect email or password.")
        if not verify_password(password, user.password_hash):
            raise AuthenticationError("Incorrect email or password.")
        if not user.is_active:
            raise AuthenticationError("This account has been deactivated.")
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        await self.users.touch_login(user)
        return user

    def issue_access_token(self, user: User) -> str:
        return create_access_token(
            subject=str(user.id),
            secret_key=self.settings.secret_key,
            ttl_seconds=self.settings.access_token_ttl_seconds,
            extra_claims={"role": user.role, "email": user.email},
        )

    async def issue_refresh_cookie(
        self, user: User, response: Response, *, user_agent: str | None
    ) -> None:
        token, _ = generate_refresh_token()
        await self.users.issue_refresh_token(
            user=user,
            token=token,
            ttl_seconds=self.settings.refresh_token_ttl_seconds,
            user_agent=user_agent,
        )
        response.set_cookie(
            REFRESH_COOKIE_NAME,
            token,
            max_age=self.settings.refresh_token_ttl_seconds,
            httponly=True,
            secure=self.settings.is_production,
            samesite="lax",
            path="/api/v1/auth",
        )

    async def rotate(self, presented: str | None, response: Response, request: Request) -> User:
        if not presented:
            raise AuthenticationError("No session to refresh.")
        record = await self.users.find_active_refresh_token(presented)
        if record is None:
            # Either expired, or a revoked token was replayed.  Both are handled the
            # same way from the caller's point of view.
            log.warning("refresh_token_rejected")
            raise AuthenticationError("Session expired. Please sign in again.")

        user = await self.users.get(record.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid credentials.")

        await self.users.revoke_refresh_token(record)
        await self.issue_refresh_cookie(
            user, response, user_agent=request.headers.get("user-agent")
        )
        return user

    async def logout(self, presented: str | None, response: Response) -> None:
        if presented:
            record = await self.users.find_active_refresh_token(presented)
            if record is not None:
                await self.users.revoke_refresh_token(record)
        response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/v1/auth")


__all__ = [
    "REFRESH_COOKIE_NAME",
    "AuthService",
    "CurrentAdmin",
    "CurrentUser",
    "RefreshCookie",
    "current_admin",
    "current_user",
]
