"""Authentication endpoints (UI-001)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from spilltrace.api.auth import AuthService, CurrentAdmin, CurrentUser, RefreshCookie
from spilltrace.api.deps import SessionDep, SettingsDep
from spilltrace.api.ratelimit import LOGIN_LIMIT, REFRESH_LIMIT, client_key, enforce
from spilltrace.api.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from spilltrace.core.enums import UserRole
from spilltrace.core.errors import ConflictError
from spilltrace.db.repositories.users import UserRepository
from spilltrace.logging import get_logger

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
log = get_logger(__name__)


@router.post("/login", response_model=TokenResponse, summary="Sign in")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    await enforce(LOGIN_LIMIT, client_key(request, body.email.lower()))
    service = AuthService(session, settings)
    user = await service.authenticate(body.email, body.password)
    await service.issue_refresh_cookie(user, response, user_agent=request.headers.get("user-agent"))
    await session.commit()
    log.info("login_succeeded", user_id=str(user.id), role=user.role)
    return TokenResponse(
        access_token=service.issue_access_token(user),
        expires_in=settings.access_token_ttl_seconds,
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse, summary="Rotate the session")
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    spilltrace_refresh: RefreshCookie = None,
) -> TokenResponse:
    await enforce(REFRESH_LIMIT, client_key(request))
    service = AuthService(session, settings)
    user = await service.rotate(spilltrace_refresh, response, request)
    await session.commit()
    return TokenResponse(
        access_token=service.issue_access_token(user),
        expires_in=settings.access_token_ttl_seconds,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def logout(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    spilltrace_refresh: RefreshCookie = None,
) -> None:
    await AuthService(session, settings).logout(spilltrace_refresh, response)
    await session.commit()


@router.get("/me", response_model=UserOut, summary="Current user")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user (administrators only)",
)
async def create_user(body: RegisterRequest, _admin: CurrentAdmin, session: SessionDep) -> UserOut:
    users = UserRepository(session)
    if await users.get_by_email(body.email):
        raise ConflictError("An account with that email already exists.")
    user = await users.create(
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        role=UserRole(body.role),
    )
    await session.commit()
    log.info("user_created", user_id=str(user.id), role=user.role)
    return UserOut.model_validate(user)


__all__ = ["router"]
