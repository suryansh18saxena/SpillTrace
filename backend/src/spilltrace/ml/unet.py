"""The U-Net architecture, defined once and shared by training and inference.

**This module imports PyTorch at the top level and must therefore only ever be imported
lazily, behind a check that torch is installed.**  The default container image is built
without torch (AD-11: this host is CPU-only and the model is optional), and importing
this module unconditionally would break every deployment that never uses it.

One definition serves both sides on purpose: an inference-time architecture that has
drifted from the training-time one loads a state dict with subtly wrong shapes, or —
worse — with right shapes and wrong semantics.

Defaults follow AD-11: depth 4, base 16 (≈1.9 M parameters), **GroupNorm** rather than
BatchNorm because CPU-sized batches make BatchNorm's running statistics unreliable, and
SiLU activations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import torch
from torch import nn

DEFAULT_IN_CHANNELS = 2
DEFAULT_BASE_FILTERS = 16
DEFAULT_DEPTH = 4
DEFAULT_NORM_GROUPS = 8


@dataclass(frozen=True, slots=True)
class UNetConfig:
    """Everything about the architecture, so a checkpoint can rebuild itself."""

    in_channels: int = DEFAULT_IN_CHANNELS
    out_channels: int = 1
    base_filters: int = DEFAULT_BASE_FILTERS
    depth: int = DEFAULT_DEPTH
    norm_groups: int = DEFAULT_NORM_GROUPS
    dropout: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "in_channels": self.in_channels,
            "out_channels": self.out_channels,
            "base_filters": self.base_filters,
            "depth": self.depth,
            "norm_groups": self.norm_groups,
            "dropout": self.dropout,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> UNetConfig:
        payload = payload or {}
        return cls(
            in_channels=int(payload.get("in_channels", DEFAULT_IN_CHANNELS)),
            out_channels=int(payload.get("out_channels", 1)),
            base_filters=int(payload.get("base_filters", DEFAULT_BASE_FILTERS)),
            depth=int(payload.get("depth", DEFAULT_DEPTH)),
            norm_groups=int(payload.get("norm_groups", DEFAULT_NORM_GROUPS)),
            dropout=float(payload.get("dropout", 0.0)),
        )


def _groups(channels: int, requested: int) -> int:
    """GroupNorm needs a divisor of the channel count; fall back to the largest one."""
    for candidate in range(min(requested, channels), 0, -1):
        if channels % candidate == 0:
            return candidate
    return 1


class ConvBlock(nn.Module):
    """Two 3×3 convolutions, each followed by GroupNorm and SiLU."""

    def __init__(self, in_channels: int, out_channels: int, groups: int, dropout: float) -> None:
        super().__init__()
        layers: list[nn.Module] = [
            nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.GroupNorm(_groups(out_channels, groups), out_channels),
            nn.SiLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.GroupNorm(_groups(out_channels, groups), out_channels),
            nn.SiLU(inplace=True),
        ]
        if dropout > 0:
            layers.append(nn.Dropout2d(dropout))
        self.block = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return cast("torch.Tensor", self.block(x))


class UNet(nn.Module):
    """A plain U-Net with a single logit output channel (binary oil / not-oil)."""

    def __init__(self, config: UNetConfig | None = None) -> None:
        super().__init__()
        self.config = config or UNetConfig()
        widths = [self.config.base_filters * (2**level) for level in range(self.config.depth)]

        self.encoders = nn.ModuleList()
        channels = self.config.in_channels
        for width in widths:
            self.encoders.append(
                ConvBlock(channels, width, self.config.norm_groups, self.config.dropout)
            )
            channels = width
        self.pool = nn.MaxPool2d(2)
        self.bottleneck = ConvBlock(
            channels, channels * 2, self.config.norm_groups, self.config.dropout
        )

        self.upsamples = nn.ModuleList()
        self.decoders = nn.ModuleList()
        channels *= 2
        for width in reversed(widths):
            self.upsamples.append(nn.ConvTranspose2d(channels, width, kernel_size=2, stride=2))
            self.decoders.append(
                ConvBlock(width * 2, width, self.config.norm_groups, self.config.dropout)
            )
            channels = width
        self.head = nn.Conv2d(channels, self.config.out_channels, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        skips: list[torch.Tensor] = []
        for encoder in self.encoders:
            x = encoder(x)
            skips.append(x)
            x = self.pool(x)
        x = self.bottleneck(x)
        for upsample, decoder, skip in zip(
            self.upsamples, self.decoders, reversed(skips), strict=True
        ):
            x = upsample(x)
            if x.shape[-2:] != skip.shape[-2:]:
                x = nn.functional.interpolate(x, size=skip.shape[-2:], mode="nearest")
            x = decoder(torch.cat([skip, x], dim=1))
        return cast("torch.Tensor", self.head(x))


def build_unet(config: UNetConfig | dict[str, Any] | None = None) -> UNet:
    if isinstance(config, dict):
        config = UNetConfig.from_dict(config)
    return UNet(config)


def parameter_count(module: nn.Module) -> int:
    return int(sum(p.numel() for p in module.parameters()))


__all__ = [
    "DEFAULT_BASE_FILTERS",
    "DEFAULT_DEPTH",
    "DEFAULT_IN_CHANNELS",
    "ConvBlock",
    "UNet",
    "UNetConfig",
    "build_unet",
    "parameter_count",
]
