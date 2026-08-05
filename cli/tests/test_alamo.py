import argparse
from pathlib import Path

import pytest

from zephyr_cli import main
from zephyr_cli.alamo import ThermoTail, derived_status, metadata_values
from zephyr_cli.config import Credentials
from zephyr_cli.main import final_watch_status


def test_metadata_values_and_status() -> None:
    values = metadata_values("HASH = abc123\nStatus: complete\nProgress = 100%\n")
    assert values["HASH"] == "abc123"
    assert derived_status(values) == ("completed", 100)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Status = Running (42%)\n", ("running", 42)),
        ("Status = Segfault\n", ("failed", None)),
        ("Status = Abort\n", ("failed", None)),
        ("Status = Interrupt\n", ("interrupted", None)),
    ],
)
def test_alamo_terminal_statuses(raw: str, expected: tuple[str, int | None]) -> None:
    assert derived_status(metadata_values(raw)) == expected


def test_thermo_tail_reads_only_appended_rows(tmp_path: Path) -> None:
    path = tmp_path / "thermo.dat"
    path.write_text("step time temperature\n0 0.0 300\n", encoding="utf-8")
    tail = ThermoTail(path)
    first = tail.poll()
    assert first[0]["columns"] == ["step", "time", "temperature"]
    assert first[0]["rows"][0]["values"]["temperature"] == 300.0
    tail.ack()

    with path.open("a", encoding="utf-8") as stream:
        stream.write("1 0.1 310\n")
    second = tail.poll()
    assert len(second[0]["rows"]) == 1
    assert second[0]["rows"][0]["sequence"] == 1


def test_thermo_tail_keeps_unacknowledged_batch(tmp_path: Path) -> None:
    path = tmp_path / "thermo.dat"
    path.write_text("step value\n0 2.0\n", encoding="utf-8")
    tail = ThermoTail(path)
    first = tail.poll()
    assert tail.poll() == first
    tail.ack()
    assert tail.poll() == []


def test_final_watch_status_uses_latest_metadata(tmp_path: Path) -> None:
    (tmp_path / "metadata").write_text("Status: complete\n", encoding="utf-8")

    assert final_watch_status(tmp_path, "running") == "completed"


def test_final_watch_status_marks_disappeared_process_interrupted(tmp_path: Path) -> None:
    (tmp_path / "metadata").write_text("Status: running\n", encoding="utf-8")

    assert final_watch_status(tmp_path, "running") == "interrupted"


def test_scheduler_context_captures_slurm_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in {
        "SLURM_JOB_ID",
        "PBS_JOBID",
        "LSB_JOBID",
        "JOB_ID",
        *main.SLURM_DETAIL_ENVIRONMENT.values(),
    }:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("SLURM_JOB_ID", "481516")
    monkeypatch.setenv("SLURM_JOB_PARTITION", "gpu-a100")
    monkeypatch.setenv("SLURM_JOB_NODELIST", "compute-[041-042]")
    monkeypatch.setenv("SLURM_JOB_NUM_NODES", "2")
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "16")
    monkeypatch.setenv("SLURM_GPUS_ON_NODE", "a100:2")
    monkeypatch.setenv("SLURM_SUBMIT_DIR", "/work/alamo")

    system, job_id, details = main.scheduler_context()

    assert system == "slurm"
    assert job_id == "481516"
    assert details == {
        "cpus_per_task": "16",
        "gpus_on_node": "a100:2",
        "node_count": "2",
        "node_list": "compute-[041-042]",
        "partition": "gpu-a100",
        "submit_directory": "/work/alamo",
    }


def test_import_directory_posts_scheduler_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "metadata").write_text("HASH = slurm-run\n", encoding="utf-8")
    requests: list[tuple[str, str, object | None]] = []

    class FakeClient:
        def request(
            self,
            method: str,
            path: str,
            payload: object | None = None,
            query: object | None = None,
        ) -> dict[str, object]:
            assert query is None
            requests.append((method, path, payload))
            if (method, path) == ("POST", "/runs"):
                return {"id": "run-id", "alamo_hash": "slurm-run"}
            return {}

    monkeypatch.setattr(
        main,
        "scheduler_context",
        lambda: (
            "slurm",
            "481516",
            {"partition": "gpu-a100", "node_list": "compute-041"},
        ),
    )

    main.import_directory(FakeClient(), tmp_path)

    payload = requests[0][2]
    assert isinstance(payload, dict)
    assert payload["scheduler_job_id"] == "481516"
    assert payload["scheduler_system"] == "slurm"
    assert payload["scheduler_details"] == {
        "partition": "gpu-a100",
        "node_list": "compute-041",
    }
    assert payload["output_path"] == str(tmp_path)


def test_watcher_that_starts_after_alamo_finishes_posts_completed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "metadata").write_text(
        "HASH = fast-run\nStatus = Complete\n",
        encoding="utf-8",
    )
    requests: list[tuple[str, str, object | None]] = []

    class FakeClient:
        server = "https://zephyr.solids.group"

        def __init__(self, _: Credentials) -> None:
            pass

        def request(
            self,
            method: str,
            path: str,
            payload: object | None = None,
            query: object | None = None,
        ) -> dict[str, object]:
            assert query is None
            requests.append((method, path, payload))
            if (method, path) == ("POST", "/runs"):
                assert isinstance(payload, dict)
                assert payload["status"] == "completed"
                assert payload["output_path"] == str(tmp_path)
                return {"id": "fast-run-id", "alamo_hash": "fast-run"}
            return {}

    monkeypatch.setattr(
        main,
        "credentials_for_server",
        lambda *args, **kwargs: Credentials("https://zephyr.solids.group", "secret"),
    )
    monkeypatch.setattr(main, "Client", FakeClient)

    main.cmd_watch(
        argparse.Namespace(
            directory=str(tmp_path),
            server=None,
            name=None,
            pid=None,
            interval=30.0,
            thermo="thermo.dat",
        )
    )

    assert not (tmp_path / ".zephyr.json").exists()
    terminal_heartbeats = [
        payload
        for method, path, payload in requests
        if method == "POST" and path.endswith("/heartbeat")
    ]
    assert terminal_heartbeats
    assert isinstance(terminal_heartbeats[-1], dict)
    assert terminal_heartbeats[-1]["status"] == "completed"
