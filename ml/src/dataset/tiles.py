"""Tiling image/mask pairs, and the empty-tile subsample.

Tiling reuses the backend's :mod:`spilltrace.ml.tiling` so training and inference cut
tiles the same way — a stride that differs between the two is a silent domain shift.

**Empty tiles are subsampled.**  In any SAR scene the overwhelming majority of tiles
contain no oil at all.  Keeping them all spends the entire CPU budget learning "this is
sea", which the model gets right almost immediately.  ML_PIPELINE §6 keeps them at
~30-40% of the training set; the exact fraction is configuration and is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from spilltrace.ml.tiling import tile_array

#: A tile with fewer than this many oil pixels counts as empty.
MIN_POSITIVE_PIXELS = 1


@dataclass(frozen=True)
class TileSet:
    images: np.ndarray  # (N, C, h, w) float32
    masks: np.ndarray  # (N, h, w) float32 in {0, 1}
    sources: tuple[str, ...]
    positive_flags: np.ndarray  # (N,) bool

    def __len__(self) -> int:
        return int(self.images.shape[0])

    @property
    def positive_fraction(self) -> float:
        return float(self.positive_flags.mean()) if len(self) else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tiles": len(self),
            "positive_tiles": int(self.positive_flags.sum()),
            "positive_fraction": round(self.positive_fraction, 6),
            "tile_shape": list(self.images.shape[1:]),
            "images": len(set(self.sources)),
        }


def tile_pair(
    image: np.ndarray,
    mask: np.ndarray,
    *,
    patch_size: int = 128,
    stride: int = 96,
) -> tuple[np.ndarray, np.ndarray]:
    """Cut one image/mask pair into aligned tiles."""
    image_tiles, _ = tile_array(image, tile_size=patch_size, stride=stride)
    mask_tiles, _ = tile_array(
        np.asarray(mask, dtype=np.float32)[np.newaxis, :, :],
        tile_size=patch_size,
        stride=stride,
    )
    return image_tiles, mask_tiles[:, 0]


def build_tileset(
    pairs: list[tuple[str, np.ndarray, np.ndarray]],
    *,
    patch_size: int = 128,
    stride: int = 96,
    empty_tile_fraction: float | None = 0.35,
    seed: int = 42,
) -> TileSet:
    """Tile every pair, then subsample the empty tiles to the configured fraction."""
    all_images: list[np.ndarray] = []
    all_masks: list[np.ndarray] = []
    sources: list[str] = []

    for name, image, mask in pairs:
        image_tiles, mask_tiles = tile_pair(image, mask, patch_size=patch_size, stride=stride)
        all_images.append(image_tiles)
        all_masks.append(mask_tiles)
        sources.extend([name] * image_tiles.shape[0])

    if not all_images:
        raise ValueError("No image/mask pairs were supplied.")

    images = np.concatenate(all_images, axis=0)
    masks = np.concatenate(all_masks, axis=0)
    positive = masks.reshape(masks.shape[0], -1).sum(axis=1) >= MIN_POSITIVE_PIXELS
    keep = np.arange(images.shape[0])

    if empty_tile_fraction is not None:
        keep = _subsample_empty(positive, fraction=empty_tile_fraction, seed=seed)

    return TileSet(
        images=images[keep].astype(np.float32),
        masks=masks[keep].astype(np.float32),
        sources=tuple(sources[i] for i in keep),
        positive_flags=positive[keep],
    )


def _subsample_empty(positive: np.ndarray, *, fraction: float, seed: int) -> np.ndarray:
    """Indices keeping every positive tile and enough empty ones to hit ``fraction``."""
    positive_index = np.flatnonzero(positive)
    empty_index = np.flatnonzero(~positive)
    if positive_index.size == 0 or empty_index.size == 0:
        return np.arange(positive.size)

    fraction = min(max(fraction, 0.0), 0.99)
    # positives / (positives + empties) = 1 - fraction  =>  empties = p * f / (1 - f)
    wanted = round(positive_index.size * fraction / max(1e-6, 1.0 - fraction))
    wanted = min(wanted, empty_index.size)
    rng = np.random.default_rng(seed)
    chosen = rng.choice(empty_index, size=wanted, replace=False) if wanted else np.array([], int)
    return np.sort(np.concatenate([positive_index, chosen.astype(int)]))


__all__ = ["MIN_POSITIVE_PIXELS", "TileSet", "build_tileset", "tile_pair"]
