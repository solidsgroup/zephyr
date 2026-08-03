import pytest

from zephyr_cli.config import ConfigError, Credentials, normalize_server_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("zephyr.solids.group", "https://zephyr.solids.group"),
        ("https://zephyr.solids.group/", "https://zephyr.solids.group"),
        ("http://localhost:8000", "http://localhost:8000"),
        ("http://[::1]:8000/", "http://[::1]:8000"),
    ],
)
def test_normalize_server_url(value: str, expected: str) -> None:
    assert normalize_server_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ftp://zephyr.solids.group",
        "https://user@zephyr.solids.group",
        "https://zephyr.solids.group/path",
        "https://zephyr.solids.group?query=yes",
    ],
)
def test_normalize_server_url_rejects_invalid_origins(value: str) -> None:
    with pytest.raises(ConfigError):
        normalize_server_url(value)


def test_credentials_normalize_bare_server_hostname() -> None:
    credentials = Credentials(server="zephyr.solids.group", token="secret")

    assert credentials.server == "https://zephyr.solids.group"
