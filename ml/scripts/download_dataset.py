"""Acquire the Trujillo-Acatitla oil-spill dataset from Zenodo (DATA-002, AD-09).

The three parts total **96.5 GB**, which is not a reasonable default download, so this
script is built around taking a documented subset:

* ``--dry-run`` lists every file with its size and MD5 and downloads nothing;
* ``--parts`` selects which records to fetch (default: Part III, 9.86 GB);
* ``--max-bytes`` stops after a byte budget — the partial file resumes later;
* ``--max-images`` limits how many image/mask pairs are extracted from an archive.

Transfers are **ranged and resumable** (Zenodo answers an unauthenticated ranged GET with
``206 PARTIAL_CONTENT``) and every completed file is verified against the MD5 the record
metadata publishes.  A checksum mismatch deletes the file rather than leaving a corrupt
archive that fails confusingly later.

```
python ml/scripts/download_dataset.py --dry-run
python ml/scripts/download_dataset.py --parts III --dest data/trujillo
```
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ZENODO_API = "https://zenodo.org/api/records"

#: CONFIRMED via the Zenodo REST API on 2026-09-10 (AD-09).
PARTS: dict[str, dict[str, Any]] = {
    "I": {"record": "8346860", "contents": "1200 oil-spill images + masks", "gb": 40.7},
    "II": {"record": "8253899", "contents": "685 no-oil + 685 look-alike + masks", "gb": 45.9},
    "III": {
        "record": "13761290",
        "contents": "150 oil / 150 look-alike / 150 no-oil + GT",
        "gb": 9.86,
    },
}
DEFAULT_PARTS = ("III",)
CHUNK = 4 * 1024 * 1024


@dataclass(frozen=True)
class RemoteFile:
    part: str
    key: str
    size: int
    md5: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "part": self.part,
            "key": self.key,
            "size_bytes": self.size,
            "size_gb": round(self.size / 1e9, 3),
            "md5": self.md5,
            "url": self.url,
        }


def list_files(part: str, *, timeout: float = 30.0) -> list[RemoteFile]:
    import httpx

    record = PARTS[part]["record"]
    response = httpx.get(f"{ZENODO_API}/{record}", timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    payload = response.json()
    files: list[RemoteFile] = []
    for entry in payload.get("files", []):
        checksum = str(entry.get("checksum") or "")
        links = entry.get("links") or {}
        url = links.get("self") or links.get("download") or ""
        files.append(
            RemoteFile(
                part=part,
                key=str(entry.get("key") or ""),
                size=int(entry.get("size") or 0),
                md5=checksum.removeprefix("md5:"),
                url=str(url),
            )
        )
    return files


def md5_of(path: Path, chunk: int = CHUNK) -> str:
    digest = hashlib.md5()  # noqa: S324 - Zenodo publishes MD5; this is integrity, not security
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def download(
    remote: RemoteFile, destination: Path, *, max_bytes: int | None = None, timeout: float = 60.0
) -> tuple[Path, bool]:
    """Fetch one file, resuming a partial download.  Returns ``(path, complete)``."""
    import httpx

    destination.mkdir(parents=True, exist_ok=True)
    path = destination / remote.key
    have = path.stat().st_size if path.exists() else 0

    if remote.size and have >= remote.size:
        return path, True

    budget = max_bytes if max_bytes is not None else None
    headers = {"Range": f"bytes={have}-"} if have else {}
    with httpx.stream(
        "GET", remote.url, headers=headers, timeout=timeout, follow_redirects=True
    ) as response:
        if response.status_code == 200 and have:
            # The server ignored the range; start again rather than appending.
            path.unlink(missing_ok=True)
            have = 0
        response.raise_for_status()
        with path.open("ab" if have else "wb") as handle:
            for block in response.iter_bytes(CHUNK):
                handle.write(block)
                have += len(block)
                if budget is not None:
                    budget -= len(block)
                    if budget <= 0:
                        print(
                            f"  stopped at {have / 1e9:.2f} GB (byte budget reached); "
                            "re-run to resume",
                            flush=True,
                        )
                        return path, False

    complete = not remote.size or have >= remote.size
    if complete and remote.md5:
        actual = md5_of(path)
        if actual != remote.md5:
            path.unlink(missing_ok=True)
            raise SystemExit(
                f"MD5 mismatch for {remote.key}: expected {remote.md5}, got {actual}. "
                "The partial file was deleted; re-run to download it again."
            )
    return path, complete


def extract(archive: Path, destination: Path, *, max_images: int | None) -> dict[str, Any]:
    """Extract a 7-Zip archive, optionally only the first ``max_images`` pairs."""
    try:
        import py7zr
    except ImportError:
        return {
            "extracted": False,
            "reason": (
                "py7zr is not installed, so the 7-Zip archive was downloaded but not "
                "extracted. Install it with 'pip install py7zr', or extract manually "
                f"with '7z x {archive}'."
            ),
        }

    destination.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(str(archive), mode="r") as handle:
        names = sorted(handle.getnames())
        selected = names
        if max_images is not None:
            stems: list[str] = []
            for name in names:
                stem = Path(name).stem.replace("_segmentation", "")
                if stem not in stems:
                    stems.append(stem)
                if len(stems) >= max_images:
                    break
            wanted = set(stems)
            selected = [
                name for name in names if Path(name).stem.replace("_segmentation", "") in wanted
            ]
        handle.extract(path=str(destination), targets=selected)
    return {"extracted": True, "members": len(selected), "destination": str(destination)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--parts", nargs="*", default=list(DEFAULT_PARTS), choices=list(PARTS))
    parser.add_argument("--dest", default="data/trujillo")
    parser.add_argument("--dry-run", action="store_true", help="List files and exit.")
    parser.add_argument("--max-bytes", type=float, default=None, help="Byte budget per file.")
    parser.add_argument("--max-images", type=int, default=None, help="Pairs to extract.")
    parser.add_argument("--no-extract", action="store_true")
    args = parser.parse_args(argv)

    destination = Path(args.dest)
    report: dict[str, Any] = {"parts": {}, "total_bytes": 0}

    for part in args.parts:
        try:
            files = list_files(part)
        except Exception as exc:
            print(f"Could not list part {part}: {exc}", file=sys.stderr)
            return 2
        total = sum(f.size for f in files)
        report["parts"][part] = {
            "record": PARTS[part]["record"],
            "contents": PARTS[part]["contents"],
            "files": [f.to_dict() for f in files],
            "total_gb": round(total / 1e9, 3),
        }
        report["total_bytes"] += total

    report["total_gb"] = round(report["total_bytes"] / 1e9, 3)
    if args.dry_run:
        print(json.dumps(report, indent=2))
        return 0

    print(f"About to download {report['total_gb']} GB into {destination}", flush=True)
    for part, entry in report["parts"].items():
        for payload in entry["files"]:
            remote = RemoteFile(
                part=part,
                key=payload["key"],
                size=payload["size_bytes"],
                md5=payload["md5"],
                url=payload["url"],
            )
            print(f"[{part}] {remote.key} ({remote.size / 1e9:.2f} GB)", flush=True)
            path, complete = download(
                remote,
                destination / part,
                max_bytes=int(args.max_bytes) if args.max_bytes else None,
            )
            payload["path"] = str(path)
            payload["complete"] = complete
            if complete and not args.no_extract and path.suffix.lower() in (".7z", ".zip"):
                payload["extraction"] = extract(
                    path, destination / part / "extracted", max_images=args.max_images
                )

    manifest_path = destination / "download_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "total_gb": report["total_gb"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
