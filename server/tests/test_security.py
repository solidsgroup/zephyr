import pytest
from fastapi import HTTPException

from zephyr_server.auth import issue_api_token, token_digest
from zephyr_server.routers.artifacts import safe_relative_path


def test_api_token_format_and_hash() -> None:
    prefix, token = issue_api_token()
    assert token.startswith(f"zph_{prefix}_")
    assert token_digest(token, "pepper") != token


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "results/../../secret"])
def test_artifact_paths_cannot_escape(path: str) -> None:
    with pytest.raises(HTTPException):
        safe_relative_path(path)
