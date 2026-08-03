from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import Settings

DOWNLOAD_TOKEN_SALT = "zephyr-artifact-download-v1"


def artifact_download_url(settings: Settings, object_key: str, content_type: str) -> str:
    serializer = URLSafeTimedSerializer(settings.session_secret, salt=DOWNLOAD_TOKEN_SALT)
    token = serializer.dumps({"key": object_key, "content_type": content_type})
    return f"{settings.public_url.rstrip('/')}/api/v1/artifacts/content/{token}"


def decode_download_token(settings: Settings, token: str) -> tuple[str, str]:
    serializer = URLSafeTimedSerializer(settings.session_secret, salt=DOWNLOAD_TOKEN_SALT)
    try:
        payload: Any = serializer.loads(token, max_age=settings.download_url_ttl_seconds)
    except SignatureExpired as error:
        raise HTTPException(status_code=410, detail="Artifact download link expired") from error
    except BadSignature as error:
        raise HTTPException(status_code=404, detail="Artifact download link is invalid") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=404, detail="Artifact download link is invalid")
    object_key = payload.get("key")
    content_type = payload.get("content_type")
    if not isinstance(object_key, str) or not isinstance(content_type, str):
        raise HTTPException(status_code=404, detail="Artifact download link is invalid")
    return object_key, content_type
