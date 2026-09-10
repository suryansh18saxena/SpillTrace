"""Segmentation metrics for the **oil class** (ML_PIPELINE §7, AD-10).

Two conventions here are decisions, not details, and both push the reported number
*down* rather than up:

**Only the oil class is reported.**  A mean over classes that includes `sea` is dominated
by trivially easy pixels.  On the standard 5-class benchmark plain U-Net scores 64.97
mIoU but only 53.79 oil-class IoU; quoting the first would be quoting a different, much
easier problem.

**Aggregation is micro, by summing confusion matrices — never a mean of per-tile Dice.**
Most tiles in any SAR scene contain no oil at all, and a per-tile Dice of 1.0 for
correctly predicting "nothing here" would drown the tiles that actually matter.  Summing
the confusion matrix over the split makes every oil pixel count once.

Numpy only, so metrics can be computed and tested without PyTorch installed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

DEFAULT_THRESHOLDS: tuple[float, ...] = (
    0.10,
    0.20,
    0.30,
    0.40,
    0.50,
    0.60,
    0.70,
    0.80,
    0.90,
)


@dataclass(frozen=True)
class ConfusionMatrix:
    """Pixel counts for the positive (oil) class."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def __add__(self, other: ConfusionMatrix) -> ConfusionMatrix:
        return ConfusionMatrix(
            tp=self.tp + other.tp,
            fp=self.fp + other.fp,
            fn=self.fn + other.fn,
            tn=self.tn + other.tn,
        )

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def positives(self) -> int:
        return self.tp + self.fn

    def to_dict(self) -> dict[str, int]:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn}


def confusion(prediction: np.ndarray, target: np.ndarray) -> ConfusionMatrix:
    """Confusion counts between two boolean arrays."""
    predicted = np.asarray(prediction).astype(bool)
    truth = np.asarray(target).astype(bool)
    if predicted.shape != truth.shape:
        raise ValueError(f"Shape mismatch: prediction {predicted.shape} vs target {truth.shape}")
    tp = int(np.count_nonzero(predicted & truth))
    fp = int(np.count_nonzero(predicted & ~truth))
    fn = int(np.count_nonzero(~predicted & truth))
    tn = int(np.count_nonzero(~predicted & ~truth))
    return ConfusionMatrix(tp=tp, fp=fp, fn=fn, tn=tn)


def sum_confusions(matrices: Iterable[ConfusionMatrix]) -> ConfusionMatrix:
    total = ConfusionMatrix()
    for matrix in matrices:
        total = total + matrix
    return total


# --------------------------------------------------------------------------- scalars
def dice(matrix: ConfusionMatrix) -> float:
    """``2·TP / (2·TP + FP + FN)``; 1.0 when there is no oil and none was predicted."""
    denominator = 2 * matrix.tp + matrix.fp + matrix.fn
    if denominator == 0:
        return 1.0
    return 2.0 * matrix.tp / denominator


def iou(matrix: ConfusionMatrix) -> float:
    denominator = matrix.tp + matrix.fp + matrix.fn
    if denominator == 0:
        return 1.0
    return matrix.tp / denominator


def precision(matrix: ConfusionMatrix) -> float:
    """Predicting nothing is correct when there is nothing, and wrong when there is."""
    denominator = matrix.tp + matrix.fp
    if denominator == 0:
        return 1.0 if matrix.fn == 0 else 0.0
    return matrix.tp / denominator


def recall(matrix: ConfusionMatrix) -> float:
    denominator = matrix.tp + matrix.fn
    if denominator == 0:
        return 1.0
    return matrix.tp / denominator


def pixel_accuracy(matrix: ConfusionMatrix) -> float:
    """Reported, never headlined: it is ~99% for a model that predicts nothing."""
    if matrix.total == 0:
        return 1.0
    return (matrix.tp + matrix.tn) / matrix.total


def summarise(matrix: ConfusionMatrix) -> dict[str, Any]:
    return {
        "dice": round(dice(matrix), 6),
        "iou": round(iou(matrix), 6),
        "precision": round(precision(matrix), 6),
        "recall": round(recall(matrix), 6),
        "pixel_accuracy": round(pixel_accuracy(matrix), 6),
        "confusion": matrix.to_dict(),
        "oil_pixel_fraction": round(matrix.positives / matrix.total, 8) if matrix.total else 0.0,
        "class": "oil",
        "aggregation": "micro (summed confusion matrix over the split)",
    }


def oil_class_metrics(
    probability: np.ndarray, target: np.ndarray, *, threshold: float = 0.5
) -> dict[str, Any]:
    matrix = confusion(np.asarray(probability) >= threshold, target)
    return {**summarise(matrix), "threshold": threshold}


# --------------------------------------------------------------------------- sweeps
def threshold_sweep(
    probability: np.ndarray,
    target: np.ndarray,
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
) -> list[dict[str, Any]]:
    values = np.asarray(probability)
    truth = np.asarray(target).astype(bool)
    return [
        {**summarise(confusion(values >= threshold, truth)), "threshold": float(threshold)}
        for threshold in thresholds
    ]


def best_threshold(sweep: Sequence[dict[str, Any]], *, key: str = "dice") -> dict[str, Any]:
    """The operating point to report.  Chosen on validation, never on test."""
    if not sweep:
        raise ValueError("An empty sweep has no operating point.")
    return max(sweep, key=lambda entry: (entry[key], -entry["threshold"]))


__all__ = [
    "DEFAULT_THRESHOLDS",
    "ConfusionMatrix",
    "best_threshold",
    "confusion",
    "dice",
    "iou",
    "oil_class_metrics",
    "pixel_accuracy",
    "precision",
    "recall",
    "sum_confusions",
    "summarise",
    "threshold_sweep",
]
