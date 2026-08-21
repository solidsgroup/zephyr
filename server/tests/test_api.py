import hashlib
import uuid
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from zephyr_server.db import SessionLocal
from zephyr_server.main import app
from zephyr_server.models import Run, utcnow

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
            assert created.json()["effective_status"] == "unreachable"
            assert created.json()["scheduler_details"]["partition"] == "gpu-a100"
            assert created.json()["output_path"] == "/work/alamo/output.481516"
            searched = await client.get("/api/v1/runs?search=output.481516")
            assert [run["id"] for run in searched.json()] == [run_id]

            metadata = await client.put(
                f"/api/v1/runs/{run_id}/metadata",
                json={"raw_text": metadata_text},
                headers=headers,
            )
            assert metadata.json()["values"]["HASH"] == "abc123"
            searched_metadata = await client.get(
                "/api/v1/runs", params={"search": "compute-[041-042]"}
            )
            assert run_id in {run["id"] for run in searched_metadata.json()}

            first_copy = await client.put(
                f"/api/v1/runs/{run_id}/copies",
                json={
                    "site": "stampede3",
                    "host": "login1",
                    "path": "/scratch/brunnels/output.481516",
                    "platform": "Linux",
                    "file_count": 1250,
                    "total_size_bytes": 987654321,
                    "has_cell_data": True,
                    "has_node_data": True,
                    "manifest_digest": "a" * 64,
                    "last_action": "sync",
                },
                headers=headers,
            )
            assert first_copy.status_code == 200
            assert first_copy.json()["file_count"] == 1250
            assert first_copy.json()["file_count_complete"] is True
            assert first_copy.json()["data_tree_count"] == 0
            copy_id = first_copy.json()["id"]

            refreshed_copy = await client.put(
                f"/api/v1/runs/{run_id}/copies",
                json={
                    **{
                        key: value
                        for key, value in first_copy.json().items()
                        if key
                        in {
                            "site",
                            "host",
                            "path",
                            "platform",
                            "file_count",
                            "total_size_bytes",
                            "has_cell_data",
                            "has_node_data",
                            "manifest_digest",
                            "last_action",
                        }
                    },
                    "file_count": 1251,
                    "manifest_digest": "b" * 64,
                    "last_action": "put",
                },
                headers=headers,
            )
            assert refreshed_copy.json()["id"] == copy_id
            assert refreshed_copy.json()["file_count"] == 1251
            assert refreshed_copy.json()["last_action"] == "put"

            second_copy = await client.put(
                f"/api/v1/runs/{run_id}/copies",
                json={
                    "site": "workstation",
                    "host": "desktop",
                    "path": "/home/user/output.481516",
                    "platform": "Linux",
                    "file_count": 4,
                    "total_size_bytes": 4096,
                    "has_cell_data": False,
                    "has_node_data": False,
                    "manifest_digest": "c" * 64,
                    "last_action": "get",
                },
                headers=headers,
            )
            assert second_copy.status_code == 200
            batch_copies = await client.put(
                "/api/v1/runs/copies/batch",
                json={
                    "copies": [
                        {
                            "run_id": run_id,
                            "site": "stampede3",
                            "host": "login2",
                            "path": "/scratch/brunnels/output.481516",
                            "platform": "Linux",
                            "file_count": 12,
                            "file_count_complete": False,
                            "data_tree_count": 1248,
                            "total_size_bytes": None,
                            "has_cell_data": True,
                            "has_node_data": True,
                            "manifest_digest": "d" * 64,
                            "last_action": "sync",
                        },
                        {
                            "run_id": run_id,
                            "site": "workstation",
                            "host": "desktop",
                            "path": "/home/user/output.481516",
                            "platform": "Linux",
                            "file_count": 4,
                            "file_count_complete": True,
                            "data_tree_count": 0,
                            "total_size_bytes": None,
                            "has_cell_data": False,
                            "has_node_data": False,
                            "manifest_digest": "e" * 64,
                            "last_action": "sync",
                        },
                    ]
                },
                headers=headers,
            )
            assert batch_copies.status_code == 200
            assert batch_copies.json() == {"updated": 2}
            copies = await client.get(f"/api/v1/runs/{run_id}/copies")
            assert len(copies.json()) == 2
            assert {copy["total_size_bytes"] for copy in copies.json()} == {None}
            shallow_copy = next(copy for copy in copies.json() if copy["site"] == "stampede3")
            assert shallow_copy["file_count_complete"] is False
            assert shallow_copy["data_tree_count"] == 1248

            searched_copy_path = await client.get(
                "/api/v1/runs", params={"search": "/home/user/output.481516"}
            )
            assert run_id in {run["id"] for run in searched_copy_path.json()}
            filtered_site = await client.get("/api/v1/runs", params={"site": "stampede3"})
            assert run_id in {run["id"] for run in filtered_site.json()}
            listed_with_copies = await client.get(
                "/api/v1/runs", params={"has_copies": "true"}
            )
            listed_copy = next(run for run in listed_with_copies.json() if run["id"] == run_id)
            assert listed_copy["copy_count"] == 2
            facets = await client.get("/api/v1/runs/facets")
            assert facets.status_code == 200
            site_counts = {item["site"]: item["run_count"] for item in facets.json()["sites"]}
            assert site_counts["stampede3"] >= 1
            assert site_counts["workstation"] >= 1

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
            assert (
                output.json()["stdout_digest"] == hashlib.sha256(b"step 1 complete\n").hexdigest()
            )

            sync_state = await client.post(
                "/api/v1/runs/sync-state",
                json={"hashes": ["abc123", "not-owned"]},
                headers=headers,
            )
            assert sync_state.status_code == 200
            assert len(sync_state.json()) == 1
            assert sync_state.json()[0]["alamo_hash"] == "abc123"
            assert (
                sync_state.json()[0]["metadata_digest"]
                == hashlib.sha256(metadata_text.encode()).hexdigest()
            )
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

            batch_run = await client.post(
                "/api/v1/runs",
                json={"name": "Batch project run", "alamo_hash": f"batch-{uuid.uuid4()}"},
                headers=headers,
            )
            assert batch_run.status_code == 201
            batch_run_id = batch_run.json()["id"]
            without_copies = await client.get(
                "/api/v1/runs", params={"has_copies": "false"}
            )
            assert batch_run_id in {item["id"] for item in without_copies.json()}
            assert run_id not in {item["id"] for item in without_copies.json()}
            by_copies = await client.get(
                "/api/v1/runs", params={"sort": "copies_desc", "limit": 1000}
            )
            copy_order = [item["id"] for item in by_copies.json()]
            assert copy_order.index(run_id) < copy_order.index(batch_run_id)
            uncategorized = await client.get("/api/v1/runs", params={"uncategorized": "true"})
            assert uncategorized.status_code == 200
            assert batch_run_id in {item["id"] for item in uncategorized.json()}
            editable_projects = await client.get("/api/v1/projects", params={"editable": "true"})
            assert project_id in {item["id"] for item in editable_projects.json()}
            batch_added = await client.post(
                f"/api/v1/projects/{project_id}/runs/batch",
                json={"run_ids": [run_id, batch_run_id]},
                headers=headers,
            )
            assert batch_added.status_code == 200
            assert batch_added.json() == {"added": 1, "already_present": 1}
            uncategorized_after_add = await client.get(
                "/api/v1/runs", params={"uncategorized": "true"}
            )
            assert batch_run_id not in {item["id"] for item in uncategorized_after_add.json()}
            categorized_listing = await client.get("/api/v1/runs")
            categorized_run = next(
                item for item in categorized_listing.json() if item["id"] == batch_run_id
            )
            assert categorized_run["projects"] == [
                {"id": project_id, "slug": "rm-study", "name": "RM Study"}
            ]
            assert all(not item["projects"] for item in uncategorized_after_add.json())
            project_runs = await client.get(f"/api/v1/projects/{project_id}/runs")
            assert {item["id"] for item in project_runs.json()} == {run_id, batch_run_id}
            project_run = next(item for item in project_runs.json() if item["id"] == run_id)
            assert project_run["copy_count"] == 2
            dashboard = await client.get("/api/v1/projects/dashboard")
            assert dashboard.status_code == 200
            dashboard_project = next(
                item for item in dashboard.json() if item["id"] == project_id
            )
            assert dashboard_project["run_count"] == 2
            assert dashboard_project["active_run_count"] == 1
            assert dashboard_project["artifact_previews"] == []
            assert dashboard_project["last_modified_at"]
            async with SessionLocal() as db:
                stale_run = await db.get(Run, uuid.UUID(run_id))
                assert stale_run is not None
                stale_run.last_heartbeat = utcnow() - timedelta(seconds=61)
                await db.commit()
            stale_dashboard = await client.get("/api/v1/projects/dashboard")
            stale_project = next(
                item for item in stale_dashboard.json() if item["id"] == project_id
            )
            assert stale_project["active_run_count"] == 0
            fresh_running = await client.get("/api/v1/runs", params={"status": "running"})
            assert run_id not in {item["id"] for item in fresh_running.json()}
            unreachable = await client.get("/api/v1/runs", params={"status": "unreachable"})
            assert run_id in {item["id"] for item in unreachable.json()}
            comparison = await client.get(
                "/api/v1/comparisons/runs",
                params=[("ids", run_id), ("ids", batch_run_id)],
            )
            assert comparison.status_code == 200
            compared_run = next(
                item for item in comparison.json()["runs"] if item["run"]["id"] == run_id
            )
            assert "HASH" in compared_run["metadata_sections"]["General"]

            cases_folder = await client.post(
                f"/api/v1/projects/{project_id}/folders",
                json={"name": "Cases"},
                headers=headers,
            )
            assert cases_folder.status_code == 201
            cases_folder_id = cases_folder.json()["id"]
            gpu_folder = await client.post(
                f"/api/v1/projects/{project_id}/folders",
                json={"name": "GPU", "parent_id": cases_folder_id},
                headers=headers,
            )
            assert gpu_folder.status_code == 201
            gpu_folder_id = gpu_folder.json()["id"]
            placed = await client.put(
                f"/api/v1/projects/{project_id}/runs/{run_id}/placement",
                json={"folder_id": gpu_folder_id, "position": 2},
                headers=headers,
            )
            assert placed.status_code == 200
            assert placed.json()["folder_id"] == gpu_folder_id
            assert placed.json()["position"] == 2
            collection_placed = await client.put(
                f"/api/v1/projects/{project_id}/runs/placement/batch",
                json={
                    "run_ids": [run_id, batch_run_id],
                    "folder_id": gpu_folder_id,
                    "position": 4,
                },
                headers=headers,
            )
            assert collection_placed.status_code == 200
            assert [item["run"]["id"] for item in collection_placed.json()] == [
                run_id,
                batch_run_id,
            ]
            assert [item["position"] for item in collection_placed.json()] == [4, 5]
            project_search = await client.get(
                "/api/v1/runs",
                params={"project_id": project_id, "search": "Batch project run"},
            )
            assert project_search.status_code == 200
            assert [item["id"] for item in project_search.json()] == [batch_run_id]
            layout = await client.get(f"/api/v1/projects/{project_id}/layout")
            assert {folder["name"] for folder in layout.json()["folders"]} == {"Cases", "GPU"}
            placement = next(item for item in layout.json()["runs"] if item["run"]["id"] == run_id)
            assert placement["folder_id"] == gpu_folder_id
            cycle = await client.patch(
                f"/api/v1/projects/{project_id}/folders/{cases_folder_id}",
                json={"parent_id": gpu_folder_id},
                headers=headers,
            )
            assert cycle.status_code == 422

            public = await client.get("/api/v1/public/projects/rm-study")
            assert public.status_code == 200
            assert {item["id"] for item in public.json()["runs"]} == {run_id, batch_run_id}

            detail = await client.get(f"/api/v1/runs/{run_id}")
            assert detail.json()["run"]["scheduler_details"]["plot_file"] == "output.481516"
            assert detail.json()["run"]["output_path"] == "/work/alamo/output.481516"
            assert detail.json()["thermo"][0]["rows"][1]["values"]["temperature"] == 305.0
            assert detail.json()["output"]["git_diff"].startswith("diff --git")
            assert {copy["path"] for copy in detail.json()["copies"]} == {
                "/scratch/brunnels/output.481516",
                "/home/user/output.481516",
            }

            deleted_project = await client.delete(f"/api/v1/projects/{project_id}", headers=headers)
            assert deleted_project.status_code == 204
            assert (await client.get("/api/v1/public/projects/rm-study")).status_code == 404

            deleted_run = await client.delete(f"/api/v1/runs/{run_id}", headers=headers)
            assert deleted_run.status_code == 204
            deleted_batch_run = await client.delete(f"/api/v1/runs/{batch_run_id}", headers=headers)
            assert deleted_batch_run.status_code == 204
            assert (await client.get(f"/api/v1/runs/{run_id}")).status_code == 404
