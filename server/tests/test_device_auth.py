from urllib.parse import urlsplit

import pytest
from httpx import ASGITransport, AsyncClient

from zephyr_server.main import app
from zephyr_server.routers.auth import safe_login_next


@pytest.mark.asyncio
async def test_device_login_issues_a_single_revocable_token() -> None:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as browser:
            created = await browser.post(
                "/api/v1/auth/device", json={"device_name": "login-test-host"}
            )
            assert created.status_code == 201
            flow = created.json()
            assert flow["expires_in"] == 600
            assert flow["interval"] == 2
            browser_code = urlsplit(flow["verification_url"]).path.rsplit("/", 1)[-1]

            pending = await browser.post(
                "/api/v1/auth/device/token",
                json={"device_code": flow["device_code"]},
            )
            assert pending.json() == {"status": "pending", "token": None, "email": None}

            assert (await browser.post("/api/v1/auth/dev-login")).status_code == 200
            csrf = (await browser.get("/api/v1/auth/me")).json()["csrf_token"]
            tampered = await browser.post(
                f"/api/v1/auth/device/{browser_code}x/approve",
                headers={"X-CSRF-Token": csrf},
            )
            assert tampered.status_code == 404
            approved = await browser.post(
                f"/api/v1/auth/device/{browser_code}/approve",
                headers={"X-CSRF-Token": csrf},
            )
            assert approved.json() == {
                "status": "approved",
                "device_name": "login-test-host",
            }

            exchanged = await browser.post(
                "/api/v1/auth/device/token",
                json={"device_code": flow["device_code"]},
            )
            assert exchanged.status_code == 200
            result = exchanged.json()
            assert result["status"] == "approved"
            assert result["token"].startswith("zph_")
            assert result["email"] == "developer@solids.group"

            consumed = await browser.post(
                "/api/v1/auth/device/token",
                json={"device_code": flow["device_code"]},
            )
            assert consumed.json()["status"] == "consumed"

        async with AsyncClient(transport=transport, base_url="http://testserver") as cli:
            me = await cli.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {result['token']}"}
            )
            assert me.status_code == 200
            assert me.json()["user"]["email"] == "developer@solids.group"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/connect/abc.def", "/connect/abc.def"),
        ("https://attacker.example/connect/code", "/"),
        ("//attacker.example/connect/code", "/"),
        ("/settings", "/"),
        (None, "/"),
    ],
)
def test_login_return_path_is_same_origin(value: str | None, expected: str) -> None:
    assert safe_login_next(value) == expected
