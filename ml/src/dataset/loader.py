"""Loading image/mask pairs and normalising them exactly as inference will.

The normalisation is imported from ``spilltrace.ml.preprocess`` rather than
reimplemented.  If training standardised differently from inference — a different
percentile, statistics over the whole set instead of per image — the model would see a
different distribution in the field than it was fitted on, and the accuracy lost would
never show up in a validation score.

Two layouts are recognised, and both are the ones the published dataset actually uses:

* ``<stem>.tif`` beside ``<stem>_segmentation.tif`` (the Part III test set), and
* ``images/<stem>.tif`` beside ``masks/<stem>.tif``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from spilltrace.ml.preprocess import DEFAULT_CLIP_PERCENTILES, clip_and_standardise

IMAGE_SUFFIXES = (".tif", ".tiff")
MASK_MARKER = "_segmentation"


@dataclass(frozen=True)
class ImagePair:
    name: str
    image: np.ndarray  # (C, H, W) float32, standardised
    mask: np.ndarray  # (H, W) float32 in {0, 1}
    statistics: tuple[dict[str, Any], ...] = ()

    @property
    def oil_fraction(self) -> float:
        return float(self.mask.mean())


def discover_pairs(root: str | Path) -> list[tuple[str, Path, Path]]:
    """Find ``(name, image_path, mask_path)`` triples under ``root``."""
    base = Path(root)
    if not base.is_dir():
        raise FileNotFoundError(f"Dataset directory does not exist: {base}")

    pairs: list[tuple[str, Path, Path]] = []

    images_dir, masks_dir = base / "images", base / "masks"
    if images_dir.is_dir() and masks_dir.is_dir():
        for image_path in sorted(images_dir.iterdir()):
            if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            mask_path = masks_dir / image_path.name
            if mask_path.is_file():
                pairs.append((image_path.stem, image_path, mask_path))
        return pairs

    for image_path in sorted(base.iterdir()):
        if image_path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if MASK_MARKER in image_path.stem:
            continue
        mask_path = image_path.with_name(f"{image_path.stem}{MASK_MARKER}{image_path.suffix}")
        if mask_path.is_file():
            pairs.append((image_path.stem, image_path, mask_path))
    return pairs


def read_db_image(path: str | Path) -> np.ndarray:
    import rasterio

    with rasterio.open(str(path)) as dataset:
        return dataset.read().astype(np.float32)


def read_mask(path: str | Path) -> np.ndarray:
    import rasterio

    with rasterio.open(str(path)) as dataset:
        return (dataset.read(1) > 0).astype(np.float32)


def normalise_db_image(
    image_db: np.ndarray,
    *,
    percentiles: tuple[float, float] = DEFAULT_CLIP_PERCENTILES,
) -> tuple[np.ndarray, tuple[dict[str, Any], ...]]:
    """Per-image percentile clip and standardise, band by band (AD-12).

    The published images are already σ0 in dB, so the dB conversion is skipped; the
    clip-and-standardise half is the same code inference runs.
    """
    stack = np.asarray(image_db, dtype=np.float32)
    if stack.ndim == 2:
        stack = stack[np.newaxis, :, :]
    channels: list[np.ndarray] = []
    statistics: list[dict[str, Any]] = []
    for index, band in enumerate(stack):
        valid = np.isfinite(band)
        standardised, stats = clip_and_standardise(
            band, valid, polarization=f"band{index + 1}", percentiles=percentiles
        )
        channels.append(standardised)
        statistics.append(stats.to_dict())
    return np.stack(channels).astype(np.float32), tuple(statistics)


def load_pair(
    name: str,
    image_path: str | Path,
    mask_path: str | Path,
    *,
    percentiles: tuple[float, float] = DEFAULT_CLIP_PERCENTILES,
) -> ImagePair:
    image, statistics = normalise_db_image(read_db_image(image_path), percentiles=percentiles)
    mask = read_mask(mask_path)
    if mask.shape != image.shape[1:]:
        raise ValueError(
            f"{name}: mask {mask.shape} does not match image {image.shape[1:]}. The pair "
            "is mismatched; training on it would learn a shifted target."
        )
    return ImagePair(name=name, image=image, mask=mask, statistics=statistics)


def load_synthetic_pairs(
    count: int,
    *,
    size: int = 256,
    seed: int = 42,
    percentiles: tuple[float, float] = DEFAULT_CLIP_PERCENTILES,
) -> list[ImagePair]:
    """Offline pairs from the deterministic generator, normalised identically."""
    from dataset.synthetic import generate_dataset

    pairs: list[ImagePair] = []
    for sample in generate_dataset(count, size=size, seed=seed):
        image, statistics = normalise_db_image(sample.image, percentiles=percentiles)
        pairs.append(
            ImagePair(
                name=f"synthetic-{sample.index:04d}-{sample.kind}",
                image=image,
                mask=sample.mask.astype(np.float32),
                statistics=statistics,
            )
        )
    return pairs


__all__ = [
    "IMAGE_SUFFIXES",
    "MASK_MARKER",
    "ImagePair",
    "discover_pairs",
    "load_pair",
    "load_synthetic_pairs",
    "normalise_db_image",
    "read_db_image",
    "read_mask",
]
