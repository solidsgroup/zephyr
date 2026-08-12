from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from zephyr_server import main

pytestmark = pytest.mark.asyncio


async def test_cli_distribution_is_served_without_caching(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    distribution = tmp_path / "downloads" / "zph-latest.tar.gz"
    distribution.parent.mkdir()
    distribution.write_bytes(b"zph source distribution")
    monkeypatch.setattr(main, "static_dir", tmp_path)

    async with AsyncClient(
        transport=ASGITransport(app=main.app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/downloads/zph-latest.tar.gz")

    assert response.status_code == 200
    assert response.content == b"zph source distribution"
    assert response.headers["cache-control"] == "no-cache"
    assert "zph-latest.tar.gz" in response.headers["content-disposition"]
