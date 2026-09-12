"""Arrange an already-downloaded Trujillo part into the layout the trainer expects.

The training loader (``ml/src/dataset/loader.py``) discovers pairs in one of two layouts:

* ``<root>/images/<stem>.tif`` beside ``<root>/masks/<stem>.tif``  (what this script builds), or
* ``<root>/<stem>.tif`` beside ``<root>/<stem>_segmentation.tif``  (the Part III test set).

Part I and Part II extract into their own folder structure, which varies, and the image
and mask files are not guaranteed to sit side by side.  This script walks whatever you
point it at, pairs every image GeoTIFF with its mask, and writes a clean
``images/`` + ``masks/`` directory with matching filenames, so a training config can
just set ``data.root`` to the output.

Nothing is deleted.  By default files are hard-linked (no extra disk); use ``--copy`` to
copy or ``--symlink`` to symlink instead.

    python ml/scripts/prepare_local_dataset.py \
        --src  ~/Downloads/trujillo/part1_extracted \
        --dest ml/data/trujillo \
        --max-images 400

Run it once per part with the SAME ``--dest`` to merge parts into one training set;
pass ``--part-prefix p2`` on the second run so filenames cannot collide.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path

IMAGE_SUFFIXES = (".tif", ".tiff")
# Tokens that mark a file as a mask rather than an image, case-insensitive.
MASK_TOKENS = ("_segmentation", "_mask", "_gt", "_label", "/mask", "/masks", "/label", "/labels")
IMAGE_HINTS = ("/image", "/images", "/img", "/sar")


def _looks_like_mask(path: Path) -> bool:
    p = path.as_posix().lower()
    return any(tok in p for tok in MASK_TOKENS)


def _stem_key(path: Path) -> str:
    """Normalise a filename down to the identifier shared by an image and its mask."""
    stem = path.stem.lower()
    for tok in ("_segmentation", "_mask", "_gt", "_label", "_img", "_image", "_sar"):
        stem = stem.replace(tok, "")
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return stem


def _walk_tifs(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.lower().endswith(IMAGE_SUFFIXES):
                out.append(Path(dirpath) / name)
    return sorted(out)


def pair_files(root: Path) -> tuple[list[tuple[str, Path, Path]], list[str]]:
    """Return ``[(key, image_path, mask_path)]`` and a list of human-readable warnings."""
    tifs = _walk_tifs(root)
    if not tifs:
        raise SystemExit(f"No .tif / .tiff files found anywhere under {root}")

    images: dict[str, Path] = {}
    masks: dict[str, Path] = {}
    for path in tifs:
        key = _stem_key(path)
        target = masks if _looks_like_mask(path) else images
        # First writer wins, but prefer a path whose folder name hints at its role.
        if key not in target:
            target[key] = path

    warnings: list[str] = []
    pairs: list[tuple[str, Path, Path]] = []
    for key, image_path in images.items():
        mask_path = masks.get(key)
        if mask_path is None:
            warnings.append(f"no mask for image {image_path.name} (key={key})")
            continue
        pairs.append((key, image_path, mask_path))

    for key, mask_path in masks.items():
        if key not in images:
            warnings.append(f"mask with no image: {mask_path.name} (key={key})")

    return pairs, warnings


def _place(src: Path, dst: Path, mode: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if mode == "copy":
        import shutil

        shutil.copy2(src, dst)
    elif mode == "symlink":
        dst.symlink_to(src.resolve())
    else:  # hardlink, with a copy fallback across filesystems
        try:
            os.link(src, dst)
        except OSError:
            import shutil

            shutil.copy2(src, dst)


def build(
    pairs: Iterable[tuple[str, Path, Path]],
    dest: Path,
    *,
    mode: str,
    prefix: str,
    limit: int | None,
) -> int:
    images_dir = dest / "images"
    masks_dir = dest / "masks"
    written = 0
    for index, (key, image_path, mask_path) in enumerate(pairs):
        if limit is not None and written >= limit:
            break
        name = f"{prefix}_{key}.tif" if prefix else f"{key}.tif"
        _place(image_path, images_dir / name, mode)
        _place(mask_path, masks_dir / name, mode)
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--src", required=True, help="Folder an extracted Trujillo part lives in.")
    parser.add_argument("--dest", default="ml/data/trujillo", help="Output dataset root.")
    parser.add_argument("--max-images", type=int, default=None, help="Cap the number of pairs.")
    parser.add_argument("--part-prefix", default="", help="Prefix added to every output filename.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--copy", action="store_true", help="Copy files (uses disk).")
    group.add_argument("--symlink", action="store_true", help="Symlink files.")
    parser.add_argument("--dry-run", action="store_true", help="Report pairing and stop.")
    args = parser.parse_args(argv)

    src = Path(args.src).expanduser()
    dest = Path(args.dest).expanduser()
    if not src.is_dir():
        print(f"--src is not a directory: {src}", file=sys.stderr)
        return 2

    pairs, warnings = pair_files(src)
    print(f"found {len(pairs)} image/mask pairs under {src}")
    for line in warnings[:20]:
        print(f"  warning: {line}")
    if len(warnings) > 20:
        print(f"  ... and {len(warnings) - 20} more warnings")

    if args.dry_run:
        for key, image_path, mask_path in pairs[:10]:
            print(f"  {key}\n    image: {image_path}\n    mask : {mask_path}")
        print("(dry run — nothing written)")
        return 0

    mode = "copy" if args.copy else "symlink" if args.symlink else "hardlink"
    written = build(
        pairs, dest, mode=mode, prefix=args.part_prefix, limit=args.max_images
    )
    print(f"wrote {written} pairs into {dest}/images and {dest}/masks  (mode: {mode})")
    print(f"now set  data.root: {dest}  in your training config")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
