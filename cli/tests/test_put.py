import argparse
from pathlib import Path
from typing import Any

import pytest

from zephyr_cli import main


class FakeArtifactClient:
    server = "https://zephyr.example"

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, object | None, object | None]] = []

    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        query: object | None = None,
    ) -> Any:
        self.requests.append((method, path, payload, query))
        if (method, path) == ("GET", "/runs"):
            alamo_hash = dict(query or [])["search"]
            return [{"id": f"id-{alamo_hash}", "alamo_hash": alamo_hash}]
        if path.endswith("/artifacts/initiate"):
            return {"already_present": True}
        if path.endswith("/artifacts/complete"):
            assert isinstance(payload, dict)
            return {"sha256": payload["sha256"], "path": payload["path"], "version": 1}
        return {}

    def upload_file(self, *_: object) -> None:
        raise AssertionError("deduplicated test artifacts should not be uploaded")


def write_run(directory: Path, alamo_hash: str, filename: str) -> Path:
    directory.mkdir(parents=True)
    (directory / "metadata").write_text(
        f"HASH = {alamo_hash}\nStatus = Complete\n",
        encoding="utf-8",
    )
    artifact = directory / filename
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"artifact")
    return artifact


def test_put_uses_metadata_beside_each_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = write_run(tmp_path / "output-a", "hash-a", "first.png")
    second = write_run(tmp_path / "output-b", "hash-b", "second.png")
    client = FakeArtifactClient()
    monkeypatch.setattr(main, "configured_client", lambda: client)

    main.cmd_put(
        argparse.Namespace(
            paths=[str(first), str(second)],
            directory=None,
        )
    )

    completions = [
        (path, payload)
        for method, path, payload, _ in client.requests
        if method == "POST" and path.endswith("/artifacts/complete")
    ]
    assert [path for path, _ in completions] == [
        "/runs/id-hash-a/artifacts/complete",
        "/runs/id-hash-b/artifacts/complete",
    ]
    assert [payload["path"] for _, payload in completions if isinstance(payload, dict)] == [
        "first.png",
        "second.png",
    ]
    output = capsys.readouterr().out
    assert "HASH hash-a" in output
    assert "HASH hash-b" in output
    locations = [
        payload
        for method, path, payload, _ in client.requests
        if method == "PUT" and path.endswith("/copies")
    ]
    assert len(locations) == 2
    assert {payload["last_action"] for payload in locations if isinstance(payload, dict)} == {
        "put"
    }


def test_put_directory_option_overrides_target_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = write_run(tmp_path / "output", "hash-root", "images/result.png")
    client = FakeArtifactClient()
    monkeypatch.setattr(main, "configured_client", lambda: client)

    main.cmd_put(
        argparse.Namespace(
            paths=[str(artifact)],
            directory=str(tmp_path / "output"),
        )
    )

    completion = next(
        payload
        for method, path, payload, _ in client.requests
        if method == "POST" and path.endswith("/artifacts/complete")
    )
    assert isinstance(completion, dict)
    assert completion["path"] == "images/result.png"
