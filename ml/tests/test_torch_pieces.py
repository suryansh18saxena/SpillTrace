"""Model, loss and training loop.  Skipped entirely when PyTorch is absent.

torch is an optional dependency (AD-11): the default image is built without it, so these
tests must skip rather than fail.  Everything they cover is exercised on the synthetic
generator, so a real dataset is never needed.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from config import TrainConfig  # noqa: E402
from dataset.augment import AugmentConfig  # noqa: E402
from dataset.tiles import build_tileset  # noqa: E402
from losses import CompoundLoss, compute_pos_weight, soft_dice_loss  # noqa: E402
from model import EncoderNotAvailableError, build_model, parameter_count  # noqa: E402


# --------------------------------------------------------------------------- model
def test_the_unet_preserves_spatial_shape_and_emits_one_logit_channel() -> None:
    model = build_model(TrainConfig().model)
    output = model(torch.zeros(2, 2, 128, 128))
    assert output.shape == (2, 1, 128, 128)


def test_the_cpu_default_is_about_two_million_parameters() -> None:
    """AD-11 budgets ~1.9M at depth 4 / base 16; base 64 would be ~31M."""
    count = parameter_count(build_model(TrainConfig().model))
    assert 1.5e6 < count < 2.5e6


def test_normalisation_is_groupnorm_not_batchnorm() -> None:
    """Small CPU batches make BatchNorm's running statistics unreliable (AD-11)."""
    model = build_model(TrainConfig().model)
    kinds = {type(module).__name__ for module in model.modules()}
    assert "GroupNorm" in kinds
    assert not any(name.startswith("BatchNorm") for name in kinds)


def test_a_batch_of_one_works() -> None:
    """BatchNorm would fail here in train mode; GroupNorm does not."""
    model = build_model(TrainConfig().model)
    model.train()
    assert model(torch.zeros(1, 2, 64, 64)).shape == (1, 1, 64, 64)


def test_channel_count_follows_the_configuration() -> None:
    from dataclasses import replace

    config = replace(TrainConfig().model, in_channels=1)
    assert build_model(config)(torch.zeros(1, 1, 64, 64)).shape == (1, 1, 64, 64)


def test_the_model_is_deterministic_under_a_fixed_seed() -> None:
    torch.manual_seed(0)
    first = build_model(TrainConfig().model)(torch.ones(1, 2, 64, 64))
    torch.manual_seed(0)
    second = build_model(TrainConfig().model)(torch.ones(1, 2, 64, 64))
    assert torch.allclose(first, second)


def test_an_unimplemented_encoder_raises_instead_of_falling_back() -> None:
    from dataclasses import replace

    with pytest.raises(EncoderNotAvailableError, match="resnet34"):
        build_model(replace(TrainConfig().model, encoder="resnet34"))


def test_a_checkpoint_round_trips(tmp_path) -> None:
    model = build_model(TrainConfig().model)
    path = tmp_path / "checkpoint.pt"
    torch.save({"state_dict": model.state_dict()}, str(path))
    restored = build_model(TrainConfig().model)
    restored.load_state_dict(torch.load(str(path), weights_only=False)["state_dict"])
    sample = torch.randn(1, 2, 64, 64)
    model.eval()
    restored.eval()
    with torch.inference_mode():
        assert torch.allclose(model(sample), restored(sample), atol=1e-6)


# --------------------------------------------------------------------------- loss
def test_soft_dice_is_zero_for_a_perfect_prediction() -> None:
    targets = torch.zeros(1, 1, 8, 8)
    targets[:, :, 2:6, 2:6] = 1.0
    logits = torch.where(targets > 0, torch.tensor(20.0), torch.tensor(-20.0))
    assert float(soft_dice_loss(logits, targets)) == pytest.approx(0.0, abs=1e-3)


def test_soft_dice_is_near_one_for_an_inverted_prediction() -> None:
    targets = torch.zeros(1, 1, 8, 8)
    targets[:, :, 2:6, 2:6] = 1.0
    logits = torch.where(targets > 0, torch.tensor(-20.0), torch.tensor(20.0))
    assert float(soft_dice_loss(logits, targets)) > 0.9


def test_pos_weight_is_the_clamped_negative_positive_ratio() -> None:
    targets = torch.zeros(1, 1, 10, 10)
    targets[:, :, :1, :5] = 1.0  # 5 positives, 95 negatives
    assert float(compute_pos_weight(targets, max_value=100.0)) == pytest.approx(19.0)
    assert float(compute_pos_weight(targets, max_value=10.0)) == pytest.approx(10.0)


def test_pos_weight_survives_an_all_sea_batch() -> None:
    """An unclamped ratio here is infinite and the loss becomes NaN."""
    value = compute_pos_weight(torch.zeros(1, 1, 8, 8), max_value=10.0)
    assert float(value) == 10.0
    assert torch.isfinite(value)


def test_the_warmup_uses_bce_only_and_then_the_compound_loss() -> None:
    criterion = CompoundLoss(warmup_epochs=3)
    targets = torch.zeros(1, 1, 8, 8)
    targets[:, :, 2:6, 2:6] = 1.0
    logits = torch.zeros_like(targets)

    assert criterion.dice_active(0) is False
    assert criterion.dice_active(3) is True

    warm = float(criterion(logits, targets, epoch=0))
    compound = float(criterion(logits, targets, epoch=5))
    bce = float(
        torch.nn.functional.binary_cross_entropy_with_logits(
            logits, targets, pos_weight=compute_pos_weight(targets)
        )
    )
    assert warm == pytest.approx(bce, rel=1e-5)
    assert compound != pytest.approx(bce, rel=1e-5)
    assert criterion.describe()["warmup_epochs"] == 3


def test_the_loss_produces_a_gradient() -> None:
    model = build_model(TrainConfig().model)
    criterion = CompoundLoss(warmup_epochs=0)
    targets = torch.zeros(1, 1, 64, 64)
    targets[:, :, 10:30, 10:30] = 1.0
    loss = criterion(model(torch.randn(1, 2, 64, 64)), targets, epoch=1)
    loss.backward()
    assert any(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())


# --------------------------------------------------------------------------- data
def test_the_torch_dataset_yields_correctly_shaped_tensors() -> None:
    from dataset.torch_data import TileDataset, build_loader

    images = np.zeros((6, 2, 32, 32), dtype=np.float32)
    masks = np.zeros((6, 32, 32), dtype=np.float32)
    masks[0, 4:10, 4:10] = 1.0
    tiles = build_tileset(
        [("a", images[0], masks[0])], patch_size=32, stride=32, empty_tile_fraction=None
    )
    dataset = TileDataset(tiles, augment_config=AugmentConfig(), seed=1)
    image, mask = dataset[0]
    assert image.shape == (2, 32, 32)
    assert mask.shape == (1, 32, 32)
    assert image.dtype == torch.float32

    loader = build_loader(dataset, batch_size=2)
    batch_image, batch_mask = next(iter(loader))
    assert batch_image.shape[0] <= 2
    assert batch_mask.shape[1] == 1


# --------------------------------------------------------------------------- training
@pytest.mark.slow
def test_a_short_synthetic_run_trains_and_writes_honest_artifacts(tmp_path) -> None:
    from dataclasses import replace

    from train import run

    config = TrainConfig(
        name="pytest-smoke",
        seed=3,
        device="cpu",
        output_dir=str(tmp_path),
        model=replace(TrainConfig().model, base_filters=4, depth=2),
        data=replace(
            TrainConfig().data,
            synthetic=True,
            synthetic_images=6,
            synthetic_size=96,
            patch_size=32,
            stride=32,
            val_fraction=0.25,
            test_fraction=0.25,
        ),
        optim=replace(
            TrainConfig().optim,
            epochs=2,
            warmup_epochs=1,
            batch_size=4,
            num_workers=0,
            threads=2,
        ),
    )
    result = run(config)

    run_dir = tmp_path / "pytest-smoke"
    assert (run_dir / "best.pt").is_file()
    assert (run_dir / "manifest.json").is_file()
    manifest = json.loads((run_dir / "manifest.json").read_text())

    assert manifest["seed"] == 3
    assert manifest["split_hash"]
    assert manifest["parameters"] > 0
    assert manifest["timings"]["epochs_run"] == 2
    assert manifest["timings"]["mean_epoch_seconds"] > 0
    assert manifest["metrics_measured"] is True
    assert any("SYNTHETIC" in note for note in manifest["notes"])
    assert any("not comparable to published benchmarks" in note for note in manifest["notes"])

    metrics = result["metrics"]
    assert metrics["threshold_selected_on"] == "validation"
    assert 0.0 <= metrics["test"]["dice"] <= 1.0
    assert metrics["test"]["class"] == "oil"
    assert len(result["history"]) == 2


@pytest.mark.slow
def test_the_benchmark_flag_runs_exactly_one_epoch_and_measures_it(tmp_path) -> None:
    """AD-11 requires a measured epoch before committing to a long run."""
    from dataclasses import replace

    from train import run

    config = TrainConfig(
        name="pytest-benchmark",
        device="cpu",
        output_dir=str(tmp_path),
        model=replace(TrainConfig().model, base_filters=4, depth=2),
        data=replace(
            TrainConfig().data,
            synthetic=True,
            synthetic_images=4,
            synthetic_size=64,
            patch_size=32,
            stride=32,
        ),
        optim=replace(TrainConfig().optim, epochs=20, num_workers=0, threads=2),
    )
    result = run(config, benchmark_epoch=True)
    manifest = result["manifest"]
    assert manifest["timings"]["epochs_run"] == 1
    assert manifest["timings"]["mean_epoch_seconds"] > 0
    # A benchmark measures cost, not accuracy: it must not publish metrics.
    assert manifest["metrics"] == {}
    assert any("Benchmark run" in note for note in manifest["notes"])
