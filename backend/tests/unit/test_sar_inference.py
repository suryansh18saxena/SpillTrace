"""Segmentation models and the factory that chooses between them.

The behaviour that matters is not accuracy — the analytical detector is not a trained
model and never claims to be — but *honesty*: what it labels its output, what happens
when a checkpoint is absent, and that the choice of model is never silent.
"""

from __future__ import annotations

import numpy as np
import pytest

from spilltrace.config import Settings
from spilltrace.core.enums import DataProvenance
from spilltrace.core.errors import ModelNotAvailableError
from spilltrace.core.ports import SegmentationModel
from spilltrace.ml.inference import (
    ANALYTICAL_NAME,
    AnalyticalDetector,
    CheckpointRef,
    UNetModel,
    build_segmentation_model,
)


def _settings(**overrides: str) -> Settings:
    values: dict[str, str] = {
        "SPILLTRACE_SECRET_KEY": "unit-test-secret-key-0123456789abcdef",
        "POSTGRES_PASSWORD": "unit-test-password",
        "CDSE_USERNAME": "",
        "CDSE_PASSWORD": "",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _tiles_with_dark_patch(n: int = 3, size: int = 64) -> np.ndarray:
    rng = np.random.default_rng(7)
    tiles = rng.normal(0.0, 1.0, size=(n, 2, size, size)).astype(np.float32)
    # A region 4 sigma below the sea: an oil-like damped surface after standardisation.
    tiles[:, :, 20:44, 10:54] -= 4.0
    return tiles


# --------------------------------------------------------------------------- analytical
async def test_analytical_detector_finds_the_dark_patch() -> None:
    result = await AnalyticalDetector().predict(_tiles_with_dark_patch())
    probability = result.probability
    assert probability.shape == (3, 64, 64)
    assert probability.dtype == np.float32
    inside = probability[:, 26:38, 20:44].mean()
    outside = probability[:, :10, :10].mean()
    assert inside > 0.8
    assert outside < 0.1


async def test_analytical_output_is_labelled_synthetic_and_says_it_is_untrained() -> None:
    result = await AnalyticalDetector().predict(_tiles_with_dark_patch(1))
    assert result.data_provenance is DataProvenance.SYNTHETIC
    assert result.model_name == ANALYTICAL_NAME
    assert any("not by a trained model" in note for note in result.notes)
    described = AnalyticalDetector().describe()
    assert described["trained"] is False
    assert "metrics" not in described  # an untrained detector has none to report


async def test_analytical_detector_is_deterministic() -> None:
    tiles = _tiles_with_dark_patch()
    first = await AnalyticalDetector().predict(tiles)
    second = await AnalyticalDetector().predict(tiles)
    assert np.array_equal(first.probability, second.probability)


async def test_probabilities_stay_in_the_unit_interval() -> None:
    result = await AnalyticalDetector().predict(_tiles_with_dark_patch())
    assert float(result.probability.min()) >= 0.0
    assert float(result.probability.max()) <= 1.0


async def test_bright_targets_are_suppressed_rather_than_detected() -> None:
    """A ship is brighter than the sea; a dark-region detector must not fire on it."""
    rng = np.random.default_rng(11)
    tiles = rng.normal(0.0, 1.0, size=(1, 2, 64, 64)).astype(np.float32)
    tiles[:, :, 30:34, 30:34] += 25.0
    result = await AnalyticalDetector().predict(tiles)
    assert float(result.probability[0, 30:34, 30:34].max()) == 0.0


async def test_a_single_untiled_scene_returns_a_two_dimensional_map() -> None:
    scene = _tiles_with_dark_patch(1)[0]
    result = await AnalyticalDetector().predict(scene)
    assert result.probability.shape == (64, 64)


async def test_single_channel_input_is_accepted() -> None:
    tiles = _tiles_with_dark_patch(1)[:, :1]
    result = await AnalyticalDetector().predict(tiles)
    assert result.input_channels == 1
    assert result.probability.shape == (1, 64, 64)


async def test_batch_statistics_do_not_change_with_batch_order() -> None:
    """The robust scale is a whole-batch statistic, so tile order must not matter."""
    tiles = _tiles_with_dark_patch(4)
    forward = (await AnalyticalDetector().predict(tiles)).probability
    reverse = (await AnalyticalDetector().predict(tiles[::-1])).probability
    assert np.allclose(forward, reverse[::-1], atol=1e-6)


async def test_malformed_input_is_rejected() -> None:
    with pytest.raises(ValueError, match="Expected tiles"):
        await AnalyticalDetector().predict(np.zeros((5, 5), dtype=np.float32))


def test_analytical_detector_satisfies_the_port() -> None:
    assert isinstance(AnalyticalDetector(), SegmentationModel)


# --------------------------------------------------------------------------- U-Net
def test_unet_without_a_checkpoint_file_raises_rather_than_guessing() -> None:
    with pytest.raises(ModelNotAvailableError):
        UNetModel(CheckpointRef(path="/nonexistent/checkpoint.pt"))


def test_unet_rejects_a_checkpoint_without_a_state_dict(tmp_path: object) -> None:
    torch = pytest.importorskip("torch")
    path = tmp_path / "broken.pt"  # type: ignore[operator]
    torch.save({"not_a_model": True}, str(path))
    with pytest.raises(ModelNotAvailableError, match="state_dict"):
        UNetModel(CheckpointRef(path=str(path)))


async def test_unet_round_trips_a_saved_checkpoint(tmp_path: object) -> None:
    torch = pytest.importorskip("torch")
    from spilltrace.ml.unet import UNetConfig, build_unet

    config = UNetConfig(base_filters=4, depth=2)
    module = build_unet(config)
    path = tmp_path / "unet.pt"  # type: ignore[operator]
    torch.save(
        {"state_dict": module.state_dict(), "model_config": config.to_dict(), "metrics": {}},
        str(path),
    )

    model = UNetModel(CheckpointRef(path=str(path), version="0.1.0"))
    result = await model.predict(_tiles_with_dark_patch(2, size=32))
    assert result.probability.shape == (2, 32, 32)
    assert 0.0 <= float(result.probability.min()) <= float(result.probability.max()) <= 1.0
    assert result.data_provenance is DataProvenance.REAL
    assert any("no measured evaluation metrics" in note for note in result.notes)
    assert model.describe()["metrics"] == {}


# --------------------------------------------------------------------------- factory
def test_factory_returns_the_analytical_detector_by_default() -> None:
    model = build_segmentation_model(_settings(SPILLTRACE_SEGMENTATION_MODEL="analytical"))
    assert model.name == ANALYTICAL_NAME


def test_factory_degrades_when_unet_is_requested_without_a_checkpoint() -> None:
    model = build_segmentation_model(_settings(SPILLTRACE_SEGMENTATION_MODEL="unet"))
    assert model.name == ANALYTICAL_NAME


def test_factory_can_be_told_to_fail_instead_of_degrading() -> None:
    with pytest.raises(ModelNotAvailableError, match="no model_versions row"):
        build_segmentation_model(
            _settings(SPILLTRACE_SEGMENTATION_MODEL="unet"), allow_fallback=False
        )


def test_factory_degrades_when_the_checkpoint_cannot_be_loaded() -> None:
    model = build_segmentation_model(
        _settings(SPILLTRACE_SEGMENTATION_MODEL="unet"),
        checkpoint=CheckpointRef(path="/nonexistent/checkpoint.pt"),
    )
    assert model.name == ANALYTICAL_NAME
