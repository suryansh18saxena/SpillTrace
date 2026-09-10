"""Deterministic synthetic SAR dataset (ML_PIPELINE §1, P10-007).

The published dataset is 96.5 GB.  Nothing in CI, and nothing on a laptop doing a first
run, should need it — so this module generates image/mask pairs with the same *shape* as
the real ones (2-channel dB GeoTIFF plus a single-band 0/1 mask) and enough of the same
character to exercise the pipeline: Gamma speckle, a range brightness gradient, elongated
damped ribbons, and — importantly — **look-alike** dark patches with no oil in the mask,
so a model cannot pass by learning "dark means oil".

It is not a substitute for real data and metrics measured on it are metrics on synthetic
data.  Everything it produces says so, in the sample metadata and in the run manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

SampleKind = Literal["oil", "lookalike", "clean"]

#: Sea σ0 at C-band VV in moderate wind; oil damps roughly 10 dB below it.
SEA_SIGMA0_VV = 0.05
OIL_SIGMA0_VV = 0.005
#: A low-wind patch is dark too — but it is not oil, and its mask is empty.
LOOKALIKE_SIGMA0_VV = 0.012
VH_RATIO = 0.13
EQUIVALENT_NUMBER_OF_LOOKS = 4.4

DATA_PROVENANCE = "SYNTHETIC"


@dataclass(frozen=True)
class SyntheticSample:
    """One image/mask pair: ``image`` is ``(2, H, W)`` dB, ``mask`` is ``(H, W)`` 0/1."""

    index: int
    kind: SampleKind
    image: np.ndarray
    mask: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def oil_fraction(self) -> float:
        return float(self.mask.mean())

    def to_metadata(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind,
            "shape": list(self.image.shape),
            "dtype": str(self.image.dtype),
            "bands": ["VV", "VH"],
            "units": "sigma0 dB",
            "oil_fraction": round(self.oil_fraction, 6),
            "data_provenance": DATA_PROVENANCE,
            **self.metadata,
        }


def _ribbon(
    height: int, width: int, rng: np.random.Generator
) -> tuple[np.ndarray, dict[str, float]]:
    """A long, thin, meandering, tapering damped region — the shape oil actually makes."""
    rows = np.arange(height, dtype=np.float64)[:, None]
    cols = np.arange(width, dtype=np.float64)[None, :]
    bearing = float(rng.uniform(0.0, np.pi))
    centre_r = height * float(rng.uniform(0.3, 0.7))
    centre_c = width * float(rng.uniform(0.3, 0.7))

    along = (rows - centre_r) * np.cos(bearing) + (cols - centre_c) * np.sin(bearing)
    across = -(rows - centre_r) * np.sin(bearing) + (cols - centre_c) * np.cos(bearing)
    meander = (
        float(rng.uniform(0.03, 0.08))
        * width
        * np.sin(2.0 * np.pi * along / (float(rng.uniform(0.4, 0.7)) * height))
    )
    half_length = float(rng.uniform(0.25, 0.4)) * height
    half_width = float(rng.uniform(0.015, 0.035)) * width
    taper = np.clip(1.0 - (along / half_length) ** 2, 0.0, 1.0)
    profile = np.exp(-0.5 * ((across - meander) / (half_width * (0.4 + taper))) ** 2)
    field_values = np.where(taper > 0.0, profile, 0.0)
    return field_values, {
        "bearing_rad": bearing,
        "half_length_px": half_length,
        "half_width_px": half_width,
    }


def _blob(height: int, width: int, rng: np.random.Generator) -> np.ndarray:
    """A rounded low-wind patch: dark, but not oil.  The look-alike case."""
    rows = np.arange(height, dtype=np.float64)[:, None]
    cols = np.arange(width, dtype=np.float64)[None, :]
    centre_r = height * float(rng.uniform(0.25, 0.75))
    centre_c = width * float(rng.uniform(0.25, 0.75))
    radius_r = height * float(rng.uniform(0.08, 0.18))
    radius_c = width * float(rng.uniform(0.08, 0.18))
    distance = ((rows - centre_r) / radius_r) ** 2 + ((cols - centre_c) / radius_c) ** 2
    return np.exp(-0.5 * distance**1.4)


def generate_sample(
    index: int,
    *,
    size: int = 256,
    seed: int = 42,
    kind: SampleKind | None = None,
) -> SyntheticSample:
    """One deterministic sample.  The same ``(index, seed, size)`` always gives the same."""
    rng = np.random.default_rng((seed * 1_000_003 + index) % (2**32))
    if kind is None:
        kind = ("oil", "lookalike", "clean")[index % 3]

    cols = np.arange(size, dtype=np.float64)[None, :]
    gradient = 1.0 + 0.3 * (cols / max(1, size - 1) - 0.5)
    mean_vv = np.broadcast_to(SEA_SIGMA0_VV * gradient, (size, size)).copy()
    mask = np.zeros((size, size), dtype=np.uint8)
    metadata: dict[str, Any] = {}

    if kind == "oil":
        damping, shape_meta = _ribbon(size, size, rng)
        mean_vv = mean_vv * (1.0 - damping) + OIL_SIGMA0_VV * damping
        mask = (damping > 0.5).astype(np.uint8)
        metadata.update({k: round(v, 4) for k, v in shape_meta.items()})
    elif kind == "lookalike":
        damping = _blob(size, size, rng)
        mean_vv = mean_vv * (1.0 - damping) + LOOKALIKE_SIGMA0_VV * damping
        # Deliberately empty: a dark region that is not oil.
    # "clean" leaves the sea as it is.

    # Bright point targets — ships and rigs sit next to slicks in real scenes.
    for _ in range(int(rng.integers(1, 4))):
        r = int(rng.integers(4, size - 4))
        c = int(rng.integers(4, size - 4))
        mean_vv[r - 1 : r + 2, c - 1 : c + 2] *= float(rng.uniform(20.0, 60.0))

    speckle_vv = rng.gamma(
        EQUIVALENT_NUMBER_OF_LOOKS, 1.0 / EQUIVALENT_NUMBER_OF_LOOKS, size=(size, size)
    )
    speckle_vh = rng.gamma(
        EQUIVALENT_NUMBER_OF_LOOKS, 1.0 / EQUIVALENT_NUMBER_OF_LOOKS, size=(size, size)
    )
    sigma0 = np.stack([mean_vv * speckle_vv, mean_vv * VH_RATIO * speckle_vh])
    image = (10.0 * np.log10(np.maximum(sigma0, 1e-8))).astype(np.float32)

    return SyntheticSample(index=index, kind=kind, image=image, mask=mask, metadata=metadata)


def generate_dataset(count: int, *, size: int = 256, seed: int = 42) -> list[SyntheticSample]:
    return [generate_sample(index, size=size, seed=seed) for index in range(count)]


def dataset_fingerprint(samples: list[SyntheticSample]) -> str:
    """A hash of the generated content, so a manifest can pin the exact dataset."""
    digest = hashlib.sha256()
    for sample in samples:
        digest.update(sample.image.tobytes())
        digest.update(sample.mask.tobytes())
    return digest.hexdigest()


def write_dataset(directory: str | Path, samples: list[SyntheticSample]) -> Path:
    """Write samples to disk in the layout the real loader reads.

    ``<index>.tif`` holds the two dB bands; ``<index>_segmentation.tif`` holds the mask,
    which is how the published test set names its ground truth.
    """
    from rasterio.io import MemoryFile

    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []

    for sample in samples:
        _write_tif(MemoryFile, target / f"{sample.index:04d}.tif", sample.image, "float32")
        _write_tif(
            MemoryFile,
            target / f"{sample.index:04d}_segmentation.tif",
            sample.mask[np.newaxis, :, :],
            "uint8",
        )
        manifest.append(sample.to_metadata())

    manifest_path = target / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "data_provenance": DATA_PROVENANCE,
                "generator": "ml/src/dataset/synthetic.py",
                "note": (
                    "Deterministic synthetic SAR imagery. Metrics measured on it are "
                    "metrics on synthetic data, not on Sentinel-1 observations."
                ),
                "samples": manifest,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path


def _write_tif(memory_file: Any, path: Path, array: np.ndarray, dtype: str) -> None:
    import warnings

    from rasterio.errors import NotGeoreferencedWarning

    count, height, width = array.shape
    with warnings.catch_warnings():
        # The published test masks are not georeferenced either (AD-09).
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with memory_file() as handle:
            with handle.open(
                driver="GTiff",
                height=height,
                width=width,
                count=count,
                dtype=dtype,
                compress="deflate",
            ) as dataset:
                dataset.write(array.astype(dtype))
            path.write_bytes(bytes(handle.read()))


__all__ = [
    "DATA_PROVENANCE",
    "EQUIVALENT_NUMBER_OF_LOOKS",
    "LOOKALIKE_SIGMA0_VV",
    "OIL_SIGMA0_VV",
    "SEA_SIGMA0_VV",
    "SyntheticSample",
    "dataset_fingerprint",
    "generate_dataset",
    "generate_sample",
    "write_dataset",
]
