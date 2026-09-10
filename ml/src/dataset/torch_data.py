"""PyTorch wiring for a :class:`~dataset.tiles.TileSet`.

Kept in its own module so that everything else — generation, loading, splitting, tiling,
augmentation, metrics — imports and tests without PyTorch installed.
"""

from __future__ import annotations

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from dataset.augment import AugmentConfig, augment
from dataset.tiles import TileSet


class TileDataset(Dataset[tuple[torch.Tensor, torch.Tensor]]):
    """Tiles as tensors, with augmentation applied on the train split only.

    The augmentation RNG is seeded from ``(seed, epoch, index)`` so a run is reproducible
    while still drawing different transforms each epoch.
    """

    def __init__(
        self,
        tiles: TileSet,
        *,
        augment_config: AugmentConfig | None = None,
        seed: int = 42,
    ) -> None:
        self.tiles = tiles
        self.augment_config = augment_config
        self.seed = seed
        self.epoch = 0

    def set_epoch(self, epoch: int) -> None:
        self.epoch = int(epoch)

    def __len__(self) -> int:
        return len(self.tiles)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        image = self.tiles.images[index]
        mask = self.tiles.masks[index]
        if self.augment_config is not None:
            rng = np.random.default_rng(
                (self.seed * 1_000_003 + self.epoch * 9_176 + index) % (2**32)
            )
            image, mask = augment(image, mask, rng=rng, config=self.augment_config)
        return (
            torch.from_numpy(np.ascontiguousarray(image, dtype=np.float32)),
            torch.from_numpy(np.ascontiguousarray(mask, dtype=np.float32))[None, :, :],
        )


def build_loader(
    dataset: TileDataset,
    *,
    batch_size: int = 8,
    shuffle: bool = False,
    num_workers: int = 0,
    seed: int = 42,
) -> DataLoader[tuple[torch.Tensor, torch.Tensor]]:
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        generator=generator if shuffle else None,
        drop_last=False,
        persistent_workers=num_workers > 0,
    )


__all__ = ["TileDataset", "build_loader"]
