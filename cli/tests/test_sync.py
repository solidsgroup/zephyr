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


def test_shallow_directory_inventory_counts_but_does_not_enter_boxlib_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_copy(tmp_path, "hash-one")
    cell = tmp_path / "00000cell" / "Level_0"
    node = tmp_path / "00100node" / "Level_0"
    cell.mkdir(parents=True)
    node.mkdir(parents=True)
    (cell / "Cell_D_00000").write_bytes(b"cell-data")
    (node / "Node_D_00000").write_bytes(b"node-data")

    scanned: list[Path] = []
    original_scandir = main.os.scandir

    def recording_scandir(path: object):
        scanned.append(Path(path))
        return original_scandir(path)

    monkeypatch.setattr(main.os, "scandir", recording_scandir)
    inventory = main.directory_inventory(tmp_path)

    assert inventory.file_count == 1
    assert inventory.file_count_complete is False
    assert inventory.data_tree_count == 2
    assert inventory.total_size_bytes is None
    assert inventory.has_cell_data is True
    assert inventory.has_node_data is True
    assert cell not in scanned
    assert node not in scanned

    deep = main.directory_inventory(tmp_path, deep=True)
    assert deep.file_count == 3
    assert deep.file_count_complete is True
    assert deep.data_tree_count == 2
    assert deep.total_size_bytes is not None
    assert deep.total_size_bytes > 0


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


def test_fast_inventory_ignores_content_changes_but_deep_inventory_detects_them(
    tmp_path: Path,
) -> None:
    write_copy(tmp_path, "hash-one")
    result = tmp_path / "result.dat"
    result.write_bytes(b"one")
    fast_before = main.directory_inventory(tmp_path)
    deep_before = main.directory_inventory(tmp_path, deep=True)

    result.write_bytes(b"a much larger result")
    fast_after = main.directory_inventory(tmp_path)
    deep_after = main.directory_inventory(tmp_path, deep=True)

    assert fast_before.manifest_digest == fast_after.manifest_digest
    assert deep_before.manifest_digest != deep_after.manifest_digest
    assert deep_before.total_size_bytes != deep_after.total_size_bytes


def test_cached_inventory_reuses_unchanged_directory_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_copy(tmp_path, "hash-one")
    nested = tmp_path / "00000cell" / "Level_0"
    nested.mkdir(parents=True)
    (nested / "Cell_D_00000").write_bytes(b"cell-data")
    cache: dict[str, Any] = {"version": 2, "paths": {}}

    first, first_hit = main.cached_directory_inventory(tmp_path, cache)
    monkeypatch.setattr(
        main,
        "directory_inventory",
        lambda *_args, **_kwargs: pytest.fail("unchanged directories should use cache"),
    )
    second, second_hit = main.cached_directory_inventory(tmp_path, cache)

    assert first_hit is False
    assert second_hit is True
    assert second == first


def test_sync_records_every_copy_even_when_hashes_repeat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
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
            if method == "PUT" and path == "/runs/copies/batch":
                assert isinstance(payload, dict)
                return {"updated": len(payload["copies"])}
            raise AssertionError(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(main, "configured_client", FakeClient)

    main.cmd_sync(argparse.Namespace(paths=[str(tmp_path)], deep=False))

    batch = next(
        payload
        for method, path, payload in requests
        if method == "PUT" and path == "/runs/copies/batch"
    )
    assert isinstance(batch, dict)
    locations = batch["copies"]
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
    assert first_payload["file_count_complete"] is False
    assert first_payload["data_tree_count"] == 1


def test_sync_parser_defaults_to_current_directory() -> None:
    args = main.parser().parse_args(["sync"])

    assert args.paths == []
    assert args.deep is False


def test_sync_dry_run_does_not_contact_server_or_write_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_copy(tmp_path / "output", "hash-one")
    monkeypatch.setattr(
        main,
        "configured_client",
        lambda: pytest.fail("a sync dry run must not configure a client"),
    )
    monkeypatch.setattr(
        main,
        "save_sync_cache",
        lambda _cache: pytest.fail("a sync dry run must not write its cache"),
    )

    main.cmd_sync(argparse.Namespace(paths=[str(tmp_path)], deep=False, dry_run=True))

    output = capsys.readouterr().out
    assert "1 locations would be updated" in output
    assert "no server or cache changes were made" in output


def test_batch_copy_update_falls_back_for_an_older_server() -> None:
    requests: list[tuple[str, str, object | None]] = []

    class OldServerClient:
        def request(
            self,
            method: str,
            path: str,
            payload: object | None = None,
            query: object | None = None,
        ) -> Any:
            requests.append((method, path, payload))
            if path == "/runs/copies/batch":
                raise main.ApiError("Zephyr returned 404: Not Found")
            return payload

    main.batch_update_copy_locations(
        OldServerClient(),
        [
            {
                "run_id": "run-id",
                "site": "cluster",
                "host": "login1",
                "path": "/scratch/output",
                "platform": "Linux",
                "file_count": 3,
                "total_size_bytes": None,
                "has_cell_data": True,
                "has_node_data": False,
                "manifest_digest": "a" * 64,
                "last_action": "sync",
            }
        ],
    )

    assert requests[-1][1] == "/runs/run-id/copies"
    assert isinstance(requests[-1][2], dict)
    assert requests[-1][2]["total_size_bytes"] == 0
