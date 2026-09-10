"""Password hashing and token primitives.

Kept in ``core`` because it is pure: no database, no framework, no request context.
``argon2-cffi`` and ``PyJWT`` are libraries, not frameworks, so the layering rule holds.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from spilltrace.core.errors import AuthenticationError

# Argon2id at the reference "second recommended" configuration from RFC 9106:
# 64 MiB, 3 iterations, 4 lanes.  Chosen over bcrypt because Argon2id resists both
# GPU and side-channel attack, and over scrypt because the parameters are clearer.
_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)

MIN_PASSWORD_LENGTH = 12
JWT_ALGORITHM = "HS256"

#: A real Argon2 hash of a value nobody will submit, used to equalise login timing.
_DUMMY_HASH = _HASHER.hash("spilltrace-timing-equaliser")


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthenticationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return _HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-ish time verification.

    Returns ``False`` rather than raising for a wrong password so callers cannot
    accidentally distinguish "no such user" from "wrong password" in their control flow.
    """
    try:
        _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    try:
        return _HASHER.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def dummy_verify() -> None:
    """Burn the same work as a real verification.

    Called when the email does not exist, so that response timing does not reveal
    whether an account is registered.
    """
    # The work is the point, not the result.
    with contextlib.suppress(Exception):
        _HASHER.verify(_DUMMY_HASH, "not-the-password")


# --------------------------------------------------------------------------- JWT
def create_access_token(
    *,
    subject: str,
    secret_key: str,
    ttl_seconds: int,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "typ": "access",
        "jti": secrets.token_urlsafe(16),
        **(extra_claims or {}),
    }
    return jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, *, secret_key: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Session expired. Please sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid credentials.") from exc
    if payload.get("typ") != "access":
        raise AuthenticationError("Invalid credentials.")
    return payload


# --------------------------------------------------------------------------- refresh
def generate_refresh_token() -> tuple[str, str]:
    """Return ``(token, token_hash)``.

    Only the hash is stored, so a database leak does not yield usable sessions.  SHA-256
    is appropriate here (unlike for passwords) because the token is already 256 bits of
    entropy and is not guessable.
    """
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


__all__ = [
    "JWT_ALGORITHM",
    "MIN_PASSWORD_LENGTH",
    "create_access_token",
    "decode_access_token",
    "dummy_verify",
    "generate_refresh_token",
    "hash_password",
    "hash_refresh_token",
    "needs_rehash",
    "tokens_equal",
    "verify_password",
]
