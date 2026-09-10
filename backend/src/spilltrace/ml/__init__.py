"""SAR preprocessing, tiling, stitching and inference.

This package is the *runtime* half of the ML pipeline: it turns a downloaded GRD into
model input and a model output into a probability raster.  Training lives in the
top-level ``ml/`` directory and depends on PyTorch; nothing in here does, so the
container image stays torch-free unless a checkpoint is actually deployed.
"""

from __future__ import annotations

__all__: list[str] = []
