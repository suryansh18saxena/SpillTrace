"""Domain errors.

Every error carries a stable machine-readable ``code``.  The API layer renders these
into the error envelope documented in ``docs/API.md``; messages are written to be safe
to show a user and never contain credentials or internal paths (NFR-004, NFR-011).
"""

from __future__ import annotations

from typing import Any


class SpilltraceError(Exception):
    """Base class for every SPILLTRACE domain error."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str, /, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationError(SpilltraceError):
    code = "VALIDATION_ERROR"
    http_status = 422


class InvalidGeometryError(ValidationError):
    code = "INVALID_GEOMETRY"


class InvalidTimeWindowError(ValidationError):
    code = "INVALID_TIME_WINDOW"


class NotFoundError(SpilltraceError):
    code = "NOT_FOUND"
    http_status = 404


class ConflictError(SpilltraceError):
    code = "CONFLICT"
    http_status = 409


class AuthenticationError(SpilltraceError):
    code = "AUTHENTICATION_FAILED"
    http_status = 401


class AuthorizationError(SpilltraceError):
    code = "NOT_AUTHORIZED"
    http_status = 403


class RateLimitError(SpilltraceError):
    code = "RATE_LIMITED"
    http_status = 429


class ProviderError(SpilltraceError):
    """An external data provider failed.

    Raised by adapters so the worker can record a ``FAILED`` job with an honest reason
    instead of silently substituting fabricated data (CON-009, NFR-011).
    """

    code = "PROVIDER_ERROR"
    http_status = 503

    def __init__(self, message: str, /, provider: str, **details: Any) -> None:
        super().__init__(message, provider=provider, **details)
        self.provider = provider


class ProviderUnavailableError(ProviderError):
    code = "PROVIDER_UNAVAILABLE"


class ProviderAuthError(ProviderError):
    code = "PROVIDER_AUTH_FAILED"


class ProviderNotConfiguredError(ProviderError):
    code = "PROVIDER_NOT_CONFIGURED"


class ProcessingError(SpilltraceError):
    """A pipeline stage could not produce a valid artifact."""

    code = "PROCESSING_FAILED"
    http_status = 500


class NoDataError(ProcessingError):
    """A stage completed but found nothing.

    This is a legitimate outcome, not a bug: no scenes in the AOI, no slick in the
    scene, no vessels in the origin region.  It must be reported honestly (A-10).
    """

    code = "NO_DATA"
    http_status = 200


class ModelNotAvailableError(ProcessingError):
    code = "MODEL_NOT_AVAILABLE"
    http_status = 503


class StorageError(SpilltraceError):
    code = "STORAGE_ERROR"
    http_status = 500
