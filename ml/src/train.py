"""Training entry point (ML_PIPELINE §6).

```
python -m train --config configs/cpu_baseline.yaml
python -m train --config configs/synthetic_smoke.yaml --benchmark-epoch
```

Design commitments, all of which exist to keep the reported number honest:

* the split is at **image level** and its hash goes in the manifest;
* the model selected is the best **validation oil-class Dice**, not the best loss;
* the operating threshold is chosen on **validation**, and only then applied to test;
* wall clock is measured, not estimated — ``--benchmark-epoch`` runs exactly one epoch
  and reports what it cost, which is what AD-11 asks for before committing to a long run;
* every metric written to ``metrics.json`` was computed by this script on data it names.

PyTorch is required *here* and nowhere else in the package.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import TrainConfig, load_config
from dataset.augment import AugmentConfig
from dataset.loader import ImagePair, discover_pairs, load_pair, load_synthetic_pairs
from dataset.splits import Splits, resolve_splits
from dataset.tiles import TileSet, build_tileset
from manifest import ExperimentManifest
from metrics import (
    ConfusionMatrix,
    best_threshold,
    confusion,
    summarise,
    threshold_sweep,
)

CHECKPOINT_NAME = "best.pt"
LAST_CHECKPOINT_NAME = "last.pt"
METRICS_NAME = "metrics.json"


def require_torch() -> Any:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - exercised only without torch
        raise SystemExit(
            "PyTorch is not installed. Training needs it; nothing else in ml/ does.\n"
            "  pip install --index-url https://download.pytorch.org/whl/cpu torch\n"
            "or rebuild the backend image with: make build-ml"
        ) from exc
    return torch


# --------------------------------------------------------------------------- data
def load_pairs(config: TrainConfig) -> list[ImagePair]:
    if config.data.synthetic:
        return load_synthetic_pairs(
            config.data.synthetic_images,
            size=config.data.synthetic_size,
            seed=config.seed,
        )
    if not config.data.root:
        raise SystemExit("data.root is not set and data.synthetic is false.")
    found = discover_pairs(config.data.root)
    if not found:
        raise SystemExit(
            f"No image/mask pairs found under {config.data.root}. Run "
            "ml/scripts/download_dataset.py, or set data.synthetic: true."
        )
    if config.data.max_images:
        found = found[: config.data.max_images]
    return [load_pair(name, image, mask) for name, image, mask in found]


def build_tilesets(
    config: TrainConfig, pairs: list[ImagePair], splits: Splits
) -> dict[str, TileSet]:
    by_name = {pair.name: pair for pair in pairs}
    sets: dict[str, TileSet] = {}
    for split, members in (
        ("train", splits.train),
        ("val", splits.val),
        ("test", splits.test),
    ):
        selected = [
            (name, by_name[name].image, by_name[name].mask) for name in members if name in by_name
        ]
        if not selected:
            continue
        sets[split] = build_tileset(
            selected,
            patch_size=config.data.patch_size,
            stride=config.data.stride,
            # Only the training split is subsampled: validation and test must describe
            # the data as it actually is, or their numbers describe something else.
            empty_tile_fraction=config.data.empty_tile_fraction if split == "train" else None,
            seed=config.seed,
        )
    return sets


# --------------------------------------------------------------------------- loops
def evaluate_split(
    model: Any, loader: Any, torch: Any, device: str
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(probabilities, targets)`` flattened over the split."""
    model.eval()
    probabilities: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    with torch.inference_mode():
        for images, masks in loader:
            logits = model(images.to(device))
            probabilities.append(torch.sigmoid(logits).cpu().numpy().ravel())
            targets.append(masks.numpy().ravel())
    if not probabilities:
        return np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.float32)
    return np.concatenate(probabilities), np.concatenate(targets)


def train_one_epoch(
    model: Any,
    loader: Any,
    optimiser: Any,
    criterion: Any,
    torch: Any,
    *,
    epoch: int,
    device: str,
    grad_clip: float,
) -> float:
    model.train()
    total, batches = 0.0, 0
    for images, masks in loader:
        optimiser.zero_grad(set_to_none=True)
        logits = model(images.to(device))
        loss = criterion(logits, masks.to(device), epoch=epoch)
        loss.backward()
        if grad_clip > 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
        optimiser.step()
        total += float(loss.item())
        batches += 1
    return total / max(1, batches)


# --------------------------------------------------------------------------- driver
def run(
    config: TrainConfig,
    *,
    benchmark_epoch: bool = False,
    regenerate_splits: bool = False,
) -> dict[str, Any]:
    torch = require_torch()
    from dataset.torch_data import TileDataset, build_loader
    from losses import CompoundLoss
    from model import build_model, parameter_count

    torch.manual_seed(config.seed)
    np.random.seed(config.seed)
    torch.set_num_threads(max(1, config.optim.threads))
    device = config.resolve_device()

    output_dir = Path(config.output_dir) / config.name
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    pairs = load_pairs(config)
    split_root = (
        Path(config.data.root) if config.data.root and not config.data.synthetic else output_dir
    )
    splits = resolve_splits(
        split_root,
        [pair.name for pair in pairs],
        val_fraction=config.data.val_fraction,
        test_fraction=config.data.test_fraction,
        seed=config.seed,
        regenerate=regenerate_splits or config.data.synthetic,
    )
    tilesets = build_tilesets(config, pairs, splits)
    if "train" not in tilesets:
        raise SystemExit("The training split is empty; there is nothing to fit.")
    load_seconds = time.perf_counter() - started

    train_loader = build_loader(
        TileDataset(
            tilesets["train"],
            augment_config=AugmentConfig() if config.data.augment else None,
            seed=config.seed,
        ),
        batch_size=config.optim.batch_size,
        shuffle=True,
        num_workers=config.optim.num_workers,
        seed=config.seed,
    )
    val_loader = (
        build_loader(
            TileDataset(tilesets["val"]),
            batch_size=config.optim.batch_size,
            num_workers=0,
            seed=config.seed,
        )
        if "val" in tilesets
        else None
    )

    model = build_model(config.model).to(device)
    criterion = CompoundLoss(
        bce_weight=config.loss.bce_weight,
        dice_weight=config.loss.dice_weight,
        pos_weight_max=config.loss.pos_weight_max,
        dice_epsilon=config.loss.dice_epsilon,
        warmup_epochs=config.optim.warmup_epochs,
    )
    optimiser = torch.optim.AdamW(
        model.parameters(), lr=config.optim.lr, weight_decay=config.optim.weight_decay
    )
    scheduler = (
        torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=max(1, config.optim.epochs))
        if config.optim.scheduler == "cosine"
        else None
    )

    manifest = ExperimentManifest(
        name=config.name,
        config=config.to_dict(),
        seed=config.seed,
        dataset={
            "source": "synthetic" if config.data.synthetic else str(config.data.root),
            "images": len(pairs),
            "splits": {name: len(tiles) for name, tiles in tilesets.items()},
            "tiles": {name: tiles.to_dict() for name, tiles in tilesets.items()},
            "augmentation": AugmentConfig().to_dict() if config.data.augment else None,
            "loss": criterion.describe(),
        },
        split_hash=splits.hash,
        parameters=parameter_count(model),
    )
    if config.data.synthetic:
        manifest.note(
            "Trained on the deterministic SYNTHETIC generator. Every metric below "
            "describes synthetic data and says nothing about Sentinel-1 performance."
        )
    manifest.note(
        "The split is ours, not the dataset authors'; these numbers are not comparable "
        "to published benchmarks on the same data (AD-10)."
    )

    epochs = 1 if benchmark_epoch else config.optim.epochs
    history: list[dict[str, Any]] = []
    best_dice, best_epoch, patience = -1.0, -1, 0
    epoch_seconds: list[float] = []

    for epoch in range(epochs):
        train_loader.dataset.set_epoch(epoch)  # type: ignore[attr-defined]
        epoch_started = time.perf_counter()
        loss = train_one_epoch(
            model,
            train_loader,
            optimiser,
            criterion,
            torch,
            epoch=epoch,
            device=device,
            grad_clip=config.optim.grad_clip,
        )
        elapsed = time.perf_counter() - epoch_started
        epoch_seconds.append(elapsed)
        if scheduler is not None:
            scheduler.step()

        record: dict[str, Any] = {
            "epoch": epoch,
            "train_loss": round(loss, 6),
            "seconds": round(elapsed, 3),
            "dice_active": criterion.dice_active(epoch),
            "lr": optimiser.param_groups[0]["lr"],
        }
        if val_loader is not None:
            probabilities, targets = evaluate_split(model, val_loader, torch, device)
            validation = summarise(confusion(probabilities >= config.threshold, targets))
            record["val"] = validation
            if validation["dice"] > best_dice:
                best_dice, best_epoch, patience = validation["dice"], epoch, 0
                _save_checkpoint(
                    torch, output_dir / CHECKPOINT_NAME, model, config, epoch, validation
                )
            else:
                patience += 1
        history.append(record)
        print(json.dumps(record), flush=True)

        if val_loader is not None and patience >= config.optim.early_stop_patience:
            manifest.note(f"Early stop at epoch {epoch}: no val Dice improvement in {patience}.")
            break

    _save_checkpoint(torch, output_dir / LAST_CHECKPOINT_NAME, model, config, len(history) - 1, {})
    manifest.timings = {
        "data_load_seconds": round(load_seconds, 3),
        "mean_epoch_seconds": round(float(np.mean(epoch_seconds)), 3) if epoch_seconds else 0.0,
        "total_seconds": round(time.perf_counter() - started, 3),
        "epochs_run": len(history),
    }

    results: dict[str, Any] = {"history": history}
    if benchmark_epoch:
        manifest.note(
            "Benchmark run: one epoch only, to measure wall clock before committing to a "
            "full run. The metrics below are from a single epoch and mean nothing else."
        )
    else:
        # Reload the best checkpoint before measuring anything that gets published.
        checkpoint_path = output_dir / CHECKPOINT_NAME
        if checkpoint_path.is_file():
            payload = torch.load(str(checkpoint_path), map_location=device, weights_only=False)
            model.load_state_dict(payload["state_dict"])
        results.update(_final_metrics(model, tilesets, config, torch, device, manifest))

    manifest.metrics = results.get("metrics", {})
    manifest.save(output_dir)
    (output_dir / METRICS_NAME).write_text(
        json.dumps({"history": history, **results}, indent=2), encoding="utf-8"
    )
    config.save(output_dir / "config.json")
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "best_epoch": best_epoch,
                "best_val_dice": round(best_dice, 6) if best_dice >= 0 else None,
                "parameters": manifest.parameters,
                "timings": manifest.timings,
                "metrics_measured": bool(manifest.metrics),
            },
            indent=2,
        )
    )
    return {"manifest": manifest.to_dict(), **results}


def _final_metrics(
    model: Any,
    tilesets: dict[str, TileSet],
    config: TrainConfig,
    torch: Any,
    device: str,
    manifest: ExperimentManifest,
) -> dict[str, Any]:
    """Choose the operating point on validation, then report test at that point."""
    from dataset.torch_data import TileDataset, build_loader

    metrics: dict[str, Any] = {}
    operating_threshold = config.threshold
    sweep: list[dict[str, Any]] = []

    if "val" in tilesets:
        loader = build_loader(TileDataset(tilesets["val"]), batch_size=config.optim.batch_size)
        probabilities, targets = evaluate_split(model, loader, torch, device)
        sweep = threshold_sweep(probabilities, targets)
        chosen = best_threshold(sweep)
        operating_threshold = float(chosen["threshold"])
        metrics["validation"] = chosen
        metrics["validation_sweep"] = sweep

    for split in ("test", "train"):
        if split not in tilesets:
            continue
        loader = build_loader(TileDataset(tilesets[split]), batch_size=config.optim.batch_size)
        probabilities, targets = evaluate_split(model, loader, torch, device)
        matrix: ConfusionMatrix = confusion(probabilities >= operating_threshold, targets)
        metrics[split] = {**summarise(matrix), "threshold": operating_threshold}

    metrics["operating_threshold"] = operating_threshold
    metrics["threshold_selected_on"] = "validation"
    manifest.note(
        f"Operating threshold {operating_threshold} was selected on validation and then "
        "applied unchanged to test."
    )
    return {"metrics": metrics}


def _save_checkpoint(
    torch: Any, path: Path, model: Any, config: TrainConfig, epoch: int, metrics: dict[str, Any]
) -> None:
    torch.save(
        {
            "state_dict": model.state_dict(),
            "model_config": {
                "in_channels": config.model.in_channels,
                "out_channels": config.model.out_channels,
                "base_filters": config.model.base_filters,
                "depth": config.model.depth,
                "norm_groups": config.model.norm_groups,
                "dropout": config.model.dropout,
            },
            "config": config.to_dict(),
            "epoch": epoch,
            # Empty unless this checkpoint was actually evaluated.
            "metrics": metrics,
        },
        str(path),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the SPILLTRACE U-Net.")
    parser.add_argument("--config", type=str, default=None, help="Path to a YAML config.")
    parser.add_argument("--name", type=str, default=None, help="Override the run name.")
    parser.add_argument("--epochs", type=int, default=None, help="Override optim.epochs.")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument(
        "--benchmark-epoch",
        action="store_true",
        help="Run exactly one epoch and report the measured wall clock (AD-11).",
    )
    parser.add_argument(
        "--regenerate-splits",
        action="store_true",
        help="Rebuild splits.json. Every previously reported metric becomes stale.",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.name:
        config = config.with_overrides(name=args.name)
    if args.output_dir:
        config = config.with_overrides(output_dir=args.output_dir)
    if args.epochs is not None:
        from dataclasses import replace

        config = config.with_overrides(optim=replace(config.optim, epochs=args.epochs))

    run(config, benchmark_epoch=args.benchmark_epoch, regenerate_splits=args.regenerate_splits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
