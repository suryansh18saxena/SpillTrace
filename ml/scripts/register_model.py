"""Register a trained checkpoint in ``model_versions`` (P11-008, DB-013).

```
python ml/scripts/register_model.py \
    --checkpoint runs/unet-cpu-baseline/best.pt \
    --manifest   runs/unet-cpu-baseline/manifest.json \
    --version 0.1.0 --activate
```

The checkpoint is uploaded to object storage and a row is written carrying its SHA-256,
input geometry, normalisation description and training manifest.

**Metrics are copied only from a manifest that measured them.**  If the manifest's
``metrics`` is empty the row's ``metrics`` stays empty, the notes say the model is
unevaluated, and ``--activate`` is refused — an unevaluated model may be registered, but
it may not silently become the one every detection uses.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

MODEL_NAME = "spilltrace-unet"


def load_manifest(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def measured_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    """The metrics the manifest actually measured, or an empty dict.

    Never synthesises, defaults or rounds up a missing number.
    """
    metrics = manifest.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return {}
    return metrics


async def register(
    checkpoint: Path,
    *,
    version: str,
    manifest: dict[str, Any],
    activate: bool,
    name: str = MODEL_NAME,
) -> dict[str, Any]:
    from spilltrace.adapters.storage import build_object_store
    from spilltrace.config import get_settings
    from spilltrace.db.models import ModelVersion
    from spilltrace.db.session import session_scope
    from sqlalchemy import select, update

    settings = get_settings()
    payload = await asyncio.to_thread(checkpoint.read_bytes)
    checksum = hashlib.sha256(payload).hexdigest()

    store = build_object_store(settings)
    stored = await store.put_bytes(
        f"models/{name}/{version}/{checkpoint.name}",
        payload,
        media_type="application/octet-stream",
    )

    metrics = measured_metrics(manifest)
    config = manifest.get("config") or {}
    model_config = config.get("model") or {}
    data_config = config.get("data") or {}

    notes = []
    if metrics and "validation" in metrics and not metrics.get("test"):
        notes.append(
            "Metrics are VALIDATION-split numbers from the training run (no independent "
            "test split was evaluated); treat them as an upper bound."
        )
    elif metrics:
        notes.append("Metrics were measured by ml/src/train.py on the split named in the manifest.")
    else:
        notes.append(
            "This model version has NOT been evaluated: no metrics were measured, so "
            "none are recorded. Do not present it as having any accuracy."
        )
    if data_config.get("synthetic"):
        notes.append(
            "Trained on SYNTHETIC generated data. Its numbers say nothing about "
            "performance on real Sentinel-1 imagery."
        )
    notes.append(
        "Public SAR oil-spill benchmarks are overwhelmingly European waters; performance "
        "elsewhere is documented to degrade (AD-13)."
    )
    for note in manifest.get("notes") or []:
        if isinstance(note, str) and note not in notes:
            notes.append(note)

    async with session_scope() as session:
        existing = (
            await session.execute(
                select(ModelVersion).where(
                    ModelVersion.name == name, ModelVersion.version == version
                )
            )
        ).scalar_one_or_none()
        row = existing or ModelVersion(name=name, version=version)
        row.framework = "pytorch"
        row.task = "oil-slick-segmentation"
        row.metrics = metrics
        row.params = model_config
        row.training_manifest = manifest
        row.artifact_uri = stored.uri
        row.checksum_sha256 = checksum
        row.input_channels = int(model_config.get("in_channels") or 2)
        row.input_size = int(data_config.get("patch_size") or 128)
        row.normalization = {
            "method": "per-scene percentile clip then standardise",
            "percentiles": [1.0, 99.0],
            "reference": "docs/DECISIONS.md AD-12",
        }
        row.notes = " ".join(notes)
        if existing is None:
            session.add(row)
        await session.flush()

        if activate:
            if not metrics:
                raise SystemExit(
                    "Refusing to activate a model version with no measured metrics. "
                    "Run ml/src/evaluate.py first, or register without --activate."
                )
            await session.execute(
                update(ModelVersion).where(ModelVersion.name == name).values(is_active=False)
            )
            row.is_active = True
            await session.flush()

        return {
            "model_version_id": str(row.id),
            "name": name,
            "version": version,
            "artifact_uri": stored.uri,
            "checksum_sha256": checksum,
            "metrics_measured": bool(metrics),
            "is_active": bool(row.is_active),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register a checkpoint in model_versions.")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--version", required=True)
    parser.add_argument("--name", default=MODEL_NAME)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args(argv)

    checkpoint = Path(args.checkpoint)
    if not checkpoint.is_file():
        print(f"Checkpoint not found: {checkpoint}", file=sys.stderr)
        return 2

    result = asyncio.run(
        register(
            checkpoint,
            version=args.version,
            manifest=load_manifest(args.manifest),
            activate=args.activate,
            name=args.name,
        )
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
