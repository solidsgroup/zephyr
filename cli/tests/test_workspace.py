from pathlib import Path

import pytest

from zephyr_cli.main import require_alamo_hash, safe_destination


def test_alamo_hash_comes_from_metadata(tmp_path: Path) -> None:
    (tmp_path / "metadata").write_text("Status = Running\nHASH = run-hash\n")

    assert require_alamo_hash(tmp_path) == "run-hash"


def test_alamo_hash_is_required(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="No HASH"):
        require_alamo_hash(tmp_path)


def test_safe_destination_rejects_parent(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        safe_destination(tmp_path, "../secret")
