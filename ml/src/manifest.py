"""The experiment manifest (P11-008, DB-013).

Everything needed to reproduce a checkpoint, and everything needed to judge whether one
of its numbers means anything: the full configuration, the git commit, the dataset
fingerprint, the split hash, the seed, the environment, the measured wall clock, and the
metrics — which stay **empty** unless something actually measured them.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MANIFEST_FILENAME = "manifest.json"


def git_sha(root: str | Path | None = None) -> str:
    """The commit this run came from, or ``unknown`` — never a guess."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(root) if root else None,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = completed.stdout.strip()
    return sha if completed.returncode == 0 and sha else "unknown"


def environment() -> dict[str, Any]:
    info: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
    }
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        info["threads"] = int(torch.get_num_threads())
    except ImportError:
        info["torch"] = None
        info["cuda_available"] = False
    try:
        import numpy

        info["numpy"] = numpy.__version__
    except ImportError:  # pragma: no cover - numpy is a hard dependency
        pass
    return info


@dataclass
class ExperimentManifest:
    """One training or evaluation run, described completely enough to repeat it."""

    name: str
    config: dict[str, Any]
    seed: int
    git_sha: str = field(default_factory=git_sha)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    dataset: dict[str, Any] = field(default_factory=dict)
    split_hash: str = ""
    environment: dict[str, Any] = field(default_factory=environment)
    #: **Measured** metrics only.  An empty dict means nothing was evaluated.
    metrics: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    parameters: int = 0
    notes: list[str] = field(default_factory=list)

    def note(self, message: str) -> ExperimentManifest:
        self.notes.append(message)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "git_sha": self.git_sha,
            "seed": self.seed,
            "config": self.config,
            "dataset": self.dataset,
            "split_hash": self.split_hash,
            "environment": self.environment,
            "parameters": self.parameters,
            "timings": self.timings,
            "metrics": self.metrics,
            "metrics_measured": bool(self.metrics),
            "notes": self.notes,
        }

    def fingerprint(self) -> str:
        payload = self.to_dict()
        payload.pop("created_at")
        payload.pop("timings")
        payload.pop("notes")
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    def save(self, directory: str | Path) -> Path:
        path = Path(directory) / MANIFEST_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return path


__all__ = ["MANIFEST_FILENAME", "ExperimentManifest", "environment", "git_sha"]
