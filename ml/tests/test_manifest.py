"""The experiment manifest: complete, reproducible, and empty when nothing was measured."""

from __future__ import annotations

import json

from config import TrainConfig
from manifest import ExperimentManifest, environment, git_sha


def _manifest(**overrides) -> ExperimentManifest:
    payload = {
        "name": "test-run",
        "config": TrainConfig().to_dict(),
        "seed": 42,
    }
    payload.update(overrides)
    return ExperimentManifest(**payload)


def test_a_manifest_carries_everything_needed_to_repeat_a_run() -> None:
    payload = _manifest().to_dict()
    for key in ("name", "git_sha", "seed", "config", "environment", "created_at"):
        assert key in payload
    assert payload["environment"]["python"]
    assert "cuda_available" in payload["environment"]


def test_metrics_are_empty_until_something_measures_them() -> None:
    """An unevaluated model must not carry a number nobody computed (AD-10)."""
    payload = _manifest().to_dict()
    assert payload["metrics"] == {}
    assert payload["metrics_measured"] is False

    measured = _manifest(metrics={"dice": 0.61}).to_dict()
    assert measured["metrics_measured"] is True


def test_the_fingerprint_ignores_wall_clock_but_not_the_configuration() -> None:
    first = _manifest()
    second = _manifest()
    second.timings = {"total_seconds": 999.0}
    second.note("a note")
    assert first.fingerprint() == second.fingerprint()

    changed = _manifest(seed=7)
    assert changed.fingerprint() != first.fingerprint()


def test_a_manifest_saves_as_readable_json(tmp_path) -> None:
    path = _manifest().save(tmp_path)
    assert path.name == "manifest.json"
    assert json.loads(path.read_text())["seed"] == 42


def test_git_sha_is_a_sha_or_the_word_unknown() -> None:
    sha = git_sha()
    assert sha == "unknown" or len(sha) == 40


def test_environment_records_whether_torch_is_present() -> None:
    info = environment()
    assert "torch" in info
    assert isinstance(info["cuda_available"], bool)
