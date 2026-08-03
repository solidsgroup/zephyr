from zephyr_server.metadata import parse_metadata, status_from_metadata


def test_parse_metadata_preserves_raw_sections() -> None:
    parsed = parse_metadata("# MESH\nHASH = a1b2\nn_cell = 64 64\nStatus = running\n")
    assert parsed.values["HASH"] == "a1b2"
    assert parsed.values["n_cell"] == "64 64"
    assert parsed.sections["Mesh"] == ["HASH", "n_cell", "Status"]
    assert len(parsed.digest) == 64


def test_status_and_progress_are_normalized() -> None:
    assert status_from_metadata({"Status": "Complete", "Progress": "99.8%"}) == (
        "completed",
        100,
    )
