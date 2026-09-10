"""Error envelope and exception handlers (docs/API.md §1)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from spilltrace.core.errors import SpilltraceError
from spilltrace.logging import get_logger, request_id_var

log = get_logger(__name__)


def error_response(
    *, code: str, message: str, http_status: int, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id_var.get(),
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SpilltraceError)
    async def _domain(_r: Request, exc: SpilltraceError) -> JSONResponse:
        log.warning("domain_error", code=exc.code, message=exc.message, **exc.details)
        return error_response(
            code=exc.code,
            message=exc.message,
            http_status=exc.http_status,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            code="VALIDATION_ERROR",
            message="The request could not be validated.",
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"errors": _serialise_validation_errors(exc)},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_r: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            401: "AUTHENTICATION_FAILED",
            403: "NOT_AUTHORIZED",
            404: "NOT_FOUND",
            429: "RATE_LIMITED",
        }
        return error_response(
            code=codes.get(exc.status_code, "HTTP_ERROR"),
            message=str(exc.detail),
            http_status=exc.status_code,
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_r: Request, exc: IntegrityError) -> JSONResponse:
        # The driver message can contain row values; never return it to the caller.
        log.warning("integrity_error", error=str(exc.orig))
        return error_response(
            code="CONFLICT",
            message="The request conflicts with existing data.",
            http_status=status.HTTP_409_CONFLICT,
        )

    @app.exception_handler(SQLAlchemyError)
    async def _sqlalchemy(_r: Request, exc: SQLAlchemyError) -> JSONResponse:
        log.error("database_error", error=str(exc), exc_info=True)
        return error_response(
            code="DATABASE_ERROR",
            message="A database error occurred.",
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @app.exception_handler(Exception)
    async def _unhandled(_r: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", error=str(exc), exc_info=True)
        return error_response(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _serialise_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for err in exc.errors():
        out.append(
            {
                "field": ".".join(str(p) for p in err.get("loc", ())),
                "message": err.get("msg", "invalid"),
                "type": err.get("type", "value_error"),
            }
        )
    return out


__all__ = ["error_response", "register_exception_handlers"]
