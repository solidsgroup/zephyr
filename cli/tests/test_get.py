import argparse
from pathlib import Path
from typing import Any

import pytest

from zephyr_cli import main


def run_record(
    run_id: str,
    output_path: str,
    *,
    alamo_hash: str = "hash-a",
    name: str = "Alamo run",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "alamo_hash": alamo_hash,
        "name": name,
        "status": "completed",
        "effective_status": "completed",
        "output_path": output_path,
        "scheduler_details": {"cluster": "stampede3"},
        "host": "node-1",
        "updated_at": "2026-08-07T12:34:56+00:00",
    }


class FakeGetClient:
    def __init__(
        self,
        searched: list[dict[str, Any]],
        recent: list[dict[str, Any]] | None = None,
    ) -> None:
        self.searched = searched
        self.recent = recent if recent is not None else searched
        self.requests: list[tuple[str, str, object | None]] = []

    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        query: list[tuple[str, str]] | None = None,
    ) -> Any:
        self.requests.append((method, path, query))
        if (method, path) == ("GET", "/runs"):
            return self.searched if "search" in dict(query or []) else self.recent
        if method == "PUT" and path.endswith("/copies"):
            return payload
        if method == "GET" and path.endswith("/artifacts"):
            return []
        if method == "GET" and path.startswith("/runs/"):
            run_id = path.split("/")[2]
            run = next(
                item for item in self.searched + self.recent if str(item["id"]) == run_id
            )
            return {"run": run, "metadata": None, "thermo": []}
        raise AssertionError(f"Unexpected request: {method} {path}")


def test_find_run_chooses_between_duplicate_output_directory_names() -> None:
    first = run_record("first", "/scratch/one/output.42", alamo_hash="hash-first")
    second = run_record("second", "/scratch/two/output.42", alamo_hash="hash-second")
    client = FakeGetClient([first, second])

    selected = main.find_run(
        client,
        "output.42",
        interactive=True,
        prompt=lambda _: "2",
    )

    assert selected["id"] == "second"


def test_find_run_uses_hash_before_a_matching_directory_name() -> None:
    hash_match = run_record("hash", "/scratch/unrelated", alamo_hash="output.42")
    directory_match = run_record("directory", "/scratch/output.42", alamo_hash="other")

    selected = main.find_run(FakeGetClient([directory_match, hash_match]), "output.42")

    assert selected["id"] == "hash"


def test_find_run_uses_uid_directly() -> None:
    run_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    client = FakeGetClient([run_record(run_id, "/scratch/output.42")])

    selected = main.find_run(client, run_id)

    assert selected["id"] == run_id
    assert client.requests == [("GET", f"/runs/{run_id}", None)]


def test_find_run_falls_back_to_plot_file_for_legacy_records() -> None:
    legacy = run_record("legacy", "")
    legacy["output_path"] = None
    legacy["scheduler_details"]["plot_file"] = "results/output.77"

    selected = main.find_run(FakeGetClient([], recent=[legacy]), "output.77")

    assert selected["id"] == "legacy"
    assert main.preferred_run_directory(selected) == "output.77"


def test_ambiguous_noninteractive_lookup_lists_uids() -> None:
    matches = [
        run_record("first", "/one/output.42"),
        run_record("second", "/two/output.42"),
    ]

    with pytest.raises(RuntimeError) as raised:
        main.choose_run(matches, "output.42", interactive=False)

    assert "UID first" in str(raised.value)
    assert "UID second" in str(raised.value)


def test_existing_destination_can_take_next_available_name(tmp_path: Path) -> None:
    destination = tmp_path / "output.42"
    destination.mkdir()
    (tmp_path / "output.42-2").mkdir()

    selected, overwrite = main.prepare_restore_directory(
        destination,
        rename=True,
    )

    assert selected == tmp_path / "output.42-3"
    assert overwrite is False


def test_existing_destination_prompts_before_overwrite(tmp_path: Path) -> None:
    destination = tmp_path / "output.42"
    destination.mkdir()

    selected, overwrite = main.prepare_restore_directory(
        destination,
        interactive=True,
        prompt=lambda _: "3",
    )

    assert selected == destination
    assert overwrite is True


def test_existing_destination_explains_noninteractive_options(tmp_path: Path) -> None:
    destination = tmp_path / "output.42"
    destination.mkdir()

    with pytest.raises(RuntimeError, match="--output PATH.*--rename.*--overwrite"):
        main.prepare_restore_directory(destination, interactive=False)


def test_get_restores_to_recorded_output_directory_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = run_record("run-id", "/remote/scratch/output.42", name="A descriptive title")
    client = FakeGetClient([run])
    monkeypatch.setattr(main, "configured_client", lambda: client)
    monkeypatch.chdir(tmp_path)

    main.cmd_get(
        argparse.Namespace(
            reference="output.42",
            output=None,
            overwrite=False,
            rename=False,
        )
    )

    assert (tmp_path / "output.42" / "zephyr-run.json").is_file()
    assert not (tmp_path / "A descriptive title").exists()
    copy_update = next(
        request
        for request in client.requests
        if request[0] == "PUT" and request[1].endswith("/copies")
    )
    assert copy_update[1] == "/runs/run-id/copies"
