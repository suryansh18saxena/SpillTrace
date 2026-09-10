"""Image-level splits, hashed and written down (P10-006).

**Splits are made at image level, before tiling.**  Tiles cut from one 2048² image share
speckle statistics, sea state and usually the same slick; a tile-level split therefore
puts near-duplicates of a training tile into validation, and the validation score
measures memorisation.  The difference is not subtle — it is the difference between a
number that predicts field performance and one that does not.

The member list is hashed so a manifest can prove which split produced a metric, and a
regeneration that would change it requires an explicit flag.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SPLITS_FILENAME = "splits.json"


@dataclass(frozen=True)
class Splits:
    train: tuple[str, ...]
    val: tuple[str, ...]
    test: tuple[str, ...]
    seed: int
    note: str = ""

    @property
    def hash(self) -> str:
        payload = json.dumps(
            {"train": sorted(self.train), "val": sorted(self.val), "test": sorted(self.test)},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "train": list(self.train),
            "val": list(self.val),
            "test": list(self.test),
            "seed": self.seed,
            "hash": self.hash,
            "level": "image",
            "note": self.note
            or (
                "Split at image level before tiling. This is OUR split, not the split "
                "used by the dataset's authors; metrics are not comparable to theirs."
            ),
        }


def make_splits(
    members: list[str], *, val_fraction: float = 0.15, test_fraction: float = 0.15, seed: int = 42
) -> Splits:
    if not members:
        raise ValueError("Cannot split an empty dataset.")
    if val_fraction + test_fraction >= 1.0:
        raise ValueError("val_fraction + test_fraction must leave something to train on.")

    ordered = sorted(members)
    rng = np.random.default_rng(seed)
    shuffled = list(rng.permutation(np.asarray(ordered, dtype=object)))

    total = len(shuffled)
    n_test = max(1, round(total * test_fraction)) if total > 2 else 0
    n_val = max(1, round(total * val_fraction)) if total > 2 else 0
    if n_test + n_val >= total:
        n_val = max(0, total - 1 - n_test)

    test = tuple(str(m) for m in shuffled[:n_test])
    val = tuple(str(m) for m in shuffled[n_test : n_test + n_val])
    train = tuple(str(m) for m in shuffled[n_test + n_val :])
    return Splits(train=train, val=val, test=test, seed=seed)


def save_splits(directory: str | Path, splits: Splits) -> Path:
    path = Path(directory) / SPLITS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(splits.to_dict(), indent=2), encoding="utf-8")
    return path


def load_splits(directory: str | Path) -> Splits | None:
    path = Path(directory) / SPLITS_FILENAME
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Splits(
        train=tuple(payload.get("train", ())),
        val=tuple(payload.get("val", ())),
        test=tuple(payload.get("test", ())),
        seed=int(payload.get("seed", 0)),
        note=str(payload.get("note", "")),
    )


def resolve_splits(
    directory: str | Path,
    members: list[str],
    *,
    val_fraction: float = 0.15,
    test_fraction: float = 0.15,
    seed: int = 42,
    regenerate: bool = False,
) -> Splits:
    """Reuse the split on disk unless told to regenerate it.

    Silently regenerating would mean two runs of the same command report metrics on
    different test sets, which makes every comparison between them meaningless.
    """
    existing = load_splits(directory)
    if existing is not None and not regenerate:
        known = set(existing.train) | set(existing.val) | set(existing.test)
        missing = sorted(set(members) - known)
        if missing:
            raise ValueError(
                f"{len(missing)} image(s) are not in the saved split "
                f"(for example {missing[:3]}). Pass regenerate=True to rebuild it, "
                "and re-measure every metric afterwards."
            )
        return existing
    splits = make_splits(members, val_fraction=val_fraction, test_fraction=test_fraction, seed=seed)
    save_splits(directory, splits)
    return splits


__all__ = [
    "SPLITS_FILENAME",
    "Splits",
    "load_splits",
    "make_splits",
    "resolve_splits",
    "save_splits",
]
