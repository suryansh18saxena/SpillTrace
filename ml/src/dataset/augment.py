"""Augmentation (ML_PIPELINE §3, AD-12).

Flips, rot90 and an optional Gamma speckle injection — and **nothing photometric**.

Brightness or contrast jitter is the standard first reach in image augmentation and it is
exactly wrong here: backscatter magnitude *is* the measurement.  An oil slick is defined
by being ~10 dB below the surrounding sea, so jittering brightness teaches the model to
ignore the one quantity that separates oil from water.

Speckle injection is different: it is a re-draw from the physical noise model (Gamma with
the equivalent number of looks), so it perturbs the noise without moving the signal.
Everything is seeded and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

#: GRDH multi-look factor; see ml/src/dataset/synthetic.py.
DEFAULT_LOOKS = 4.4


@dataclass(frozen=True)
class AugmentConfig:
    horizontal_flip: bool = True
    vertical_flip: bool = True
    rot90: bool = True
    speckle_probability: float = 0.25
    speckle_looks: float = DEFAULT_LOOKS

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizontal_flip": self.horizontal_flip,
            "vertical_flip": self.vertical_flip,
            "rot90": self.rot90,
            "speckle_probability": self.speckle_probability,
            "speckle_looks": self.speckle_looks,
            "photometric_jitter": False,
            "reason_no_photometric": (
                "Backscatter magnitude is the physical signal being measured, not a "
                "nuisance variable (AD-12)."
            ),
        }


def augment(
    image: np.ndarray,
    mask: np.ndarray,
    *,
    rng: np.random.Generator,
    config: AugmentConfig | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply the configured augmentations to a ``(C, H, W)`` / ``(H, W)`` pair."""
    config = config or AugmentConfig()
    out_image = np.asarray(image, dtype=np.float32)
    out_mask = np.asarray(mask)

    if config.horizontal_flip and rng.random() < 0.5:
        out_image = out_image[:, :, ::-1]
        out_mask = out_mask[:, ::-1]
    if config.vertical_flip and rng.random() < 0.5:
        out_image = out_image[:, ::-1, :]
        out_mask = out_mask[::-1, :]
    if config.rot90:
        turns = int(rng.integers(0, 4))
        if turns:
            out_image = np.rot90(out_image, turns, axes=(1, 2))
            out_mask = np.rot90(out_mask, turns, axes=(0, 1))
    if config.speckle_probability > 0 and rng.random() < config.speckle_probability:
        out_image = inject_speckle(out_image, rng=rng, looks=config.speckle_looks)

    return np.ascontiguousarray(out_image), np.ascontiguousarray(out_mask)


def inject_speckle(
    image: np.ndarray, *, rng: np.random.Generator, looks: float = DEFAULT_LOOKS
) -> np.ndarray:
    """Re-draw multiplicative speckle in the linear domain, on dB-valued input.

    The image is in dB, so multiplicative speckle in power is *additive* in dB:
    ``dB' = dB + 10·log10(g)`` with ``g ~ Gamma(L, 1/L)``, mean 1.  Doing it any other
    way (adding Gaussian noise to dB, say) would not be the physical noise model.
    """
    gain = rng.gamma(looks, 1.0 / looks, size=image.shape)
    return (np.asarray(image, dtype=np.float32) + 10.0 * np.log10(gain)).astype(np.float32)


__all__ = ["DEFAULT_LOOKS", "AugmentConfig", "augment", "inject_speckle"]
