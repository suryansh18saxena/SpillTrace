"""The on-disk shape of a downloaded scene.

``SatelliteCatalogue.download`` returns a single :class:`StoredObject`, but a Sentinel-1
GRD is fetched as **one file per polarisation** (AD-08).  The bundle manifest is what
reconciles the two: the returned object describes the *directory*, and ``bundle.json``
inside it names every band with its own size and checksum.

The directory-level checksum is a hash over the sorted ``(filename, sha256)`` pairs, not
over the bytes of a concatenation — that keeps it stable regardless of download order and
verifiable without re-reading gigabytes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spilltrace.core.enums import DataProvenance
from spilltrace.core.ports import StoredObject

BUNDLE_FILENAME = "bundle.json"
BUNDLE_MEDIA_TYPE = "application/vnd.spilltrace.scene-bundle+json"


@dataclass(frozen=True, slots=True)
class SceneBand:
    """One measurement file: a single polarisation of one scene."""

    polarization: str
    filename: str
    size_bytes: int
    checksum_sha256: str
    source_url: str | None = None
    is_cog: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "polarization": self.polarization,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "checksum_sha256": self.checksum_sha256,
            "source_url": self.source_url,
            "is_cog": self.is_cog,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SceneBand:
        return cls(
            polarization=str(payload["polarization"]),
            filename=str(payload["filename"]),
            size_bytes=int(payload.get("size_bytes") or 0),
            checksum_sha256=str(payload.get("checksum_sha256") or ""),
            source_url=payload.get("source_url"),
            is_cog=bool(payload.get("is_cog")),
        )


@dataclass(frozen=True, slots=True)
class SceneBundle:
    product_id: str
    provider: str
    bands: tuple[SceneBand, ...]
    data_provenance: DataProvenance = DataProvenance.REAL
    notes: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def total_bytes(self) -> int:
        return sum(band.size_bytes for band in self.bands)

    def band(self, polarization: str) -> SceneBand | None:
        wanted = polarization.upper()
        for candidate in self.bands:
            if candidate.polarization.upper() == wanted:
                return candidate
        return None

    def manifest_checksum(self) -> str:
        digest = hashlib.sha256()
        for band in sorted(self.bands, key=lambda b: b.filename):
            digest.update(f"{band.filename}:{band.checksum_sha256}\n".encode())
        return digest.hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "provider": self.provider,
            "bands": [band.to_dict() for band in self.bands],
            "data_provenance": str(self.data_provenance),
            "notes": list(self.notes),
            "extra": dict(self.extra),
            "manifest_checksum_sha256": self.manifest_checksum(),
            "total_bytes": self.total_bytes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SceneBundle:
        return cls(
            product_id=str(payload["product_id"]),
            provider=str(payload.get("provider") or "unknown"),
            bands=tuple(SceneBand.from_dict(b) for b in payload.get("bands") or []),
            data_provenance=DataProvenance(payload.get("data_provenance", "REAL")),
            notes=tuple(payload.get("notes") or ()),
            extra=dict(payload.get("extra") or {}),
        )


def write_bundle(directory: str | Path, bundle: SceneBundle) -> Path:
    path = Path(directory) / BUNDLE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def read_bundle(directory: str | Path) -> SceneBundle:
    path = Path(directory) / BUNDLE_FILENAME
    return SceneBundle.from_dict(json.loads(path.read_text(encoding="utf-8")))


def bundle_stored_object(directory: str | Path, bundle: SceneBundle) -> StoredObject:
    """Describe the downloaded directory as one :class:`StoredObject`."""
    resolved = Path(directory).resolve()
    return StoredObject(
        uri=f"file://{resolved}",
        key=str(resolved),
        size_bytes=bundle.total_bytes,
        checksum_sha256=bundle.manifest_checksum(),
        media_type=BUNDLE_MEDIA_TYPE,
    )


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "BUNDLE_FILENAME",
    "BUNDLE_MEDIA_TYPE",
    "SceneBand",
    "SceneBundle",
    "bundle_stored_object",
    "read_bundle",
    "sha256_file",
    "write_bundle",
]
