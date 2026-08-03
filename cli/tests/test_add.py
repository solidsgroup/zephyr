import argparse
import io
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from zephyr_cli import main


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_color_respects_terminal_and_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = TtyBuffer()
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert main.color_enabled(stream)

    monkeypatch.setenv("NO_COLOR", "1")
    assert not main.color_enabled(stream)


def test_discover_run_directories_recurses(tmp_path: Path) -> None:
    root_run = tmp_path / "run-1" / "metadata"
    nested_run = tmp_path / "campaign" / "run-2" / "metadata"
    root_run.parent.mkdir()
    root_run.write_text("HASH = root\n", encoding="utf-8")
    nested_run.parent.mkdir(parents=True)
    nested_run.write_text("HASH = nested\n", encoding="utf-8")

    root, directories = main.discover_run_directories(tmp_path)

    assert root == tmp_path.resolve()
    assert directories == sorted(
        [root_run.parent.resolve(), nested_run.parent.resolve()],
        key=str,
    )


def test_discover_run_directories_stops_below_run_metadata(tmp_path: Path) -> None:
    run = tmp_path / "output"
    nested = run / "restart-copy" / "metadata"
    nested.parent.mkdir(parents=True)
    (run / "metadata").write_text("HASH = root\n", encoding="utf-8")
    nested.write_text("HASH = nested\n", encoding="utf-8")

    _, directories = main.discover_run_directories(tmp_path)

    assert directories == [run.resolve()]


def test_discover_run_directories_prunes_alamo_source_and_environment_trees(
    tmp_path: Path,
) -> None:
    (tmp_path / "configure").write_text("", encoding="utf-8")
    hidden = tmp_path / "ext" / "dependency" / "metadata"
    environment = tmp_path / ".venv" / "package" / "metadata"
    visible = tmp_path / "tests" / "case" / "output" / "metadata"
    for metadata in (hidden, environment, visible):
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text("HASH = test\n", encoding="utf-8")
    (tmp_path / "src").mkdir()

    _, directories = main.discover_run_directories(tmp_path)

    assert directories == [visible.parent.resolve()]


def test_discover_run_directories_prunes_boxlib_cell_and_node_trees(tmp_path: Path) -> None:
    visible = tmp_path / "campaign" / "run-2" / "metadata"
    cell_metadata = tmp_path / "00000cell" / "Level_0" / "metadata"
    node_metadata = tmp_path / "123456node" / "Level_4" / "metadata"
    similar_name = tmp_path / "00000cell-results" / "metadata"
    for metadata in (visible, cell_metadata, node_metadata, similar_name):
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text("HASH = test\n", encoding="utf-8")

    _, directories = main.discover_run_directories(tmp_path)

    assert directories == sorted(
        [visible.parent.resolve(), similar_name.parent.resolve()],
        key=str,
    )


def test_discover_run_directories_does_not_scan_explicit_boxlib_tree(tmp_path: Path) -> None:
    data_tree = tmp_path / "00400cell"
    metadata = data_tree / "Level_0" / "metadata"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("HASH = hidden\n", encoding="utf-8")

    root, directories = main.discover_run_directories(data_tree)

    assert root == data_tree.resolve()
    assert directories == []


def test_expand_add_paths_supports_wildcards_and_deduplicates(tmp_path: Path) -> None:
    first = tmp_path / "output-a"
    second = tmp_path / "output-b"
    first.mkdir()
    second.mkdir()

    matches = main.expand_add_paths(
        [str(tmp_path / "output*"), str(first)],
    )

    assert matches == [first.resolve(), second.resolve()]


def test_add_parser_accepts_shell_expanded_paths() -> None:
    args = main.parser().parse_args(["add", "output-a", "output-b"])

    assert args.paths == ["output-a", "output-b"]


def test_add_reports_added_updated_and_skipped_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    new_run = tmp_path / "new-run"
    old_run = tmp_path / "old-run"
    invalid_run = tmp_path / "missing-hash"
    for directory in (new_run, old_run, invalid_run):
        directory.mkdir()
    (new_run / "metadata").write_text(
        "Git_commit_hash = abc123\nHASH = hash-new\nStatus = Complete\n",
        encoding="utf-8",
    )
    (new_run / "thermo.dat").write_text("step value\n0 2.5\n", encoding="utf-8")
    (new_run / "out.log").write_text("ALAMO output\n", encoding="utf-8")
    (new_run / "diff.patch").write_text("diff --git a/a.cpp b/a.cpp\n", encoding="utf-8")
    (old_run / "metadata").write_text(
        "Git_commit_hash = def456\nHASH = hash-old\nStatus = Segfault\n",
        encoding="utf-8",
    )
    (invalid_run / "metadata").write_text("Status = Complete\n", encoding="utf-8")
    requests: list[tuple[str, str, object | None, object | None]] = []

    class FakeClient:
        server = "https://zephyr.example"

        def request(
            self,
            method: str,
            path: str,
            payload: object | None = None,
            query: object | None = None,
        ) -> Any:
            requests.append((method, path, payload, query))
            if (method, path) == ("POST", "/runs/sync-state"):
                assert payload == {"hashes": ["hash-new", "hash-old"]}
                return [
                    {
                        "id": "old-id",
                        "alamo_hash": "hash-old",
                        "status": "starting",
                        "progress": None,
                        "metadata_digest": None,
                        "stdout_digest": None,
                        "git_diff_digest": None,
                        "thermo_digest": None,
                    }
                ]
            if (method, path) == ("POST", "/runs"):
                assert isinstance(payload, dict)
                alamo_hash = str(payload["alamo_hash"])
                return {
                    "id": "old-id" if alamo_hash == "hash-old" else "new-id",
                    "alamo_hash": alamo_hash,
                    "name": payload["name"],
                }
            return {}

    monkeypatch.setattr(main, "configured_client", lambda: FakeClient())

    main.cmd_add(argparse.Namespace(paths=[str(tmp_path)]))

    output = capsys.readouterr().out
    assert "ADDED" in output
    assert "UPDATED" in output
    assert "SKIPPED" in output
    assert "hash-new" in output
    assert "hash-old" in output
    assert "1 added" in output
    assert "1 updated" in output
    assert "1 skipped" in output
    assert "\033[" not in output
    assert not list(tmp_path.rglob(".zephyr.json"))

    created_statuses = {
        payload["alamo_hash"]: payload["status"]
        for method, path, payload, _ in requests
        if (method, path) == ("POST", "/runs") and isinstance(payload, dict)
    }
    assert created_statuses == {"hash-new": "completed"}
    assert any(
        method == "POST" and path == "/runs/new-id/thermo"
        for method, path, _, _ in requests
    )
    posted_output = next(
        payload
        for method, path, payload, _ in requests
        if method == "PUT" and path == "/runs/new-id/output"
    )
    assert posted_output == {
        "stdout": "ALAMO output\n",
        "stdout_truncated": False,
        "git_diff": "diff --git a/a.cpp b/a.cpp\n",
        "git_diff_truncated": False,
    }
    assert sum(
        method == "POST" and path == "/runs/sync-state"
        for method, path, _, _ in requests
    ) == 1
    assert sum(
        method == "PUT" and path == "/runs/new-id/metadata"
        for method, path, _, _ in requests
    ) == 1


def test_add_syncs_multiple_runs_concurrently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for index in range(4):
        directory = tmp_path / f"run-{index}"
        directory.mkdir()
        (directory / "metadata").write_text(
            f"HASH = hash-{index}\nStatus = Complete\n",
            encoding="utf-8",
        )
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    class SlowClient:
        def request(
            self,
            method: str,
            path: str,
            payload: object | None = None,
            query: object | None = None,
        ) -> Any:
            nonlocal active, maximum_active
            if (method, path) == ("POST", "/runs/sync-state"):
                return []
            if (method, path) == ("POST", "/runs"):
                assert isinstance(payload, dict)
                with lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                time.sleep(0.03)
                with lock:
                    active -= 1
                return {
                    "id": f"id-{payload['alamo_hash']}",
                    "alamo_hash": payload["alamo_hash"],
                    "name": payload["name"],
                }
            return {}

    monkeypatch.setattr(main, "configured_client", SlowClient)

    main.cmd_add(argparse.Namespace(paths=[str(tmp_path)]))

    assert maximum_active >= 2
    assert "4 concurrent connections" in capsys.readouterr().out


def test_add_skips_network_writes_for_current_completed_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "run"
    directory.mkdir()
    metadata = "HASH = hash-current\nStatus = Complete\n"
    (directory / "metadata").write_text(metadata, encoding="utf-8")
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
                return [
                    {
                        "id": "run-id",
                        "alamo_hash": "hash-current",
                        "status": "completed",
                        "progress": None,
                        "metadata_digest": main.metadata_digest(metadata),
                        "stdout_digest": None,
                        "git_diff_digest": None,
                        "thermo_digest": None,
                    }
                ]
            raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(main, "configured_client", FakeClient)

    main.cmd_add(argparse.Namespace(paths=[str(tmp_path)]))

    assert requests == [
        ("POST", "/runs/sync-state", {"hashes": ["hash-current"]})
    ]
    output = capsys.readouterr().out
    assert "CURRENT" in output
    assert "already current" in output
    assert "1 current" in output


def test_git_repository_url_normalizes_github_ssh_remote(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "add",
            "origin",
            "git@github.com:solidsgroup/alamo.git",
        ],
        check=True,
    )

    assert main.git_repository_url(tmp_path) == "https://github.com/solidsgroup/alamo"


def test_captured_text_keeps_stdout_tail_and_diff_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "output.txt"
    path.write_text("0123456789", encoding="utf-8")
    monkeypatch.setattr(main, "MAX_CAPTURED_TEXT_BYTES", 5)

    assert main.captured_text(path, keep_tail=True) == ("56789", True)
    assert main.captured_text(path, keep_tail=False) == ("01234", True)
