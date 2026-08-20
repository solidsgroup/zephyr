import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from zephyr_server.db import SessionLocal
from zephyr_server.main import app
from zephyr_server.models import ArtifactObject, RunArtifact
from zephyr_server.search import refresh_run_search_document

pytestmark = pytest.mark.asyncio


async def test_run_list_previews_and_selected_thumbnail() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            await client.post("/api/v1/auth/dev-login")
            me = await client.get("/api/v1/auth/me")
            headers = {"X-CSRF-Token": me.json()["csrf_token"]}
            created = await client.post(
                "/api/v1/runs",
                json={"name": "Thumbnail test", "alamo_hash": f"thumb-{uuid.uuid4()}"},
                headers=headers,
            )
            run_id = uuid.UUID(created.json()["id"])
            empty = await client.post(
                "/api/v1/runs",
                json={"name": "No artifact test", "alamo_hash": f"empty-{uuid.uuid4()}"},
                headers=headers,
            )
            empty_run_id = empty.json()["id"]

            async with SessionLocal() as db:
                records: list[RunArtifact] = []
                for index, (name, kind, content_type) in enumerate(
                    [
                        ("pressure.gif", "image", "image/gif"),
                        ("temperature.png", "image", "image/png"),
                        ("solver.log", "log", "text/plain"),
                        ("temperature.png", "image", "image/png"),
                        ("animation.webm", "file", "video/webm"),
                    ],
                    start=1,
                ):
                    digest = f"{index:064x}"
                    obj = ArtifactObject(
                        sha256=digest,
                        size=index * 100,
                        content_type=content_type,
                        object_key=f"thumbnail-test-{run_id}-{index}",
                        verified=True,
                    )
                    record = RunArtifact(
                        run_id=run_id,
                        object_sha256=digest,
                        logical_name=name,
                        path=name,
                        version=2 if index == 4 else 1,
                        kind=kind,
                    )
                    db.add_all([obj, record])
                    records.append(record)
                await db.flush()
                await refresh_run_search_document(db, run_id)
                await db.commit()
                selected_id = str(records[1].id)
                log_id = str(records[2].id)
                latest_temperature_id = str(records[3].id)
                webm_id = str(records[4].id)

            searched = await client.get("/api/v1/runs", params={"search": ".gif"})
            assert str(run_id) in {run["id"] for run in searched.json()}
            without_thumbnail = await client.get("/api/v1/runs", params={"has_thumbnail": "false"})
            assert str(run_id) in {run["id"] for run in without_thumbnail.json()}

            selected_webm = await client.put(
                f"/api/v1/runs/{run_id}/artifacts/{webm_id}/thumbnail",
                headers=headers,
            )
            assert selected_webm.status_code == 200
            assert selected_webm.json()["thumbnail_artifact_id"] == webm_id

            listing = await client.get("/api/v1/runs")
            listed = next(run for run in listing.json() if run["id"] == str(run_id))
            assert listed["artifact_count"] == 4
            assert listed["copy_count"] == 0
            assert len(listed["artifact_previews"]) == 3
            assert listed["artifact_previews"][0]["id"] == webm_id
            assert listed["artifact_previews"][0]["content_type"] == "video/webm"
            assert listed["artifact_previews"][0]["download_url"].startswith(
                f"/api/v1/runs/{run_id}/artifacts/"
            )
            assert listed["artifact_previews"][0]["download_url"].endswith("/content")

            with_artifacts = await client.get(
                "/api/v1/runs", params={"has_artifacts": "true"}
            )
            assert str(run_id) in {run["id"] for run in with_artifacts.json()}
            assert empty_run_id not in {run["id"] for run in with_artifacts.json()}
            without_artifacts = await client.get(
                "/api/v1/runs", params={"has_artifacts": "false"}
            )
            assert empty_run_id in {run["id"] for run in without_artifacts.json()}
            assert str(run_id) not in {run["id"] for run in without_artifacts.json()}
            artifact_order = await client.get(
                "/api/v1/runs", params={"sort": "artifacts_desc", "limit": 1000}
            )
            artifact_ids = [run["id"] for run in artifact_order.json()]
            assert artifact_ids.index(str(run_id)) < artifact_ids.index(empty_run_id)

            selected = await client.put(
                f"/api/v1/runs/{run_id}/artifacts/{selected_id}/thumbnail",
                headers=headers,
            )
            assert selected.status_code == 200
            assert selected.json()["thumbnail_artifact_id"] == selected_id

            with_thumbnail = await client.get("/api/v1/runs", params={"has_thumbnail": "true"})
            assert str(run_id) in {run["id"] for run in with_thumbnail.json()}
            without_thumbnail = await client.get("/api/v1/runs", params={"has_thumbnail": "false"})
            assert str(run_id) not in {run["id"] for run in without_thumbnail.json()}

            listing = await client.get("/api/v1/runs")
            listed = next(run for run in listing.json() if run["id"] == str(run_id))
            assert listed["artifact_previews"][0]["id"] == selected_id
            assert latest_temperature_id not in {
                preview["id"] for preview in listed["artifact_previews"]
            }

            rejected = await client.put(
                f"/api/v1/runs/{run_id}/artifacts/{log_id}/thumbnail",
                headers=headers,
            )
            assert rejected.status_code == 422

            deleted = await client.delete(f"/api/v1/runs/{run_id}", headers=headers)
            assert deleted.status_code == 204
            deleted_empty = await client.delete(
                f"/api/v1/runs/{empty_run_id}", headers=headers
            )
            assert deleted_empty.status_code == 204
