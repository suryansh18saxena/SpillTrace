"""Copernicus Data Space Ecosystem authentication (AD-06).

CDSE fronts its download services with Keycloak.  The confirmed shape is a **password
grant against the ``CDSE`` realm using the public client ``cdse-public``**; the access
token lives 10 minutes and the refresh token 60.  ``client_credentials`` is documented
only for openEO/Sentinel Hub and CDSE itself calls that experimental, so it is not used.

The manager keeps one token in memory, refreshes it at ~8 minutes (that is, two minutes
before expiry) and falls back to a full password grant when the refresh window has also
closed.  A single lock serialises acquisition so that four concurrent band downloads do
not open four Keycloak sessions — the account is capped at 100.

Credentials never appear in a log line: only the username's presence is ever recorded.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from spilltrace.core.errors import (
    ProviderAuthError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
)
from spilltrace.core.time import utcnow
from spilltrace.logging import get_logger

log = get_logger(__name__)

PROVIDER = "cdse"

#: CONFIRMED (AD-06).  Realm ``CDSE``, public client, ``password`` grant.
CDSE_IDENTITY_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
DEFAULT_CLIENT_ID = "cdse-public"

#: Observed lifetimes, used only as a fallback when the response omits them.
DEFAULT_ACCESS_LIFETIME_SECONDS = 600
DEFAULT_REFRESH_LIFETIME_SECONDS = 3600

#: Renew this long before expiry.  With CDSE's 600 s access token this is the ~8 minute
#: refresh AD-06 specifies; it is expressed as a margin so a shorter token still works.
REFRESH_MARGIN_SECONDS = 120

_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)


@dataclass(frozen=True, slots=True)
class CDSECredentials:
    """Service-account credentials.  Server side only — never sent to a browser."""

    username: str
    password: str
    client_id: str = DEFAULT_CLIENT_ID
    #: Time-based one-time code, when the account has 2FA enabled.
    totp: str | None = None

    def redacted(self) -> dict[str, Any]:
        return {"username_set": bool(self.username), "client_id": self.client_id}


@dataclass(slots=True)
class TokenState:
    """A live token pair and the two clocks that govern it."""

    access_token: str
    expires_at: datetime
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None

    def is_fresh(self, now: datetime, margin_seconds: int) -> bool:
        return now < self.expires_at - timedelta(seconds=margin_seconds)

    def can_refresh(self, now: datetime) -> bool:
        if not self.refresh_token:
            return False
        if self.refresh_expires_at is None:
            return True
        return now < self.refresh_expires_at - timedelta(seconds=REFRESH_MARGIN_SECONDS)


class CDSETokenManager:
    """Acquires, caches and refreshes a CDSE access token."""

    def __init__(
        self,
        credentials: CDSECredentials,
        *,
        client: httpx.AsyncClient | None = None,
        identity_url: str = CDSE_IDENTITY_URL,
        refresh_margin_seconds: int = REFRESH_MARGIN_SECONDS,
    ) -> None:
        if not credentials.username or not credentials.password:
            raise ProviderNotConfiguredError(
                "CDSE_USERNAME and CDSE_PASSWORD are not set, so no Copernicus token "
                "can be requested.",
                provider=PROVIDER,
            )
        self._credentials = credentials
        self._identity_url = identity_url
        self._refresh_margin = refresh_margin_seconds
        self._client = client
        self._owns_client = client is None
        self._state: TokenState | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def invalidate(self) -> None:
        """Forget the cached token.

        Called when the download service answers 401 despite a token we believed valid —
        for instance after a session was revoked server-side.
        """
        self._state = None

    @property
    def state(self) -> TokenState | None:
        return self._state

    # ------------------------------------------------------------------ tokens
    async def access_token(self) -> str:
        now = utcnow()
        state = self._state
        if state is not None and state.is_fresh(now, self._refresh_margin):
            return state.access_token

        async with self._lock:
            # Another coroutine may have refreshed while this one waited for the lock.
            now = utcnow()
            state = self._state
            if state is not None and state.is_fresh(now, self._refresh_margin):
                return state.access_token

            if state is not None and state.can_refresh(now):
                try:
                    self._state = await self._grant(
                        {
                            "grant_type": "refresh_token",
                            "refresh_token": state.refresh_token or "",
                            "client_id": self._credentials.client_id,
                        },
                        kind="refresh",
                    )
                    return self._state.access_token
                except ProviderAuthError as exc:
                    # A rejected refresh is normal once the 60-minute window closes.
                    log.info("cdse_refresh_rejected_reauthenticating", reason=exc.message)

            self._state = await self._grant(self._password_form(), kind="password")
            return self._state.access_token

    def _password_form(self) -> dict[str, str]:
        form = {
            "grant_type": "password",
            "client_id": self._credentials.client_id,
            "username": self._credentials.username,
            "password": self._credentials.password,
        }
        if self._credentials.totp:
            form["totp"] = self._credentials.totp
        return form

    async def _grant(self, form: dict[str, str], *, kind: str) -> TokenState:
        try:
            response = await self._http().post(
                self._identity_url,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                f"Could not reach the Copernicus identity service: {exc}",
                provider=PROVIDER,
                grant=kind,
            ) from exc

        if response.status_code >= 400:
            raise ProviderAuthError(
                _describe_failure(response, kind),
                provider=PROVIDER,
                grant=kind,
                status_code=response.status_code,
            )

        payload = _json_or_error(response, kind)
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ProviderAuthError(
                "The Copernicus identity service returned no access token.",
                provider=PROVIDER,
                grant=kind,
            )

        now = utcnow()
        expires_in = _positive_int(payload.get("expires_in"), DEFAULT_ACCESS_LIFETIME_SECONDS)
        refresh_expires_in = _positive_int(
            payload.get("refresh_expires_in"), DEFAULT_REFRESH_LIFETIME_SECONDS
        )
        refresh = payload.get("refresh_token")
        state = TokenState(
            access_token=token,
            expires_at=now + timedelta(seconds=expires_in),
            refresh_token=refresh if isinstance(refresh, str) and refresh else None,
            refresh_expires_at=now + timedelta(seconds=refresh_expires_in),
        )
        log.info(
            "cdse_token_acquired",
            grant=kind,
            expires_in_seconds=expires_in,
            renews_in_seconds=max(0, expires_in - self._refresh_margin),
            **self._credentials.redacted(),
        )
        return state


def _json_or_error(response: httpx.Response, kind: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderAuthError(
            "The Copernicus identity service returned a non-JSON response.",
            provider=PROVIDER,
            grant=kind,
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderAuthError(
            "The Copernicus identity service returned an unexpected payload.",
            provider=PROVIDER,
            grant=kind,
        )
    return payload


def _describe_failure(response: httpx.Response, kind: str) -> str:
    """Surface Keycloak's own reason, which is the only useful part of a 400."""
    detail = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        detail = str(body.get("error_description") or body.get("error") or "")
    if not detail:
        detail = response.text[:200]
    return f"Copernicus rejected the {kind} grant (HTTP {response.status_code}). {detail}".strip()


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


__all__ = [
    "CDSE_IDENTITY_URL",
    "DEFAULT_CLIENT_ID",
    "REFRESH_MARGIN_SECONDS",
    "CDSECredentials",
    "CDSETokenManager",
    "TokenState",
]
