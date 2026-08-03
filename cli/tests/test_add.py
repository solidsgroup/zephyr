import argparse
import io
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
    root_run = tmp_path / "metadata"
    nested_run = tmp_path / "campaign" / "run-2" / "metadata"
    root_run.write_text("HASH = root\n", encoding="utf-8")
    nested_run.parent.mkdir(parents=True)
    nested_run.write_text("HASH = nested\n", encoding="utf-8")

    root, directories = main.discover_run_directories(tmp_path)

    assert root == tmp_path.resolve()
    assert directories == sorted(
        [tmp_path.resolve(), nested_run.parent.resolve()],
        key=str,
    )


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
            if (method, path) == ("GET", "/auth/me"):
                return {"user": {"id": "owner-1"}}
            if (method, path) == ("GET", "/runs"):
                search = dict(query or []).get("search")
                if search == "hash-old":
                    return [{"id": "old-id", "alamo_hash": "hash-old", "owner_id": "owner-1"}]
                return []
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
    assert created_statuses == {"hash-new": "completed", "hash-old": "failed"}
    assert any(
        method == "POST" and path == "/runs/new-id/thermo"
        for method, path, _, _ in requests
    )
