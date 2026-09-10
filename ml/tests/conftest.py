"""Shared fixtures.

``ml/src`` is on ``sys.path`` via ``pythonpath`` in ml/pyproject.toml; the backend
package supplies the shared tiling and normalisation code and is installed in the image.
"""

from __future__ import annotations

import pytest

requires_torch = pytest.mark.requires_torch


@pytest.fixture(scope="session")
def torch_module():
    return pytest.importorskip("torch")
