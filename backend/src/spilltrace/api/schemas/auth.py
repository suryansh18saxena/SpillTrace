"""Authentication schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from spilltrace.api.schemas.common import ORMModel
from spilltrace.core.security import MIN_PASSWORD_LENGTH


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
    last_login_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - the OAuth token type, not a secret
    expires_in: int
    user: UserOut


class RegisterRequest(BaseModel):
    """Admin-only user creation."""

    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    full_name: str | None = Field(default=None, max_length=200)
    role: str = Field(default="analyst", pattern="^(analyst|admin)$")


__all__ = ["LoginRequest", "RegisterRequest", "TokenResponse", "UserOut"]
