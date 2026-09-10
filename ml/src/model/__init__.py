"""Model factory.

``encoder`` is a string in the config so a later architecture swap is a configuration
change, not a code change (AD-11).  Only ``simple`` is implemented; the other keys raise
with an explicit message rather than silently falling back to the baseline and reporting
its numbers under another name.
"""

from __future__ import annotations

from typing import Any

SUPPORTED_ENCODERS = ("simple",)
PLANNED_ENCODERS = ("resnet34", "segformer")


class EncoderNotAvailableError(NotImplementedError):
    """A configured encoder exists in the config schema but not in this image."""


def build_model(config: Any) -> Any:
    """Build the model described by a :class:`~config.ModelConfig`."""
    from spilltrace.ml.unet import UNetConfig, build_unet

    name = getattr(config, "name", "unet")
    encoder = getattr(config, "encoder", "simple")
    if name != "unet":
        raise EncoderNotAvailableError(f"Model '{name}' is not implemented. Available: 'unet'.")
    if encoder not in SUPPORTED_ENCODERS:
        raise EncoderNotAvailableError(
            f"Encoder '{encoder}' is planned but not implemented "
            f"({', '.join(PLANNED_ENCODERS)} need pretrained weights this image does "
            f"not ship). Available: {', '.join(SUPPORTED_ENCODERS)}."
        )
    return build_unet(
        UNetConfig(
            in_channels=int(config.in_channels),
            out_channels=int(config.out_channels),
            base_filters=int(config.base_filters),
            depth=int(config.depth),
            norm_groups=int(config.norm_groups),
            dropout=float(config.dropout),
        )
    )


def parameter_count(module: Any) -> int:
    return int(sum(p.numel() for p in module.parameters()))


__all__ = [
    "PLANNED_ENCODERS",
    "SUPPORTED_ENCODERS",
    "EncoderNotAvailableError",
    "build_model",
    "parameter_count",
]
