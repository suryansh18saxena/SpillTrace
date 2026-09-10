"""The Zenodo downloader, against a mocked HTTP transport.

Nothing here touches the network or the 96.5 GB the real records hold.  What is tested is
the behaviour AD-09 depends on: resumable ranged requests, MD5 verification that deletes
a corrupt file instead of leaving it, a byte budget, and a dry run that downloads nothing.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_dataset.py"
_SPEC = importlib.util.spec_from_file_location("download_dataset", _SCRIPT)
assert _SPEC and _SPEC.loader
download_dataset = importlib.util.module_from_spec(_SPEC)
sys.modules["download_dataset"] = download_dataset
_SPEC.loader.exec_module(download_dataset)

PAYLOAD = bytes(range(256)) * 64
MD5 = hashlib.md5(PAYLOAD).hexdigest()


class Recorder:
    def __init__(self, *, payload: bytes = PAYLOAD, md5: str = MD5) -> None:
        self.payload = payload
        self.md5 = md5
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if "/api/records/" in url:
            return httpx.Response(
                200,
                json={
                    "files": [
                        {
                            "key": "part.7z",
                            "size": len(self.payload),
                            "checksum": f"md5:{self.md5}",
                            "links": {"self": "https://zenodo.example/files/part.7z"},
                        }
                    ]
                },
            )
        range_header = request.headers.get("range", "")
        if range_header.startswith("bytes="):
            start = int(range_header.removeprefix("bytes=").split("-")[0])
            return httpx.Response(
                206,
                content=self.payload[start:],
                headers={
                    "content-range": f"bytes {start}-{len(self.payload) - 1}/{len(self.payload)}"
                },
            )
        return httpx.Response(200, content=self.payload)


@pytest.fixture
def mocked(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    transport = httpx.MockTransport(recorder)
    real_get, real_stream = httpx.get, httpx.stream

    def fake_get(url, **kwargs):
        kwargs.pop("follow_redirects", None)
        kwargs.pop("timeout", None)
        with httpx.Client(transport=transport) as client:
            return client.get(url, **kwargs)

    def fake_stream(method, url, **kwargs):
        kwargs.pop("follow_redirects", None)
        kwargs.pop("timeout", None)
        client = httpx.Client(transport=transport)
        return client.stream(method, url, **kwargs)

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "stream", fake_stream)
    yield recorder
    monkeypatch.setattr(httpx, "get", real_get)
    monkeypatch.setattr(httpx, "stream", real_stream)


def test_the_record_ids_are_the_confirmed_ones() -> None:
    assert download_dataset.PARTS["I"]["record"] == "8346860"
    assert download_dataset.PARTS["II"]["record"] == "8253899"
    assert download_dataset.PARTS["III"]["record"] == "13761290"
    # Part III is the default: 9.86 GB, not 96.5 GB.
    assert download_dataset.DEFAULT_PARTS == ("III",)


def test_listing_reports_size_and_md5(mocked: Recorder) -> None:
    files = download_dataset.list_files("III")
    assert len(files) == 1
    assert files[0].size == len(PAYLOAD)
    assert files[0].md5 == MD5
    assert files[0].to_dict()["size_gb"] == round(len(PAYLOAD) / 1e9, 3)


def test_a_dry_run_downloads_nothing(
    mocked: Recorder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert download_dataset.main(["--dry-run", "--dest", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "III" in report["parts"]
    assert list(tmp_path.iterdir()) == []
    assert not any("files/part.7z" in str(r.url) for r in mocked.requests)


def test_a_complete_download_is_verified_against_the_published_md5(
    mocked: Recorder, tmp_path: Path
) -> None:
    remote = download_dataset.list_files("III")[0]
    path, complete = download_dataset.download(remote, tmp_path)
    assert complete is True
    assert path.read_bytes() == PAYLOAD
    assert download_dataset.md5_of(path) == MD5


def test_a_partial_file_resumes_with_a_range_header(mocked: Recorder, tmp_path: Path) -> None:
    remote = download_dataset.list_files("III")[0]
    partial = tmp_path / remote.key
    partial.write_bytes(PAYLOAD[:5000])

    path, complete = download_dataset.download(remote, tmp_path)
    assert complete is True
    assert path.read_bytes() == PAYLOAD
    assert any(r.headers.get("range") == "bytes=5000-" for r in mocked.requests)


def test_an_already_complete_file_is_not_downloaded_again(mocked: Recorder, tmp_path: Path) -> None:
    remote = download_dataset.list_files("III")[0]
    (tmp_path / remote.key).write_bytes(PAYLOAD)
    before = len(mocked.requests)
    _, complete = download_dataset.download(remote, tmp_path)
    assert complete is True
    assert len(mocked.requests) == before


def test_a_byte_budget_stops_early_and_leaves_a_resumable_file(
    mocked: Recorder, tmp_path: Path
) -> None:
    remote = download_dataset.list_files("III")[0]
    path, complete = download_dataset.download(remote, tmp_path, max_bytes=1)
    assert complete is False
    assert 0 < path.stat().st_size <= len(PAYLOAD)


def test_a_checksum_mismatch_deletes_the_file_rather_than_keeping_it(
    monkeypatch: pytest.MonkeyPatch, mocked: Recorder, tmp_path: Path
) -> None:
    remote = download_dataset.list_files("III")[0]
    wrong = download_dataset.RemoteFile(
        part=remote.part, key=remote.key, size=remote.size, md5="0" * 32, url=remote.url
    )
    with pytest.raises(SystemExit, match="MD5 mismatch"):
        download_dataset.download(wrong, tmp_path)
    assert not (tmp_path / remote.key).exists()


def test_extraction_without_py7zr_explains_itself(tmp_path: Path) -> None:
    pytest.importorskip("pytest")
    if importlib.util.find_spec("py7zr") is not None:  # pragma: no cover
        pytest.skip("py7zr is installed; the degraded path cannot be observed")
    archive = tmp_path / "part.7z"
    archive.write_bytes(b"not really an archive")
    result = download_dataset.extract(archive, tmp_path / "out", max_images=None)
    assert result["extracted"] is False
    assert "py7zr" in result["reason"]
