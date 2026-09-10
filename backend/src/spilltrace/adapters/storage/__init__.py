"""Object storage adapters."""

from __future__ import annotations

from spilltrace.config import Settings, get_settings
from spilltrace.core.ports import ObjectStore


def build_object_store(settings: Settings | None = None) -> ObjectStore:
    settings = settings or get_settings()
    if settings.storage_provider == "local":
        from spilltrace.adapters.storage.local import LocalObjectStore

        return LocalObjectStore(settings.local_storage_root)
    from spilltrace.adapters.storage.s3 import S3ObjectStore

    return S3ObjectStore(settings)


__all__ = ["build_object_store"]
