"""The compound loss (ML_PIPELINE §5).

```
L = bce_weight · BCEWithLogits(pos_weight = clamp(neg/pos, max)) + dice_weight · SoftDice
```

with a **BCE-only warm-up** for the first few epochs.  Dice is a ratio of overlaps, and
at initialisation there is no overlap to speak of: starting with it gives a gradient that
is both tiny and noisy.  BCE gives a clean per-pixel signal until the model predicts
something, and then Dice takes over the job BCE is bad at — caring about a class that
occupies 1% of the pixels.

``pos_weight`` is computed from the batch and clamped, because an all-sea batch has an
infinite negative/positive ratio and an unclamped weight makes the loss explode.

Requires PyTorch.  Nothing else in ``ml/`` does.
"""

from __future__ import annotations

from typing import Any

import torch
from torch import nn


def compute_pos_weight(targets: torch.Tensor, *, max_value: float = 10.0) -> torch.Tensor:
    """``clamp(negatives / positives, max=max_value)``, safe on an all-sea batch."""
    positives = float(targets.sum().item())
    total = float(targets.numel())
    if positives <= 0.0:
        return torch.tensor(max_value, dtype=targets.dtype, device=targets.device)
    ratio = (total - positives) / positives
    return torch.tensor(min(ratio, max_value), dtype=targets.dtype, device=targets.device)


def soft_dice_loss(
    logits: torch.Tensor, targets: torch.Tensor, *, epsilon: float = 1.0
) -> torch.Tensor:
    """1 - soft Dice over the batch.

    The Dice is computed over the whole batch rather than per sample and averaged: a
    per-sample Dice on an all-sea tile is 1.0 for predicting nothing, which rewards
    exactly the failure mode this loss exists to punish.
    """
    probabilities = torch.sigmoid(logits)
    intersection = (probabilities * targets).sum()
    denominator = probabilities.sum() + targets.sum()
    return 1.0 - (2.0 * intersection + epsilon) / (denominator + epsilon)


class CompoundLoss(nn.Module):
    """BCE + Dice with a warm-up, as specified in ML_PIPELINE §5."""

    def __init__(
        self,
        *,
        bce_weight: float = 0.5,
        dice_weight: float = 0.5,
        pos_weight_max: float = 10.0,
        dice_epsilon: float = 1.0,
        warmup_epochs: int = 3,
    ) -> None:
        super().__init__()
        self.bce_weight = float(bce_weight)
        self.dice_weight = float(dice_weight)
        self.pos_weight_max = float(pos_weight_max)
        self.dice_epsilon = float(dice_epsilon)
        self.warmup_epochs = int(warmup_epochs)

    def dice_active(self, epoch: int) -> bool:
        return epoch >= self.warmup_epochs

    def forward(
        self, logits: torch.Tensor, targets: torch.Tensor, *, epoch: int = 0
    ) -> torch.Tensor:
        targets = targets.to(dtype=logits.dtype)
        pos_weight = compute_pos_weight(targets, max_value=self.pos_weight_max)
        bce = nn.functional.binary_cross_entropy_with_logits(logits, targets, pos_weight=pos_weight)
        if not self.dice_active(epoch):
            return bce
        dice = soft_dice_loss(logits, targets, epsilon=self.dice_epsilon)
        return self.bce_weight * bce + self.dice_weight * dice

    def describe(self) -> dict[str, Any]:
        return {
            "loss": "0.5*BCEWithLogits(pos_weight) + 0.5*SoftDice",
            "bce_weight": self.bce_weight,
            "dice_weight": self.dice_weight,
            "pos_weight_max": self.pos_weight_max,
            "dice_epsilon": self.dice_epsilon,
            "warmup_epochs": self.warmup_epochs,
            "reference": "docs/ML_PIPELINE.md §5",
        }


__all__ = ["CompoundLoss", "compute_pos_weight", "soft_dice_loss"]
