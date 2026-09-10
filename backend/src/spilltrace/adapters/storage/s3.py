"""S3-compatible object storage (MinIO locally, S3 in production).

boto3 is synchronous, so every call runs in a worker thread; the surface stays async
so callers cannot accidentally block the event loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from functools import partial
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from spilltrace.config import Settings, get_settings
from spilltrace.core.errors import StorageError
from spilltrace.core.ports import StoredObject
from spilltrace.logging import get_logger

log = get_logger(__name__)


class S3ObjectStore:
    """Implements :class:`spilltrace.core.ports.ObjectStore`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._bucket = self._settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=self._settings.s3_endpoint_url,
            aws_access_key_id=self._settings.s3_access_key,
            aws_secret_access_key=self._settings.s3_secret_key,
            region_name=self._settings.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        # A separate client bound to the browser-reachable endpoint, so presigned URLs
        # are valid outside the container network.
        self._public_client = boto3.client(
            "s3",
            endpoint_url=self._settings.s3_public_endpoint_url,
            aws_access_key_id=self._settings.s3_access_key,
            aws_secret_access_key=self._settings.s3_secret_key,
            region_name=self._settings.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    # ------------------------------------------------------------------ helpers
    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(partial(fn, *args, **kwargs))
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"Object storage operation failed: {type(exc).__name__}") from exc

    def uri_for(self, key: str) -> str:
        return f"s3://{self._bucket}/{key}"

    def describe(self) -> str:
        return f"s3 bucket '{self._bucket}' at {self._settings.s3_endpoint_url}"

    # ------------------------------------------------------------------ operations
    async def put_bytes(
        self, key: str, data: bytes, *, media_type: str | None = None
    ) -> StoredObject:
        checksum = hashlib.sha256(data).hexdigest()
        media_type = media_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
        await self._run(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=media_type,
            Metadata={"sha256": checksum},
        )
        log.info("object_stored", key=key, size_bytes=len(data))
        return StoredObject(
            uri=self.uri_for(key),
            key=key,
            size_bytes=len(data),
            checksum_sha256=checksum,
            media_type=media_type,
        )

    async def put_file(self, key: str, path: str, *, media_type: str | None = None) -> StoredObject:
        file_path = Path(path)
        # Cheap stat() guards; every byte-moving call below is offloaded to a thread.
        if not file_path.is_file():  # noqa: ASYNC240
            raise StorageError(f"File to upload does not exist: {key}")
        checksum = await asyncio.to_thread(_sha256_file, file_path)
        size = file_path.stat().st_size  # noqa: ASYNC240
        media_type = media_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
        await self._run(
            self._client.upload_file,
            str(file_path),
            self._bucket,
            key,
            ExtraArgs={"ContentType": media_type, "Metadata": {"sha256": checksum}},
        )
        log.info("object_uploaded", key=key, size_bytes=size)
        return StoredObject(
            uri=self.uri_for(key),
            key=key,
            size_bytes=size,
            checksum_sha256=checksum,
            media_type=media_type,
        )

    async def get_bytes(self, key: str) -> bytes:
        response = await self._run(self._client.get_object, Bucket=self._bucket, Key=key)
        return await asyncio.to_thread(response["Body"].read)

    async def exists(self, key: str) -> bool:
        try:
            await self._run(self._client.head_object, Bucket=self._bucket, Key=key)
        except StorageError:
            return False
        return True

    async def delete(self, key: str) -> None:
        await self._run(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def presigned_url(self, key: str, *, expires_seconds: int = 3600) -> str:
        return await self._run(
            self._public_client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    async def healthcheck(self) -> None:
        await self._run(self._client.head_bucket, Bucket=self._bucket)


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["S3ObjectStore"]
