"""A ResNet-34 encoder U-Net that is state-dict compatible with ``segmentation_models_pytorch``.

The production checkpoint (``ml/runs/colab-resnet34-run3``) was trained outside this
repository with ``smp.Unet(encoder_name="resnet34", encoder_weights=None, in_channels=2,
classes=1)``.  Rather than adding ``segmentation_models_pytorch`` (and, transitively,
``timm`` and ``huggingface_hub``) to the runtime image, the architecture is reproduced
here in plain PyTorch with **identical parameter names and identical forward semantics**,
so ``load_state_dict(state, strict=True)`` succeeds and the outputs match smp to floating
point precision (verified against smp on 2026-09-12; see ``docs/DECISIONS.md`` AD-14).

**This module imports PyTorch at the top level and must only ever be imported lazily**,
for the same reason as :mod:`spilltrace.ml.unet` — the default image ships without torch.

Layout (all names are load-bearing):

```
encoder.conv1 / bn1 / relu / maxpool / layer1..4      torchvision ResNet-34, fc & avgpool removed
decoder.center                                        Identity
decoder.blocks.{0..4}.conv1.{0,1,2}                   Conv2d(bias=False) · BatchNorm2d · ReLU
decoder.blocks.{0..4}.attention1.attention            Identity  (attention_type=None)
decoder.blocks.{0..4}.conv2.{0,1,2}                   Conv2d(bias=False) · BatchNorm2d · ReLU
decoder.blocks.{0..4}.attention2.attention            Identity
segmentation_head.0                                   Conv2d(16, classes, 3, padding=1)
segmentation_head.1                                   Identity  (upsampling=1)
segmentation_head.2.activation                        Identity  (raw logits)
```
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import torch
from torch import nn
from torch.nn import functional

RESNET34_LAYERS: tuple[int, int, int, int] = (3, 4, 6, 3)
RESNET34_STAGE_CHANNELS: tuple[int, int, int, int, int] = (64, 64, 128, 256, 512)
DEFAULT_DECODER_CHANNELS: tuple[int, int, int, int, int] = (256, 128, 64, 32, 16)

#: smp calls the encoder ``resnet34``; we keep the same spelling so a manifest written by
#: either side names the same thing.
ENCODER_NAME = "resnet34"


@dataclass(frozen=True, slots=True)
class ResNetUNetConfig:
    in_channels: int = 2
    classes: int = 1
    decoder_channels: tuple[int, int, int, int, int] = DEFAULT_DECODER_CHANNELS

    def to_dict(self) -> dict[str, Any]:
        return {
            "architecture": "segmentation_models_pytorch.Unet",
            "encoder": ENCODER_NAME,
            "in_channels": self.in_channels,
            "out_channels": self.classes,
            "decoder_channels": list(self.decoder_channels),
        }


# ------------------------------------------------------------------ encoder (torchvision)
def _conv3x3(in_planes: int, out_planes: int, stride: int = 1) -> nn.Conv2d:
    return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride, padding=1, bias=False)


class BasicBlock(nn.Module):
    """torchvision's ``BasicBlock``; attribute names must match (conv1, bn1, conv2, bn2, …)."""

    expansion = 1

    def __init__(
        self,
        inplanes: int,
        planes: int,
        stride: int = 1,
        downsample: nn.Module | None = None,
    ) -> None:
        super().__init__()
        self.conv1 = _conv3x3(inplanes, planes, stride)
        self.bn1 = nn.BatchNorm2d(planes)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = _conv3x3(planes, planes)
        self.bn2 = nn.BatchNorm2d(planes)
        self.downsample = downsample

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        identity = x
        out = self.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        if self.downsample is not None:
            identity = self.downsample(x)
        return cast("torch.Tensor", self.relu(out + identity))


class ResNet34Encoder(nn.Module):
    """torchvision ResNet-34 without ``fc``/``avgpool``, returning smp's six feature maps."""

    def __init__(self, in_channels: int) -> None:
        super().__init__()
        self.inplanes = 64
        self.conv1 = nn.Conv2d(in_channels, 64, kernel_size=7, stride=2, padding=3, bias=False)
        self.bn1 = nn.BatchNorm2d(64)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
        self.layer1 = self._make_layer(64, RESNET34_LAYERS[0])
        self.layer2 = self._make_layer(128, RESNET34_LAYERS[1], stride=2)
        self.layer3 = self._make_layer(256, RESNET34_LAYERS[2], stride=2)
        self.layer4 = self._make_layer(512, RESNET34_LAYERS[3], stride=2)

    def _make_layer(self, planes: int, blocks: int, stride: int = 1) -> nn.Sequential:
        downsample: nn.Module | None = None
        if stride != 1 or self.inplanes != planes:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes, kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes),
            )
        layers = [BasicBlock(self.inplanes, planes, stride, downsample)]
        self.inplanes = planes
        layers.extend(BasicBlock(planes, planes) for _ in range(1, blocks))
        return nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> list[torch.Tensor]:
        features = [x]
        x = self.relu(self.bn1(self.conv1(x)))
        features.append(x)
        x = self.layer1(self.maxpool(x))
        features.append(x)
        x = self.layer2(x)
        features.append(x)
        x = self.layer3(x)
        features.append(x)
        x = self.layer4(x)
        features.append(x)
        return features


# ------------------------------------------------------------------ decoder (smp UnetDecoder)
class Conv2dReLU(nn.Sequential):
    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__(
            nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )


class Attention(nn.Module):
    """smp's ``Attention(None)`` wrapper: a named Identity so the key path exists."""

    def __init__(self) -> None:
        super().__init__()
        self.attention = nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return cast("torch.Tensor", self.attention(x))


class DecoderBlock(nn.Module):
    def __init__(self, in_channels: int, skip_channels: int, out_channels: int) -> None:
        super().__init__()
        self.conv1 = Conv2dReLU(in_channels + skip_channels, out_channels)
        self.attention1 = Attention()
        self.conv2 = Conv2dReLU(out_channels, out_channels)
        self.attention2 = Attention()

    def forward(self, x: torch.Tensor, skip: torch.Tensor | None = None) -> torch.Tensor:
        x = functional.interpolate(x, scale_factor=2.0, mode="nearest")
        if skip is not None:
            if x.shape[-2:] != skip.shape[-2:]:
                x = functional.interpolate(x, size=skip.shape[-2:], mode="nearest")
            x = torch.cat([x, skip], dim=1)
        x = self.attention1(self.conv1(x))
        return cast("torch.Tensor", self.attention2(self.conv2(x)))


class UnetDecoder(nn.Module):
    def __init__(
        self,
        encoder_channels: tuple[int, ...],
        decoder_channels: tuple[int, ...],
    ) -> None:
        super().__init__()
        # smp: drop the identity feature, reverse so the deepest map comes first.
        channels = list(encoder_channels[1:])[::-1]
        head_channels = channels[0]
        in_channels = [head_channels, *decoder_channels[:-1]]
        skip_channels = [*channels[1:], 0]
        self.center = nn.Identity()
        self.blocks = nn.ModuleList(
            DecoderBlock(inp, skip, out)
            for inp, skip, out in zip(in_channels, skip_channels, decoder_channels, strict=True)
        )

    def forward(self, features: list[torch.Tensor]) -> torch.Tensor:
        maps = features[1:][::-1]
        head, skips = maps[0], maps[1:]
        x = self.center(head)
        for index, block in enumerate(self.blocks):
            skip = skips[index] if index < len(skips) else None
            x = block(x, skip)
        return x


class Activation(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.activation = nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return cast("torch.Tensor", self.activation(x))


class ResNetUNet(nn.Module):
    """``smp.Unet("resnet34", encoder_weights=None, in_channels, classes)`` in plain torch."""

    def __init__(self, config: ResNetUNetConfig | None = None) -> None:
        super().__init__()
        self.config = config or ResNetUNetConfig()
        self.encoder = ResNet34Encoder(self.config.in_channels)
        self.decoder = UnetDecoder(
            (self.config.in_channels, *RESNET34_STAGE_CHANNELS), self.config.decoder_channels
        )
        self.segmentation_head = nn.Sequential(
            nn.Conv2d(
                self.config.decoder_channels[-1], self.config.classes, kernel_size=3, padding=1
            ),
            nn.Identity(),
            Activation(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        height, width = x.shape[-2:]
        if height % 32 or width % 32:
            raise ValueError(
                "Input spatial size must be divisible by 32 for a ResNet-34 U-Net, "
                f"got {(height, width)}."
            )
        features = self.encoder(x)
        decoded = self.decoder(features)
        return cast("torch.Tensor", self.segmentation_head(decoded))


SMP_KEY_PREFIXES: tuple[str, ...] = ("encoder.", "decoder.", "segmentation_head.")


def looks_like_smp_state_dict(state: Any) -> bool:
    """True when every key belongs to an smp ``Unet`` (encoder / decoder / head)."""
    if not isinstance(state, dict) or not state:
        return False
    return all(isinstance(key, str) and key.startswith(SMP_KEY_PREFIXES) for key in state)


def config_from_state_dict(state: dict[str, Any]) -> ResNetUNetConfig:
    """Infer channels and classes from the tensors themselves, never from a guess."""
    conv1 = state.get("encoder.conv1.weight")
    head = state.get("segmentation_head.0.weight")
    if conv1 is None or head is None:
        raise KeyError("state dict lacks encoder.conv1.weight / segmentation_head.0.weight")
    decoder_channels: list[int] = []
    for index in range(5):
        weight = state.get(f"decoder.blocks.{index}.conv1.0.weight")
        if weight is None:
            raise KeyError(f"state dict lacks decoder.blocks.{index}.conv1.0.weight")
        decoder_channels.append(int(weight.shape[0]))
    return ResNetUNetConfig(
        in_channels=int(conv1.shape[1]),
        classes=int(head.shape[0]),
        decoder_channels=cast("tuple[int, int, int, int, int]", tuple(decoder_channels)),
    )


def build_resnet_unet(config: ResNetUNetConfig | dict[str, Any] | None = None) -> ResNetUNet:
    if isinstance(config, dict):
        config = ResNetUNetConfig(
            in_channels=int(config.get("in_channels") or 2),
            classes=int(config.get("out_channels") or config.get("classes") or 1),
            decoder_channels=cast(
                "tuple[int, int, int, int, int]",
                tuple(int(v) for v in config.get("decoder_channels", DEFAULT_DECODER_CHANNELS)),
            ),
        )
    return ResNetUNet(config)


__all__ = [
    "DEFAULT_DECODER_CHANNELS",
    "ENCODER_NAME",
    "ResNetUNet",
    "ResNetUNetConfig",
    "build_resnet_unet",
    "config_from_state_dict",
    "looks_like_smp_state_dict",
]
