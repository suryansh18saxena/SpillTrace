"""Configuration: the defaults are the documented ones and a typo cannot pass silently."""

from __future__ import annotations

import json

import pytest

from config import DEFAULT_CONFIG_DIR, TrainConfig, load_config


def test_defaults_match_the_documented_cpu_configuration() -> None:
    config = TrainConfig()
    assert (config.data.patch_size, config.data.stride) == (128, 96)
    assert (config.model.depth, config.model.base_filters) == (4, 16)
    assert config.model.norm_groups == 8
    assert config.optim.lr == 3e-4
    assert config.optim.warmup_epochs == 3
    assert config.optim.early_stop_patience == 8
    assert config.loss.pos_weight_max == 10.0
    assert config.model.in_channels == 2


def test_the_shipped_cpu_config_loads_and_agrees_with_the_decision_record() -> None:
    config = load_config(DEFAULT_CONFIG_DIR / "cpu_baseline.yaml")
    assert config.name == "unet-cpu-baseline"
    assert config.data.patch_size == 128
    assert config.data.stride == 96
    assert config.model.base_filters == 16
    assert config.optim.epochs == 30
    assert config.optim.threads == 8
    assert config.data.expected_band_order == ("VV", "VH")


def test_the_smoke_config_is_synthetic_and_short() -> None:
    config = load_config(DEFAULT_CONFIG_DIR / "synthetic_smoke.yaml")
    assert config.data.synthetic is True
    assert config.optim.epochs <= 5


def test_an_unknown_key_is_rejected_rather_than_ignored() -> None:
    with pytest.raises(ValueError, match="Unknown key"):
        TrainConfig.from_dict({"optim": {"learning_rate": 0.1}})
    with pytest.raises(ValueError, match="Unknown top-level key"):
        TrainConfig.from_dict({"epochs": 10})


def test_config_round_trips_through_json() -> None:
    config = load_config(DEFAULT_CONFIG_DIR / "cpu_baseline.yaml")
    restored = TrainConfig.from_dict(json.loads(config.to_json()))
    assert restored.to_dict() == config.to_dict()


def test_config_is_saved_beside_a_run(tmp_path) -> None:
    config = TrainConfig()
    path = config.save(tmp_path / "run" / "config.json")
    assert path.is_file()
    assert json.loads(path.read_text())["model"]["depth"] == 4


def test_device_auto_resolves_to_something_concrete() -> None:
    assert TrainConfig().resolve_device() in {"cpu", "cuda", "mps"}
    assert TrainConfig(device="cpu").resolve_device() == "cpu"


def test_overrides_do_not_mutate_the_original() -> None:
    config = TrainConfig()
    other = config.with_overrides(seed=99)
    assert config.seed == 42
    assert other.seed == 99
