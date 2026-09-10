"""``python -m spilltrace.api`` — run the API server."""

from __future__ import annotations

import uvicorn

from spilltrace.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "spilltrace.api.app:app",
        host="0.0.0.0",  # noqa: S104 - container-internal bind, published selectively
        port=8000,
        reload=settings.environment == "development",
        reload_dirs=["/app/backend/src"] if settings.environment == "development" else None,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
