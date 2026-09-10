"""Training configuration.

Every number that affects a result lives in a YAML file and arrives here as a frozen
dataclass.  Nothing is hard-coded in the training loop, which is what makes a later GPU
run a configuration change rather than a code change (AD-11), and what makes a CPU run
and a GPU run comparable artifacts: the config is saved beside every checkpoint.

Defaults are the measured-hardware defaults from AD-11 — 128x128 patches at stride 96,
depth 4, base 16, GroupNorm, AdamW 3e-4 with cosine decay, 30 epochs, early stop on
validation **oil-class** Dice.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


@dataclass(frozen=True)
class ModelConfig:
    """Architecture. ``encoder`` is a factory key so a swap is a string change."""

    name: str = "unet"
    encoder: str = "simple"
    in_channels: int = 2
    out_channels: int = 1
    base_filters: int = 16
    depth: int = 4
    norm_groups: int = 8
    dropout: float = 0.0


@dataclass(frozen=True)
class DataConfig:
    #: Directory of GeoTIFF image/mask pairs.  Ignored when ``synthetic`` is set.
    root: str | None = None
    #: Use the deterministic offline generator instead of a downloaded dataset.
    synthetic: bool = False
    synthetic_images: int = 24
    synthetic_size: int = 256
    patch_size: int = 128
    stride: int = 96
    val_fraction: float = 0.15
    test_fraction: float = 0.15
    #: Keeping every all-sea tile spends the compute budget on the easiest examples.
    empty_tile_fraction: float = 0.35
    augment: bool = True
    max_images: int | None = None
    #: Band 1 of the published GeoTIFFs is *not documented*; the loader probes and fails
    #: loudly rather than assuming (AD-09).
    expected_band_order: tuple[str, ...] = ("VV", "VH")
    expected_dtype: str | None = None


@dataclass(frozen=True)
class OptimConfig:
    lr: float = 3e-4
    weight_decay: float = 1e-4
    batch_size: int = 8
    epochs: int = 30
    #: BCE-only warm-up before the Dice term joins in (ML_PIPELINE §5).
    warmup_epochs: int = 3
    early_stop_patience: int = 8
    scheduler: str = "cosine"
    num_workers: int = 2
    threads: int = 8
    #: A no-op on CPU; here so a GPU run needs no code change.
    amp: bool = False
    grad_clip: float = 1.0


@dataclass(frozen=True)
class LossConfig:
    bce_weight: float = 0.5
    dice_weight: float = 0.5
    #: ``pos_weight = clamp(negatives / positives, max=pos_weight_max)``
    pos_weight_max: float = 10.0
    dice_epsilon: float = 1.0


@dataclass(frozen=True)
class TrainConfig:
    name: str = "unet-cpu-baseline"
    seed: int = 42
    device: str = "auto"
    output_dir: str = "runs"
    threshold: float = 0.5
    model: ModelConfig = field(default_factory=ModelConfig)
    data: DataConfig = field(default_factory=DataConfig)
    optim: OptimConfig = field(default_factory=OptimConfig)
    loss: LossConfig = field(default_factory=LossConfig)

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TrainConfig:
        payload = dict(payload or {})
        sections = {
            "model": ModelConfig,
            "data": DataConfig,
            "optim": OptimConfig,
            "loss": LossConfig,
        }
        kwargs: dict[str, Any] = {}
        for key, factory in sections.items():
            section = payload.pop(key, None) or {}
            unknown = set(section) - set(factory.__dataclass_fields__)
            if unknown:
                raise ValueError(f"Unknown key(s) in '{key}': {sorted(unknown)}")
            if key == "data" and "expected_band_order" in section:
                section["expected_band_order"] = tuple(section["expected_band_order"])
            kwargs[key] = factory(**section)
        unknown_top = set(payload) - {
            name for name in cls.__dataclass_fields__ if name not in sections
        }
        if unknown_top:
            raise ValueError(f"Unknown top-level key(s): {sorted(unknown_top)}")
        kwargs.update(payload)
        return cls(**kwargs)

    @classmethod
    def from_yaml(cls, path: str | Path) -> TrainConfig:
        import yaml

        text = Path(path).read_text(encoding="utf-8")
        return cls.from_dict(yaml.safe_load(text) or {})

    def with_overrides(self, **overrides: Any) -> TrainConfig:
        return replace(self, **overrides)

    # ------------------------------------------------------------------ output
    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["data"]["expected_band_order"] = list(self.data.expected_band_order)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")
        return target

    # ------------------------------------------------------------------ device
    def resolve_device(self) -> str:
        """Resolve ``auto`` once, here, so no module ever calls ``.cuda()`` directly."""
        if self.device != "auto":
            return self.device
        try:
            import torch
        except ImportError:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"


def load_config(path: str | Path | None = None) -> TrainConfig:
    if path is None:
        return TrainConfig()
    return TrainConfig.from_yaml(path)


__all__ = [
    "DEFAULT_CONFIG_DIR",
    "DataConfig",
    "LossConfig",
    "ModelConfig",
    "OptimConfig",
    "TrainConfig",
    "load_config",
]
