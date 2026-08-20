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


def test_put_uses_metadata_for_each_target(
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


def test_put_finds_metadata_above_nested_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = write_run(
        tmp_path / "output",
        "hash-root",
        "images/frames/result.png",
    )
    client = FakeArtifactClient()
    monkeypatch.setattr(main, "configured_client", lambda: client)

    main.cmd_put(
        argparse.Namespace(
            paths=[str(artifact)],
            directory=None,
        )
    )

    completion = next(
        payload
        for method, path, payload, _ in client.requests
        if method == "POST" and path.endswith("/artifacts/complete")
    )
    assert isinstance(completion, dict)
    assert completion["path"] == "images/frames/result.png"
    assert any(
        method == "GET"
        and path == "/runs"
        and dict(query or []).get("search") == "hash-root"
        for method, path, _, query in client.requests
    )


def test_put_basename_pattern_traverses_discovered_runs_and_dry_run_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = write_run(tmp_path / "campaign" / "output-a", "hash-a", "frames/first.png")
    second = write_run(tmp_path / "output-b", "hash-b", "second.png")
    write_run(tmp_path / "output-c", "hash-c", "notes.txt")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        main,
        "configured_client",
        lambda: pytest.fail("a put dry run must not configure a client"),
    )

    main.cmd_put(argparse.Namespace(paths=["*.png"], directory=None, dry_run=True))

    output = capsys.readouterr().out
    assert "HASH hash-a" in output
    assert "HASH hash-b" in output
    assert first.relative_to(first.parents[1]).as_posix() in output
    assert second.name in output
    assert "notes.txt" not in output
    assert "2 files across 2 runs; nothing uploaded" in output


def test_transfer_parsers_accept_dry_run() -> None:
    argument_parser = main.parser()

    for command in (
        ["import", "--dry-run"],
        ["add", "--dry-run"],
        ["sync", "--dry-run"],
        ["put", "--dry-run", "*.png"],
        ["get", "--dry-run", "hash"],
    ):
        assert argument_parser.parse_args(command).dry_run is True
