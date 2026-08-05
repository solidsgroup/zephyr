import hashlib
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from zephyr_server.db import SessionLocal
from zephyr_server.main import app
from zephyr_server.models import Run

pytestmark = pytest.mark.asyncio


async def test_run_lifecycle_and_public_project() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            login = await client.post("/api/v1/auth/dev-login")
            assert login.status_code == 200
            me = await client.get("/api/v1/auth/me")
            csrf = me.json()["csrf_token"]
            headers = {"X-CSRF-Token": csrf}
            metadata_text = (
                "HASH = abc123\nStatus = running\nProgress = 25\n"
                "SLURM_JOB_ID = 481516\n"
                "SLURM_JOB_NAME = rm-gpu-study\n"
                "SLURM_CLUSTER_NAME = stampede3\n"
                "SLURM_JOB_PARTITION = gpu-a100\n"
                "SLURM_JOB_NUM_NODES = 2\n"
                "SLURM_JOB_NODELIST = compute-[041-042]\n"
                "SLURM_NTASKS = 32\n"
                "SLURM_JOB_GPUS = 0,1,2,3\n"
                "SLURM_SUBMIT_DIR = /work/alamo\n"
                "plot_file = output.481516\n"
            )

            created = await client.post(
                "/api/v1/runs",
                json={
                    "name": "Richtmyer-Meshkov",
                    "status": "running",
                    "scheduler_job_id": "481516",
                    "scheduler_system": "slurm",
                    "scheduler_details": {
                        "partition": "gpu-a100",
                        "node_list": "compute-[041-042]",
                        "node_count": "2",
                        "gpus_on_node": "a100:2",
                        "submit_directory": "/work/alamo",
                    },
                    "output_path": "/work/alamo/output.481516",
                },
                headers=headers,
            )
            assert created.status_code == 201
            run_id = created.json()["id"]
            assert created.json()["scheduler_details"]["partition"] == "gpu-a100"
            assert created.json()["output_path"] == "/work/alamo/output.481516"

            metadata = await client.put(
                f"/api/v1/runs/{run_id}/metadata",
                json={"raw_text": metadata_text},
                headers=headers,
            )
            assert metadata.json()["values"]["HASH"] == "abc123"

            # Recreate a legacy row that retained metadata but not scheduler columns.
            async with SessionLocal() as db:
                legacy_run = await db.get(Run, uuid.UUID(run_id))
                assert legacy_run is not None
                legacy_run.scheduler_details = {}
                legacy_run.output_path = None
                await db.commit()
            listed = await client.get("/api/v1/runs?include_scheduler_metadata=true")
            listed_run = next(run for run in listed.json() if run["id"] == run_id)
            assert listed_run["scheduler_details"]["job_name"] == "rm-gpu-study"
            assert listed_run["scheduler_details"]["node_count"] == "2"
            assert listed_run["scheduler_details"]["task_count"] == "32"
            assert listed_run["scheduler_details"]["job_gpu_ids"] == "0,1,2,3"
            assert listed_run["output_path"] == "/work/alamo/output.481516"

            output = await client.put(
                f"/api/v1/runs/{run_id}/output",
                json={
                    "stdout": "step 1 complete\n",
                    "stdout_truncated": False,
                    "git_diff": "diff --git a/a.cpp b/a.cpp\n",
                    "git_diff_truncated": False,
                },
                headers=headers,
            )
            assert output.status_code == 200
            assert output.json()["stdout"] == "step 1 complete\n"
            assert output.json()["stdout_digest"] == hashlib.sha256(
                b"step 1 complete\n"
            ).hexdigest()

            sync_state = await client.post(
                "/api/v1/runs/sync-state",
                json={"hashes": ["abc123", "not-owned"]},
                headers=headers,
            )
            assert sync_state.status_code == 200
            assert len(sync_state.json()) == 1
            assert sync_state.json()[0]["alamo_hash"] == "abc123"
            assert sync_state.json()[0]["metadata_digest"] == hashlib.sha256(
                metadata_text.encode()
            ).hexdigest()
            assert sync_state.json()[0]["stdout_digest"] == output.json()["stdout_digest"]

            thermo = await client.post(
                f"/api/v1/runs/{run_id}/thermo",
                json={
                    "segment": 0,
                    "columns": ["time", "temperature"],
                    "rows": [
                        {"sequence": 0, "values": {"time": 0.0, "temperature": 300.0}},
                        {"sequence": 1, "values": {"time": 0.1, "temperature": 305.0}},
                    ],
                },
                headers=headers,
            )
            assert thermo.json() == {"accepted": 2, "duplicates": 0}

            heartbeat = await client.post(
                f"/api/v1/runs/{run_id}/heartbeat",
                json={"sequence": 1, "status": "running", "progress": 25},
                headers=headers,
            )
            assert heartbeat.json()["effective_status"] == "running"

            project = await client.post(
                "/api/v1/projects",
                json={"slug": "rm-study", "name": "RM Study", "visibility": "public"},
                headers=headers,
            )
            assert project.status_code == 201
            project_id = project.json()["id"]
            added = await client.post(
                f"/api/v1/projects/{project_id}/runs",
                json={"run_id": run_id},
                headers=headers,
            )
            assert added.status_code == 204

            public = await client.get("/api/v1/public/projects/rm-study")
            assert public.status_code == 200
            assert public.json()["runs"][0]["id"] == run_id

            detail = await client.get(f"/api/v1/runs/{run_id}")
            assert detail.json()["run"]["scheduler_details"]["plot_file"] == "output.481516"
            assert detail.json()["run"]["output_path"] == "/work/alamo/output.481516"
            assert detail.json()["thermo"][0]["rows"][1]["values"]["temperature"] == 305.0
            assert detail.json()["output"]["git_diff"].startswith("diff --git")

            deleted_project = await client.delete(f"/api/v1/projects/{project_id}", headers=headers)
            assert deleted_project.status_code == 204
            assert (await client.get("/api/v1/public/projects/rm-study")).status_code == 404

            deleted_run = await client.delete(f"/api/v1/runs/{run_id}", headers=headers)
            assert deleted_run.status_code == 204
            assert (await client.get(f"/api/v1/runs/{run_id}")).status_code == 404
