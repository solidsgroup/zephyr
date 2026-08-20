from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.responses import RedirectResponse
from httpx import ASGITransport, AsyncClient

from zephyr_server.main import app
from zephyr_server.routers import auth as auth_router

pytestmark = pytest.mark.asyncio


class FakeGoogle:
    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.authorization_options: dict[str, Any] = {}

    async def authorize_redirect(
        self, request: Any, redirect_uri: str, **kwargs: Any
    ) -> RedirectResponse:
        self.authorization_options = {"redirect_uri": redirect_uri, **kwargs}
        return RedirectResponse("https://accounts.google.test/authorize")

    async def authorize_access_token(self, request: Any) -> dict[str, Any]:
        return {"userinfo": self.info}


class FakeOAuth:
    def __init__(self, google: FakeGoogle) -> None:
        self.google = google

    def create_client(self, name: str) -> FakeGoogle | None:
        return self.google if name == "google" else None


async def test_linked_google_account_can_sign_in_and_be_unlinked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    google = FakeGoogle()
    monkeypatch.setattr(auth_router, "configure_oauth", lambda settings: FakeOAuth(google))
    linked_subject = f"personal-{uuid.uuid4()}"

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            login = await client.post("/api/v1/auth/dev-login")
            assert login.status_code == 200
            primary_email = login.json()["email"]

            started = await client.get("/api/v1/auth/google-accounts/link")
            assert started.status_code == 307
            assert google.authorization_options["prompt"] == "select_account"
            assert google.authorization_options["redirect_uri"].endswith(
                "/api/v1/auth/callback/google"
            )

            google.info = {
                "sub": linked_subject,
                "email": "researcher.personal@gmail.com",
                "email_verified": True,
                "name": "Researcher Personal",
                "picture": "https://images.test/personal.png",
            }
            linked = await client.get("/api/v1/auth/callback/google")
            assert linked.status_code == 303
            assert linked.headers["location"] == "/settings?google_link=linked"

            accounts = await client.get("/api/v1/auth/google-accounts")
            assert accounts.status_code == 200
            assert [account["is_primary"] for account in accounts.json()] == [True, False]
            assert accounts.json()[0]["email"] == primary_email
            assert accounts.json()[1]["email"] == "researcher.personal@gmail.com"
            linked_id = accounts.json()[1]["id"]

            me = await client.get("/api/v1/auth/me")
            csrf = me.json()["csrf_token"]
            logged_out = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
            assert logged_out.status_code == 204

            alternate_login = await client.get("/api/v1/auth/callback/google")
            assert alternate_login.status_code == 307
            me = await client.get("/api/v1/auth/me")
            assert me.status_code == 200
            assert me.json()["user"]["email"] == primary_email

            csrf = me.json()["csrf_token"]
            removed = await client.delete(
                f"/api/v1/auth/google-accounts/{linked_id}",
                headers={"X-CSRF-Token": csrf},
            )
            assert removed.status_code == 204
            remaining = await client.get("/api/v1/auth/google-accounts")
            assert len(remaining.json()) == 1
            assert remaining.json()[0]["is_primary"] is True


async def test_unlinked_external_google_account_cannot_sign_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    google = FakeGoogle()
    google.info = {
        "sub": f"unlinked-{uuid.uuid4()}",
        "email": "unlinked@gmail.com",
        "email_verified": True,
        "name": "Unlinked User",
    }
    monkeypatch.setattr(auth_router, "configure_oauth", lambda settings: FakeOAuth(google))

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/api/v1/auth/callback/google")
            assert response.status_code == 403
            assert "already-linked" in response.json()["detail"]
