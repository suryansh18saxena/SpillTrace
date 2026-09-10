"""Provenance and reproducibility helpers (CON-009, NFR-005).

Two ideas live here:

``DataProvenance``    — did this artifact come from a real observation or from
                        deterministic synthetic data?
``RunManifest``       — everything needed to explain how an artifact was produced.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from spilltrace.core.enums import DataProvenance

#: Suffix appended to synthetic vessel names so they can never be read as real vessels.
SYNTHETIC_LABEL = "(SYNTHETIC)"


def combine_provenance(*values: DataProvenance | str | None) -> DataProvenance:
    """Provenance of an artifact derived from several inputs.

    Any synthetic input makes the result at best ``MIXED``; a result is ``REAL`` only
    when every contributing input was real.
    """
    seen = {DataProvenance(v) for v in values if v is not None}
    if not seen:
        return DataProvenance.REAL
    if seen == {DataProvenance.REAL}:
        return DataProvenance.REAL
    if seen == {DataProvenance.SYNTHETIC}:
        return DataProvenance.SYNTHETIC
    return DataProvenance.MIXED


def label_synthetic(name: str, provenance: DataProvenance | str) -> str:
    """Append the synthetic marker to a display name when appropriate."""
    if DataProvenance(provenance) is DataProvenance.REAL:
        return name
    if SYNTHETIC_LABEL in name:
        return name
    return f"{name} {SYNTHETIC_LABEL}".strip()


@dataclass(slots=True)
class RunManifest:
    """Reproducibility envelope stored alongside every derived artifact.

    An investigator reading the evidence report must be able to see exactly which
    software, which inputs and which parameters produced a result (NFR-005, AC-12).
    """

    stage: str
    software_version: str
    git_sha: str = "unknown"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    provider: str | None = None
    provider_parameters: dict[str, Any] = field(default_factory=dict)
    model_name: str | None = None
    model_version: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None
    inputs: dict[str, str] = field(default_factory=dict)
    data_provenance: DataProvenance = DataProvenance.REAL
    notes: list[str] = field(default_factory=list)

    def with_input(self, name: str, checksum: str) -> RunManifest:
        self.inputs[name] = checksum
        return self

    def note(self, message: str) -> RunManifest:
        self.notes.append(message)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "software_version": self.software_version,
            "git_sha": self.git_sha,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "provider": self.provider,
            "provider_parameters": self.provider_parameters,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "parameters": self.parameters,
            "seed": self.seed,
            "inputs": self.inputs,
            "data_provenance": str(self.data_provenance),
            "notes": self.notes,
        }

    def fingerprint(self) -> str:
        """Stable hash of everything that affects the result.

        Excludes ``created_at`` and ``notes`` so that re-running the same computation
        yields the same fingerprint — this is what makes AC-07 testable.
        """
        payload = self.to_dict()
        payload.pop("created_at")
        payload.pop("notes")
        return sha256_of_json(payload)


def sha256_of_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "SYNTHETIC_LABEL",
    "RunManifest",
    "combine_provenance",
    "label_synthetic",
    "sha256_of_bytes",
    "sha256_of_json",
]
