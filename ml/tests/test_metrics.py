"""Metrics, against hand-computed confusion matrices.

Each convention that could inflate a headline is asserted explicitly, because the point
of AD-10 is that these are the numbers nobody may quietly improve.
"""

from __future__ import annotations

import numpy as np
import pytest

from metrics import (
    ConfusionMatrix,
    best_threshold,
    confusion,
    dice,
    iou,
    oil_class_metrics,
    pixel_accuracy,
    precision,
    recall,
    sum_confusions,
    summarise,
    threshold_sweep,
)


def test_confusion_counts_are_what_you_would_count_by_hand() -> None:
    prediction = np.array([[1, 1, 0], [0, 1, 0]], dtype=bool)
    target = np.array([[1, 0, 0], [1, 1, 0]], dtype=bool)
    matrix = confusion(prediction, target)
    assert (matrix.tp, matrix.fp, matrix.fn, matrix.tn) == (2, 1, 1, 2)
    assert matrix.total == 6


def test_scalars_against_a_hand_computed_matrix() -> None:
    matrix = ConfusionMatrix(tp=2, fp=1, fn=1, tn=2)
    assert dice(matrix) == pytest.approx(4 / 6)
    assert iou(matrix) == pytest.approx(2 / 4)
    assert precision(matrix) == pytest.approx(2 / 3)
    assert recall(matrix) == pytest.approx(2 / 3)
    assert pixel_accuracy(matrix) == pytest.approx(4 / 6)


def test_a_perfect_prediction_scores_one() -> None:
    matrix = ConfusionMatrix(tp=10, fp=0, fn=0, tn=90)
    assert dice(matrix) == 1.0
    assert iou(matrix) == 1.0
    assert precision(matrix) == 1.0
    assert recall(matrix) == 1.0


def test_predicting_nothing_when_there_is_nothing_is_correct() -> None:
    matrix = ConfusionMatrix(tp=0, fp=0, fn=0, tn=100)
    assert dice(matrix) == 1.0
    assert iou(matrix) == 1.0
    assert precision(matrix) == 1.0
    assert recall(matrix) == 1.0


def test_predicting_nothing_when_there_is_oil_scores_zero() -> None:
    """The failure mode the class imbalance rewards; it must not read as success."""
    matrix = ConfusionMatrix(tp=0, fp=0, fn=25, tn=975)
    assert dice(matrix) == 0.0
    assert iou(matrix) == 0.0
    assert precision(matrix) == 0.0
    assert recall(matrix) == 0.0
    # ...while pixel accuracy is 97.5%, which is why it is never headlined.
    assert pixel_accuracy(matrix) == pytest.approx(0.975)


def test_summarise_labels_the_class_and_the_aggregation() -> None:
    payload = summarise(ConfusionMatrix(tp=5, fp=5, fn=5, tn=85))
    assert payload["class"] == "oil"
    assert "micro" in payload["aggregation"]
    assert payload["confusion"] == {"tp": 5, "fp": 5, "fn": 5, "tn": 85}


def test_micro_aggregation_is_not_a_mean_of_per_tile_dice() -> None:
    """Averaging per-tile Dice over mostly-empty tiles is the inflated version."""
    empty_tiles = [ConfusionMatrix(tp=0, fp=0, fn=0, tn=100) for _ in range(9)]
    hard_tile = ConfusionMatrix(tp=1, fp=0, fn=99, tn=0)

    micro = dice(sum_confusions([*empty_tiles, hard_tile]))
    macro = float(np.mean([dice(m) for m in [*empty_tiles, hard_tile]]))

    assert micro == pytest.approx(2 / 101)
    assert macro > 0.9
    assert micro < 0.05


def test_oil_class_metrics_apply_the_threshold() -> None:
    probability = np.array([[0.9, 0.4], [0.6, 0.1]])
    target = np.array([[1, 0], [1, 0]])
    strict = oil_class_metrics(probability, target, threshold=0.8)
    loose = oil_class_metrics(probability, target, threshold=0.5)
    assert strict["recall"] == pytest.approx(0.5)
    assert loose["recall"] == pytest.approx(1.0)
    assert strict["threshold"] == 0.8


def test_a_sweep_covers_every_threshold_and_picks_the_best_dice() -> None:
    rng = np.random.default_rng(0)
    target = np.zeros(1000, dtype=bool)
    target[:100] = True
    probability = np.where(target, rng.uniform(0.55, 1.0, 1000), rng.uniform(0.0, 0.45, 1000))

    sweep = threshold_sweep(probability, target)
    assert len(sweep) == 9
    chosen = best_threshold(sweep)
    assert chosen["dice"] == pytest.approx(1.0)
    assert 0.45 <= chosen["threshold"] <= 0.55


def test_ties_prefer_the_lower_threshold() -> None:
    """A lower threshold at equal Dice recalls more thin slick; prefer it."""
    sweep = [
        {"threshold": 0.3, "dice": 0.8},
        {"threshold": 0.7, "dice": 0.8},
    ]
    assert best_threshold(sweep)["threshold"] == 0.3


def test_shape_mismatch_is_an_error_not_a_broadcast() -> None:
    with pytest.raises(ValueError, match="Shape mismatch"):
        confusion(np.zeros((4, 4), dtype=bool), np.zeros((4, 5), dtype=bool))


def test_an_empty_sweep_has_no_operating_point() -> None:
    with pytest.raises(ValueError, match="no operating point"):
        best_threshold([])
