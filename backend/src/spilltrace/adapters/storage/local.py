"""Filesystem object store.

Used by tests and by anyone running without MinIO.  Implements the same port so no
caller can tell the difference (AD-2).
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import shutil
from pathlib import Path

from spilltrace.core.errors import StorageError
from spilltrace.core.ports import StoredObject


class LocalObjectStore:
    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Reject traversal before touching the filesystem.
        candidate = (self._root / key).resolve()
        if not str(candidate).startswith(str(self._root.resolve())):
            raise StorageError("Rejected object key that escapes the storage root.")
        return candidate

    def uri_for(self, key: str) -> str:
        return f"file://{self._path(key)}"

    def describe(self) -> str:
        return f"local filesystem at {self._root}"

    async def put_bytes(
        self, key: str, data: bytes, *, media_type: str | None = None
    ) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return StoredObject(
            uri=self.uri_for(key),
            key=key,
            size_bytes=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            media_type=media_type or mimetypes.guess_type(key)[0],
        )

    async def put_file(self, key: str, path: str, *, media_type: str | None = None) -> StoredObject:
        source = Path(path)
        # A stat() guard before the copy; the copy itself is offloaded below.
        if not source.is_file():  # noqa: ASYNC240
            raise StorageError(f"File to upload does not exist: {key}")
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, source, target)
        data = await asyncio.to_thread(target.read_bytes)
        return StoredObject(
            uri=self.uri_for(key),
            key=key,
            size_bytes=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            media_type=media_type or mimetypes.guess_type(key)[0],
        )

    async def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"Object not found: {key}")
        return await asyncio.to_thread(path.read_bytes)

    async def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            await asyncio.to_thread(path.unlink)

    async def presigned_url(self, key: str, *, expires_seconds: int = 3600) -> str:
        # No signing for a local store; the API streams these bytes itself.
        return f"/api/v1/artifacts/local/{key}"

    async def healthcheck(self) -> None:
        if not self._root.is_dir():
            raise StorageError("Local storage root is not a directory.")


__all__ = ["LocalObjectStore"]
