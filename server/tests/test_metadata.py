from zephyr_server.metadata import (
    parse_metadata,
    slurm_context_from_metadata,
    status_from_metadata,
)


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


def test_slurm_context_is_recovered_from_alamo_metadata() -> None:
    job_id, details = slurm_context_from_metadata(
        {
            "SLURM_JOB_ID": "11930715",
            "SLURM_JOB_NAME": "lm3d-30mw-full-normal",
            "SLURM_CLUSTER_NAME": "nova",
            "SLURM_JOB_PARTITION": "nova",
            "SLURM_JOB_NUM_NODES": "1",
            "SLURM_JOB_NODELIST": "nova23-amp-9",
            "SLURM_NTASKS": "4",
            "SLURM_JOB_GPUS": "0,1,2,3",
            "SLURM_SUBMIT_DIR": "/work/brunnels/alamo",
            "plot_file": "output.11930715",
        }
    )

    assert job_id == "11930715"
    assert details == {
        "cluster": "nova",
        "job_gpu_ids": "0,1,2,3",
        "job_name": "lm3d-30mw-full-normal",
        "node_count": "1",
        "node_list": "nova23-amp-9",
        "partition": "nova",
        "plot_file": "output.11930715",
        "submit_directory": "/work/brunnels/alamo",
        "task_count": "4",
    }
