"""The smp-compatible ResNet-34 U-Net (AD-14) and the checkpoint loader that uses it."""

from __future__ import annotations

from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from spilltrace.core.errors import ModelNotAvailableError  # noqa: E402
from spilltrace.ml.inference import CheckpointRef, UNetModel  # noqa: E402
from spilltrace.ml.resnet_unet import (  # noqa: E402
    ResNetUNetConfig,
    build_resnet_unet,
    config_from_state_dict,
    looks_like_smp_state_dict,
)

EXPECTED_KEYS = {
    "encoder.conv1.weight",
    "encoder.bn1.running_mean",
    "encoder.layer1.0.conv1.weight",
    "encoder.layer2.0.downsample.0.weight",
    "encoder.layer4.2.bn2.num_batches_tracked",
    "decoder.blocks.0.conv1.0.weight",
    "decoder.blocks.0.conv1.1.bias",
    "decoder.blocks.4.conv2.1.running_var",
    "segmentation_head.0.weight",
    "segmentation_head.0.bias",
}


def test_state_dict_matches_smp_layout() -> None:
    module = build_resnet_unet(ResNetUNetConfig(in_channels=2, classes=1))
    state = module.state_dict()
    # 278 entries: what smp 0.5.0's Unet("resnet34", in_channels=2, classes=1) produces.
    assert len(state) == 278
    assert set(state) >= EXPECTED_KEYS
    assert tuple(state["encoder.conv1.weight"].shape) == (64, 2, 7, 7)
    assert tuple(state["decoder.blocks.0.conv1.0.weight"].shape) == (256, 768, 3, 3)
    assert tuple(state["segmentation_head.0.weight"].shape) == (1, 16, 3, 3)
    assert sum(p.numel() for p in module.parameters()) == 24_433_233
    assert looks_like_smp_state_dict(state)
    assert not looks_like_smp_state_dict({"encoders.0.block.0.weight": None})


def test_forward_shape_and_divisibility() -> None:
    module = build_resnet_unet().eval()
    with torch.inference_mode():
        out = module(torch.zeros(1, 2, 256, 256))
        assert tuple(out.shape) == (1, 1, 256, 256)
        out = module(torch.zeros(2, 2, 128, 64))
        assert tuple(out.shape) == (2, 1, 128, 64)
    with pytest.raises(ValueError, match="divisible by 32"):
        module(torch.zeros(1, 2, 100, 100))


def test_config_is_read_from_tensors() -> None:
    state = build_resnet_unet(ResNetUNetConfig(in_channels=3, classes=2)).state_dict()
    config = config_from_state_dict(state)
    assert (config.in_channels, config.classes) == (3, 2)
    assert config.decoder_channels == (256, 128, 64, 32, 16)


def _write_smp_checkpoint(path: Path) -> None:
    module = build_resnet_unet()
    torch.save(
        {
            "model": module.state_dict(),
            "args": {"encoder": "resnet34", "patch": 256},
            "epoch": 42,
            "val": {"dice": 0.84, "iou": 0.73, "precision": 0.77, "recall": 0.93, "loss": 0.08},
        },
        str(path),
    )


def test_loader_accepts_smp_format_and_labels_validation_metrics(tmp_path: Path) -> None:
    path = tmp_path / "best.pt"
    _write_smp_checkpoint(path)
    model = UNetModel(CheckpointRef(path=str(path), version="0.2.0", input_size=256))
    described = model.describe()
    assert described["architecture"]["encoder"] == "resnet34"
    assert described["parameter_count"] == 24_433_233
    assert described["metrics"]["validation"]["dice"] == pytest.approx(0.84)
    assert described["metrics"]["epoch"] == 42
    assert "test" not in described["metrics"]
    assert any("validation-split" in note for note in described["notes"])
    assert any("normalisation was not recorded" in note for note in described["notes"])


def test_loader_prefers_registry_metrics_over_checkpoint_metrics(tmp_path: Path) -> None:
    path = tmp_path / "best.pt"
    _write_smp_checkpoint(path)
    registry_metrics = {"validation": {"dice": 0.5}, "split": "validation"}
    model = UNetModel(
        CheckpointRef(path=str(path), input_size=256, params={"metrics": registry_metrics})
    )
    assert model.describe()["metrics"]["validation"]["dice"] == 0.5


@pytest.mark.asyncio
async def test_predict_returns_probabilities(tmp_path: Path) -> None:
    import numpy as np

    path = tmp_path / "best.pt"
    _write_smp_checkpoint(path)
    model = UNetModel(CheckpointRef(path=str(path), input_size=256))
    tiles = np.zeros((3, 2, 64, 64), dtype=np.float32)
    result = await model.predict(tiles)
    assert result.probability.shape == (3, 64, 64)
    assert float(result.probability.min()) >= 0.0 and float(result.probability.max()) <= 1.0
    assert str(result.data_provenance) == "REAL"


def test_loader_rejects_unknown_payload(tmp_path: Path) -> None:
    path = tmp_path / "junk.pt"
    torch.save({"model": {"foo.weight": torch.zeros(1)}}, str(path))
    with pytest.raises(ModelNotAvailableError, match="smp-style"):
        UNetModel(CheckpointRef(path=str(path)))
