from pathlib import Path

from zephyr_cli.alamo import ThermoTail, derived_status, metadata_values
from zephyr_cli.main import final_watch_status


def test_metadata_values_and_status() -> None:
    values = metadata_values("HASH = abc123\nStatus: complete\nProgress = 100%\n")
    assert values["HASH"] == "abc123"
    assert derived_status(values) == ("completed", 100)


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
