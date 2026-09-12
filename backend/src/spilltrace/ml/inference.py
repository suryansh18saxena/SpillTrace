"""Segmentation models (FR-005, ML_PIPELINE §9).

Two implementations sit behind :class:`~spilltrace.core.ports.SegmentationModel`:

``AnalyticalDetector``
    A deterministic adaptive-threshold dark-region finder.  It needs no checkpoint, no
    torch and no GPU, so it is **always** available — and its output is labelled
    ``SYNTHETIC`` with ``model=analytical-detector`` so nobody can mistake it for a
    trained model's judgement.  This is what runs when no checkpoint is registered, and
    the pipeline keeps working rather than dead-ending.

``UNetModel``
    Loads a registered checkpoint.  If torch is absent, or no ``model_versions`` row
    points at an artifact, it raises ``ModelNotAvailableError`` instead of inventing a
    prediction.

``build_segmentation_model`` chooses between them and logs which one it chose, because
the difference is exactly the kind of thing that must not be silent.

**Shape contract.**  ``predict`` takes ``ndarray[N, C, H, W]`` and returns
``ndarray[N, H, W]`` — one probability map per tile, in the same order.  Given a single
un-tiled scene as ``[C, H, W]`` it returns ``[H, W]``.  Stitching tiles back into a scene
is :mod:`spilltrace.ml.stitch`'s job, not the model's.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage

from spilltrace.config import Settings, get_settings
from spilltrace.core.enums import DataProvenance
from spilltrace.core.errors import ModelNotAvailableError
from spilltrace.core.ports import SegmentationModel, SegmentationResult
from spilltrace.logging import get_logger

log = get_logger(__name__)

ANALYTICAL_NAME = "analytical-detector"
ANALYTICAL_VERSION = "1.0.0"
UNET_NAME = "spilltrace-unet"

#: Boxcar multi-look applied before any decision.  A GRDH pixel at ~4.4 looks has a
#: ~48% coefficient of variation, so a per-pixel dark/bright test is a test of speckle,
#: not of the surface.  A 5x5 boxcar is the cheapest honest way to buy back the looks.
DEFAULT_SMOOTHING_WINDOW = 5
#: Side of the moving window used to estimate the local sea background, in pixels.
#: Wide enough that a slick does not dominate its own background, narrow enough to track
#: the wind-driven brightness gradient across a swath.
DEFAULT_BACKGROUND_WINDOW = 31
#: How many robust standard deviations below the local background a pixel must sit
#: before it is called dark.  1.2 keeps thin trails while rejecting ordinary clutter.
DEFAULT_DARKNESS_SIGMAS = 1.2
#: Width of the logistic ramp, in the same units.  A step function here would make the
#: probability raster a mask, and a mask carries no confidence information.
DEFAULT_RAMP_SIGMAS = 0.6
#: Weights when both polarisations are present: damping is strongest in co-pol.
CHANNEL_WEIGHTS: tuple[float, float] = (0.7, 0.3)


@dataclass(frozen=True, slots=True)
class CheckpointRef:
    """Where a trained model lives and what it was trained to expect."""

    path: str
    name: str = UNET_NAME
    version: str = "0.0.0"
    input_channels: int = 2
    input_size: int = 128
    normalization: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)


class AnalyticalDetector:
    """Deterministic dark-region detector.

    The rule is the one an analyst would apply by eye: a pixel is oil-like when it is
    materially darker than the sea immediately around it, and not simply dark because
    the whole neighbourhood is.  Brightness above the local background — a ship, a rig —
    is actively suppressed rather than ignored, because bright targets sit next to real
    slicks often enough to matter.

    It is not a trained model and it is never presented as one.
    """

    name = ANALYTICAL_NAME
    version = ANALYTICAL_VERSION

    def __init__(
        self,
        *,
        smoothing_window: int = DEFAULT_SMOOTHING_WINDOW,
        background_window: int = DEFAULT_BACKGROUND_WINDOW,
        darkness_sigmas: float = DEFAULT_DARKNESS_SIGMAS,
        ramp_sigmas: float = DEFAULT_RAMP_SIGMAS,
    ) -> None:
        self.smoothing_window = max(1, int(smoothing_window))
        self.background_window = max(3, int(background_window))
        self.darkness_sigmas = float(darkness_sigmas)
        self.ramp_sigmas = max(1e-3, float(ramp_sigmas))

    def describe(self) -> dict[str, Any]:
        return {
            "model": self.name,
            "version": self.version,
            "framework": "numpy+scipy",
            "trained": False,
            "data_provenance": str(DataProvenance.SYNTHETIC),
            "parameters": {
                "smoothing_window_px": self.smoothing_window,
                "background_window_px": self.background_window,
                "darkness_sigmas": self.darkness_sigmas,
                "ramp_sigmas": self.ramp_sigmas,
                "channel_weights": list(CHANNEL_WEIGHTS),
            },
            "note": (
                "Deterministic adaptive-threshold detector. No training was performed "
                "and no performance metrics exist for it."
            ),
        }

    async def predict(self, tiles: Any) -> SegmentationResult:
        stack, squeeze = _as_tile_stack(tiles)
        probability = await asyncio.to_thread(self._infer, stack)
        return SegmentationResult(
            probability=probability[0] if squeeze else probability,
            model_name=self.name,
            model_version=self.version,
            input_channels=int(stack.shape[1]),
            notes=[
                "Produced by the deterministic analytical detector, not by a trained "
                "model. Treat the probabilities as a contrast statistic, not as a "
                "learned likelihood.",
            ],
            data_provenance=DataProvenance.SYNTHETIC,
        )

    def _infer(self, stack: np.ndarray) -> np.ndarray:
        signal = _combine_channels(stack)
        if self.smoothing_window > 1:
            signal = ndimage.uniform_filter(
                signal, size=(1, self.smoothing_window, self.smoothing_window), mode="nearest"
            )
        background = ndimage.uniform_filter(
            signal, size=(1, self.background_window, self.background_window), mode="nearest"
        )
        contrast = background - signal

        # The robust scale is computed over the whole batch, not per tile.  A per-tile
        # statistic would make a tile lying entirely inside a large slick treat the
        # slick as its own background — the detector would go blind exactly where the
        # signal is strongest — and would leave visible discontinuities at tile seams.
        median = float(np.median(signal))
        mad = float(np.median(np.abs(signal - median)))
        sigma = max(1.4826 * mad, 1e-3)

        z = (contrast - self.darkness_sigmas * sigma) / (self.ramp_sigmas * sigma)
        probability = 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))
        # Anything brighter than its surroundings is a target, not a slick.
        probability[contrast < 0] = 0.0
        return np.clip(probability, 0.0, 1.0).astype(np.float32)


class UNetModel:
    """A trained U-Net loaded from a registered checkpoint."""

    def __init__(self, checkpoint: CheckpointRef, *, device: str = "cpu", batch_size: int = 8):
        self._checkpoint = checkpoint
        self._device = device
        self._batch_size = max(1, batch_size)
        self.name = checkpoint.name
        self.version = checkpoint.version
        self._module: Any = None
        self._torch: Any = None
        self._metrics: dict[str, Any] = dict(checkpoint.params.get("metrics") or {})
        self._architecture: dict[str, Any] = {}
        self._parameters: int = 0
        self._training_args: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------ loading
    def _load(self) -> None:
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - exercised by the no-torch path
            raise ModelNotAvailableError(
                "PyTorch is not installed in this image, so a trained U-Net cannot be "
                "loaded. Rebuild with 'make build-ml', or leave "
                "SPILLTRACE_SEGMENTATION_MODEL=analytical."
            ) from exc

        path = Path(self._checkpoint.path)
        if not path.is_file():
            raise ModelNotAvailableError(
                f"The registered checkpoint is missing from {path}. No detection was "
                "run with a trained model."
            )

        payload = torch.load(str(path), map_location=self._device, weights_only=False)
        if not isinstance(payload, dict):
            raise ModelNotAvailableError(
                f"The checkpoint at {path} is not a dict payload; it cannot be loaded as a "
                "SPILLTRACE segmentation model."
            )

        state: Any = payload.get("state_dict")
        architecture: dict[str, Any]
        module: Any
        if state is not None:
            # The repository's own trainer (ml/src/train.py): plain U-Net + model_config.
            from spilltrace.ml.unet import UNetConfig, build_unet

            config = UNetConfig.from_dict(payload.get("model_config") or {})
            module = build_unet(config)
            architecture = {"architecture": "spilltrace-unet", **config.to_dict()}
        else:
            # segmentation_models_pytorch ``Unet`` saved as ``{"model": state_dict, ...}``
            # (the Colab-trained ResNet-34 checkpoint, AD-14).
            from spilltrace.ml.resnet_unet import (
                build_resnet_unet,
                config_from_state_dict,
                looks_like_smp_state_dict,
            )

            state = payload.get("model")
            if not isinstance(state, dict) or not looks_like_smp_state_dict(state):
                raise ModelNotAvailableError(
                    f"The checkpoint at {path} has neither a 'state_dict' (SPILLTRACE U-Net) "
                    "nor an smp-style 'model' state dict; it cannot be loaded."
                )
            try:
                resnet_config = config_from_state_dict(state)
            except KeyError as exc:
                raise ModelNotAvailableError(
                    f"The checkpoint at {path} is missing expected tensors: {exc}"
                ) from exc
            module = build_resnet_unet(resnet_config)
            architecture = resnet_config.to_dict()
            self._training_args = dict(payload.get("args") or {})
            validation = payload.get("val")
            if not self._metrics and isinstance(validation, dict) and validation:
                # Only the training script's own validation-split numbers exist in this
                # file.  They are recorded under an explicit 'validation' group so nobody
                # reads them as held-out test performance.
                self._metrics = {
                    "validation": {
                        key: float(value)
                        for key, value in validation.items()
                        if isinstance(value, int | float)
                    },
                    "split": "validation (training-time hold-out, not an independent test set)",
                }
            if isinstance(payload.get("epoch"), int):
                self._metrics.setdefault("epoch", int(payload["epoch"]))
        try:
            module.load_state_dict(state)
        except (RuntimeError, KeyError) as exc:
            raise ModelNotAvailableError(
                f"The checkpoint at {path} does not match the {architecture.get('architecture')} "
                f"architecture: {exc}"
            ) from exc
        self._architecture = architecture
        self._parameters = int(sum(p.numel() for p in module.parameters()))
        module.eval()
        module.to(self._device)

        self._torch = torch
        self._module = module
        if isinstance(payload.get("metrics"), dict) and payload["metrics"]:
            self._metrics = dict(payload["metrics"])
        log.info(
            "unet_checkpoint_loaded",
            checkpoint=str(path),
            model=self.name,
            version=self.version,
            device=self._device,
            metrics_recorded=bool(self._metrics),
        )

    # ------------------------------------------------------------------ inference
    def describe(self) -> dict[str, Any]:
        return {
            "model": self.name,
            "version": self.version,
            "framework": "pytorch",
            "trained": True,
            "device": self._device,
            "data_provenance": str(DataProvenance.REAL),
            "checkpoint": self._checkpoint.path,
            "input_channels": self._checkpoint.input_channels,
            "input_size": self._checkpoint.input_size,
            "normalization": dict(self._checkpoint.normalization),
            "architecture": dict(self._architecture),
            "parameter_count": self._parameters,
            # Empty unless a training run measured them.  Never populated by default.
            "metrics": dict(self._metrics),
            "notes": list(self._notes()),
        }

    def _notes(self) -> list[str]:
        notes: list[str] = []
        if not self._metrics:
            notes.append(
                "This model version has no measured evaluation metrics recorded, so its "
                "accuracy on this scene is unknown."
            )
        elif "validation" in self._metrics and "test" not in self._metrics:
            notes.append(
                "The recorded metrics are validation-split numbers from the training run, "
                "not an independent test set; treat them as an upper bound."
            )
        if self._architecture.get("architecture") == "segmentation_models_pytorch.Unet":
            notes.append(
                "Training-time input normalisation was not recorded in this checkpoint; "
                "inference applies the platform's per-scene percentile-clip "
                "standardisation (AD-12), so a distribution mismatch is possible."
            )
        notes.append(
            "Public SAR oil-spill benchmarks are overwhelmingly European waters; "
            "performance in other regions is documented to be lower (AD-13)."
        )
        return notes

    async def predict(self, tiles: Any) -> SegmentationResult:
        stack, squeeze = _as_tile_stack(tiles)
        probability = await asyncio.to_thread(self._infer, stack)
        notes = self._notes()
        return SegmentationResult(
            probability=probability[0] if squeeze else probability,
            model_name=self.name,
            model_version=self.version,
            input_channels=int(stack.shape[1]),
            notes=notes,
            data_provenance=DataProvenance.REAL,
        )

    def _infer(self, stack: np.ndarray) -> np.ndarray:
        torch = self._torch
        outputs: list[np.ndarray] = []
        with torch.inference_mode():
            for start in range(0, stack.shape[0], self._batch_size):
                batch = torch.from_numpy(
                    np.ascontiguousarray(stack[start : start + self._batch_size])
                ).to(self._device)
                logits = self._module(batch)
                outputs.append(torch.sigmoid(logits)[:, 0].cpu().numpy())
        return np.concatenate(outputs, axis=0).astype(np.float32)


# --------------------------------------------------------------------------- factory
def build_segmentation_model(
    settings: Settings | None = None,
    *,
    checkpoint: CheckpointRef | None = None,
    allow_fallback: bool = True,
) -> SegmentationModel:
    """Choose a model and say so.

    ``allow_fallback=False`` is for callers that must fail rather than quietly produce a
    synthetic result — the model registry endpoint, for instance.
    """
    settings = settings or get_settings()
    if settings.segmentation_model == "unet":
        if checkpoint is None:
            reason = "no model_versions row with an artifact is registered"
            if not allow_fallback:
                raise ModelNotAvailableError(
                    "SPILLTRACE_SEGMENTATION_MODEL=unet but " + reason + "."
                )
            log.warning(
                "segmentation_model_degraded",
                requested="unet",
                selected=ANALYTICAL_NAME,
                mode="SYNTHETIC",
                reason=reason,
                remedy="train a model and register it with ml/scripts/register_model.py",
            )
        else:
            try:
                model = UNetModel(checkpoint)
            except ModelNotAvailableError as exc:
                if not allow_fallback:
                    raise
                log.warning(
                    "segmentation_model_degraded",
                    requested="unet",
                    selected=ANALYTICAL_NAME,
                    mode="SYNTHETIC",
                    reason=exc.message,
                )
            else:
                log.info(
                    "segmentation_model_selected",
                    selected=model.name,
                    version=model.version,
                    mode="REAL",
                    reason="a trained checkpoint is registered and torch is installed",
                )
                return model
    else:
        log.info(
            "segmentation_model_selected",
            selected=ANALYTICAL_NAME,
            mode="SYNTHETIC",
            reason="SPILLTRACE_SEGMENTATION_MODEL=analytical",
        )
    return AnalyticalDetector()


# --------------------------------------------------------------------------- helpers
def _as_tile_stack(tiles: Any) -> tuple[np.ndarray, bool]:
    """Normalise input to ``(N, C, H, W)``; report whether N was synthetic."""
    array = np.asarray(tiles, dtype=np.float32)
    if array.ndim == 3:
        return array[np.newaxis, ...], True
    if array.ndim != 4:
        raise ValueError(f"Expected tiles shaped (N, C, H, W) or (C, H, W), got {array.shape}.")
    return array, False


def _combine_channels(stack: np.ndarray) -> np.ndarray:
    if stack.shape[1] == 1:
        return stack[:, 0]
    co_pol, cross_pol = CHANNEL_WEIGHTS
    return co_pol * stack[:, 0] + cross_pol * stack[:, 1]


__all__ = [
    "ANALYTICAL_NAME",
    "ANALYTICAL_VERSION",
    "DEFAULT_BACKGROUND_WINDOW",
    "DEFAULT_SMOOTHING_WINDOW",
    "UNET_NAME",
    "AnalyticalDetector",
    "CheckpointRef",
    "UNetModel",
    "build_segmentation_model",
]
