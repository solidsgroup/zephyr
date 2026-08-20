from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .config import get_settings
from .db import create_schema_for_development
from .routers import artifacts, auth, comparisons, projects, public, runs, views

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await create_schema_for_development()
    yield


app = FastAPI(
    title="Zephyr API",
    description="Zero-effort Execution Provenance and Health for Your Alamo Runs",
    version=__version__,
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=settings.secure_cookies,
    same_site="lax",
    max_age=60 * 60 * 24 * 14,
)


@app.get("/healthz", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/v1/meta", tags=["protocol"])
async def protocol_metadata() -> dict[str, object]:
    return {
        "service": "zephyr",
        "server_version": __version__,
        "protocol": "1.0",
        "minimum_client": "0.1.0",
        "maximum_client": "0.x",
        "cli_distribution": f"{settings.public_url.rstrip('/')}/downloads/zph-latest.tar.gz",
        "development_login": settings.dev_auth and settings.env != "production",
        "capabilities": [
            "runs",
            "metadata",
            "run-output",
            "bulk-sync-state",
            "copy-locations",
            "bulk-copy-locations",
            "cli-distribution",
            "scheduler-context",
            "thermo-segments",
            "artifacts",
            "projects",
            "bulk-project-runs",
            "project-folders",
            "project-run-placement",
            "project-sharing",
            "public-projects",
            "comparisons",
            "saved-views",
            "device-login",
            "linked-google-accounts",
        ],
    }


for api_router in (
    auth.router,
    public.router,
    comparisons.router,
    runs.router,
    artifacts.router,
    projects.router,
    views.router,
    artifacts.content_router,
):
    app.include_router(api_router, prefix="/api/v1")


static_dir = settings.static_dir


@app.get("/downloads/zph-latest.tar.gz", include_in_schema=False)
async def download_zph_distribution():
    distribution = static_dir / "downloads" / "zph-latest.tar.gz" if static_dir else None
    if distribution is None or not distribution.is_file():
        raise HTTPException(status_code=404, detail="zph distribution is unavailable")
    return FileResponse(
        distribution,
        media_type="application/gzip",
        filename="zph-latest.tar.gz",
        headers={"Cache-Control": "no-cache"},
    )


if static_dir and static_dir.exists():
    served_static_dir: Path = static_dir
    assets = served_static_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        requested = (served_static_dir / path).resolve()
        root = served_static_dir.resolve()
        if requested.is_relative_to(root) and requested.is_file():
            return FileResponse(requested)
        index = served_static_dir / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Not found")
