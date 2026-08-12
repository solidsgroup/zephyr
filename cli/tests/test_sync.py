import argparse
from pathlib import Path
from typing import Any

import pytest

from zephyr_cli import main


def write_copy(directory: Path, alamo_hash: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metadata").write_text(
        f"HASH = {alamo_hash}\nStatus = Complete\n",
        encoding="utf-8",
    )


def test_directory_inventory_counts_files_and_boxlib_data(tmp_path: Path) -> None:
    write_copy(tmp_path, "hash-one")
    cell = tmp_path / "00000cell" / "Level_0"
    node = tmp_path / "00100node" / "Level_0"
    cell.mkdir(parents=True)
    node.mkdir(parents=True)
    (cell / "Cell_D_00000").write_bytes(b"cell-data")
    (node / "Node_D_00000").write_bytes(b"node-data")

    inventory = main.directory_inventory(tmp_path)

    assert inventory.file_count == 3
    assert inventory.total_size_bytes > 0
    assert inventory.has_cell_data is True
    assert inventory.has_node_data is True


def test_directory_inventory_fingerprint_changes_when_a_file_moves(tmp_path: Path) -> None:
    write_copy(tmp_path, "hash-one")
    original = tmp_path / "old-name.png"
    original.write_bytes(b"same contents")
    before = main.directory_inventory(tmp_path)

    original.rename(tmp_path / "new-name.png")
    after = main.directory_inventory(tmp_path)

    assert before.file_count == after.file_count
    assert before.total_size_bytes == after.total_size_bytes
    assert before.manifest_digest != after.manifest_digest


def test_sync_records_every_copy_even_when_hashes_repeat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = tmp_path / "disk-a" / "output.42"
    second = tmp_path / "disk-b" / "output.42"
    write_copy(first, "same-hash")
    write_copy(second, "same-hash")
    (first / "00000cell").mkdir()
    (second / "preview.png").write_bytes(b"png")
    requests: list[tuple[str, str, object | None]] = []

    class FakeClient:
        def request(
            self,
            method: str,
            path: str,
            payload: object | None = None,
            query: object | None = None,
        ) -> Any:
            requests.append((method, path, payload))
            if (method, path) == ("POST", "/runs/sync-state"):
                assert payload == {"hashes": ["same-hash"]}
                return [{"id": "run-id", "alamo_hash": "same-hash"}]
            if method == "PUT" and path == "/runs/run-id/copies":
                return payload
            raise AssertionError(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(main, "configured_client", FakeClient)

    main.cmd_sync(argparse.Namespace(paths=[str(tmp_path)]))

    locations = [
        payload
        for method, path, payload in requests
        if method == "PUT" and path == "/runs/run-id/copies"
    ]
    assert len(locations) == 2
    assert {payload["path"] for payload in locations if isinstance(payload, dict)} == {
        str(first.resolve()),
        str(second.resolve()),
    }
    assert {payload["last_action"] for payload in locations if isinstance(payload, dict)} == {
        "sync"
    }
    first_payload = next(
        payload
        for payload in locations
        if isinstance(payload, dict) and payload["path"] == str(first.resolve())
    )
    assert first_payload["has_cell_data"] is True


def test_sync_parser_defaults_to_current_directory() -> None:
    args = main.parser().parse_args(["sync"])

    assert args.paths == []
