import json
from pathlib import Path

import pytest

from zephyr_cli.main import safe_destination
from zephyr_cli.workspace import RunMarker


def test_marker_round_trip(tmp_path: Path) -> None:
    marker = RunMarker(run_id="run-id", server="https://zephyr.example")
    marker.save(tmp_path)
    assert RunMarker.load(tmp_path) == marker
    assert json.loads((tmp_path / ".zephyr.json").read_text())["protocol"] == "1.0"


def test_safe_destination_rejects_parent(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        safe_destination(tmp_path, "../secret")
