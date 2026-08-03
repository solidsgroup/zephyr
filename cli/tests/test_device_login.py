import argparse
from pathlib import Path
from typing import Any

import pytest

from zephyr_cli import main
from zephyr_cli.config import Credentials


def test_device_login_opens_browser_polls_and_saves_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    opened: list[str] = []
    polls = iter(
        [
            {"status": "pending", "token": None, "email": None},
            {
                "status": "approved",
                "token": "zph_12345678_device-token",
                "email": "researcher@solids.group",
            },
        ]
    )

    def fake_public_request(
        server: str,
        method: str,
        path: str,
        payload: object | None = None,
        query: list[tuple[str, str]] | None = None,
        token: str | None = None,
    ) -> Any:
        assert server == "https://zephyr.solids.group"
        assert method == "POST"
        assert query is None
        assert token is None
        if path == "/auth/device":
            assert payload == {"device_name": "workstation"}
            return {
                "verification_url": "https://zephyr.solids.group/connect/browser-code",
                "device_code": "device-code",
                "expires_in": 600,
                "interval": 2,
            }
        assert path == "/auth/device/token"
        assert payload == {"device_code": "device-code"}
        return next(polls)

    def fake_authenticated_request(
        server: str,
        method: str,
        path: str,
        payload: object | None = None,
        query: list[tuple[str, str]] | None = None,
        token: str | None = None,
    ) -> Any:
        assert (server, method, path) == (
            "https://zephyr.solids.group",
            "GET",
            "/auth/me",
        )
        assert payload is None
        assert query is None
        assert token == "zph_12345678_device-token"
        return {"user": {"email": "researcher@solids.group"}}

    monkeypatch.setattr(main, "api_request", fake_public_request)
    monkeypatch.setattr("zephyr_cli.client.api_request", fake_authenticated_request)
    monkeypatch.setattr(main.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(main.time, "sleep", lambda _: None)

    credentials = main.device_login("zephyr.solids.group", "workstation")

    assert credentials == Credentials(
        server="https://zephyr.solids.group",
        token="zph_12345678_device-token",
    )
    assert Credentials.load() == credentials
    assert opened == ["https://zephyr.solids.group/connect/browser-code"]
    output = capsys.readouterr().out
    assert "copy the URL" in output
    assert "Authenticated as researcher@solids.group" in output


def test_matching_explicit_server_reuses_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    expected = Credentials("https://zephyr.solids.group", "secret")
    expected.save()
    monkeypatch.setattr(
        main,
        "device_login",
        lambda _: pytest.fail("an existing matching login should be reused"),
    )

    assert main.credentials_for_server("zephyr.solids.group", login_if_missing=True) == expected


def test_login_command_reuses_a_valid_login(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    Credentials("https://zephyr.solids.group", "secret").save()
    monkeypatch.setattr(
        "zephyr_cli.client.api_request",
        lambda *args, **kwargs: {"user": {"email": "researcher@solids.group"}},
    )
    monkeypatch.setattr(
        main,
        "device_login",
        lambda *args: pytest.fail("a valid login should not open a new device flow"),
    )

    main.cmd_login(
        argparse.Namespace(
            server="https://zephyr.solids.group",
            token=None,
            name=None,
        )
    )

    assert "Already authenticated as researcher@solids.group" in capsys.readouterr().out
