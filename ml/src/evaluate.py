"""Evaluate a checkpoint on a named split (ML_PIPELINE §7).

```
python -m evaluate --checkpoint runs/<name>/best.pt --config runs/<name>/config.json \
    --split test
```

Reports **oil-class** Dice, IoU, precision and recall at a stated threshold, plus a
threshold sweep and pixel accuracy — the last of which is printed and never headlined,
because a model that predicts nothing scores ~99% on it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import TrainConfig, load_config
from dataset.splits import resolve_splits
from manifest import ExperimentManifest
from metrics import best_threshold, confusion, summarise, threshold_sweep
from train import build_tilesets, evaluate_split, load_pairs, require_torch


def load_checkpoint_config(checkpoint: dict[str, Any], fallback: TrainConfig) -> TrainConfig:
    """Prefer the config saved beside the weights over anything passed on the CLI."""
    saved = checkpoint.get("config")
    if isinstance(saved, dict):
        try:
            return TrainConfig.from_dict(saved)
        except (TypeError, ValueError):
            pass
    return fallback


def evaluate(
    checkpoint_path: str | Path,
    config: TrainConfig,
    *,
    split: str = "test",
    threshold: float | None = None,
) -> dict[str, Any]:
    torch = require_torch()
    from dataset.torch_data import TileDataset, build_loader
    from model import build_model, parameter_count

    device = config.resolve_device()
    payload = torch.load(str(checkpoint_path), map_location=device, weights_only=False)
    config = load_checkpoint_config(payload, config)

    model = build_model(config.model).to(device)
    model.load_state_dict(payload["state_dict"])
    model.eval()

    pairs = load_pairs(config)
    split_root = (
        Path(config.data.root)
        if config.data.root and not config.data.synthetic
        else Path(config.output_dir) / config.name
    )
    splits = resolve_splits(
        split_root,
        [pair.name for pair in pairs],
        val_fraction=config.data.val_fraction,
        test_fraction=config.data.test_fraction,
        seed=config.seed,
        regenerate=config.data.synthetic,
    )
    tilesets = build_tilesets(config, pairs, splits)
    if split not in tilesets:
        raise SystemExit(f"Split '{split}' is empty for this dataset.")

    loader = build_loader(TileDataset(tilesets[split]), batch_size=config.optim.batch_size)
    probabilities, targets = evaluate_split(model, loader, torch, device)

    sweep = threshold_sweep(probabilities, targets)
    operating = (
        float(threshold) if threshold is not None else float(best_threshold(sweep)["threshold"])
    )
    point = summarise(confusion(np.asarray(probabilities) >= operating, targets))

    manifest = ExperimentManifest(
        name=f"{config.name}-eval-{split}",
        config=config.to_dict(),
        seed=config.seed,
        dataset={
            "source": "synthetic" if config.data.synthetic else str(config.data.root),
            "split": split,
            "tiles": tilesets[split].to_dict(),
        },
        split_hash=splits.hash,
        parameters=parameter_count(model),
        metrics={"operating_point": {**point, "threshold": operating}, "sweep": sweep},
    )
    manifest.note(
        "Oil-class metrics only. A mean over classes including 'sea' would be dominated "
        "by trivially easy pixels (AD-10)."
    )
    if config.data.synthetic:
        manifest.note("Measured on SYNTHETIC data; not a statement about real imagery.")
    return manifest.to_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a SPILLTRACE checkpoint.")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--split", default="test", choices=("train", "val", "test"))
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--output", default=None, help="Write the report to this JSON file.")
    args = parser.parse_args(argv)

    report = evaluate(
        args.checkpoint,
        load_config(args.config),
        split=args.split,
        threshold=args.threshold,
    )
    text = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
