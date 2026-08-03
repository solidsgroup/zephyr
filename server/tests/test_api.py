import pytest
from httpx import ASGITransport, AsyncClient

from zephyr_server.main import app

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

            created = await client.post(
                "/api/v1/runs",
                json={"name": "Richtmyer-Meshkov", "status": "running"},
                headers=headers,
            )
            assert created.status_code == 201
            run_id = created.json()["id"]

            metadata = await client.put(
                f"/api/v1/runs/{run_id}/metadata",
                json={"raw_text": "HASH = abc123\nStatus = running\nProgress = 25\n"},
                headers=headers,
            )
            assert metadata.json()["values"]["HASH"] == "abc123"

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
            assert detail.json()["thermo"][0]["rows"][1]["values"]["temperature"] == 305.0

            deleted_project = await client.delete(f"/api/v1/projects/{project_id}", headers=headers)
            assert deleted_project.status_code == 204
            assert (await client.get("/api/v1/public/projects/rm-study")).status_code == 404

            deleted_run = await client.delete(f"/api/v1/runs/{run_id}", headers=headers)
            assert deleted_run.status_code == 204
            assert (await client.get(f"/api/v1/runs/{run_id}")).status_code == 404
