from __future__ import annotations

import json

import httpx
import pytest

from zephyr_server.config import Settings
from zephyr_server.routers.artifacts import artifact_download_url, decode_download_token
from zephyr_server.storage import GoogleDriveStorage, StorageError


def drive_settings() -> Settings:
    return Settings(
        artifact_store="google_drive",
        google_drive_folder_id="folder-123",
        google_drive_service_account_json="{}",
        public_url="https://zephyr.example",
        session_secret="test-session-secret-that-is-long-enough",
    )


def test_google_drive_upload_verify_and_download() -> None:
    requests: list[httpx.Request] = []
    digest = "a" * 64

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.url.path.endswith("/files/generateIds"):
            return httpx.Response(200, json={"ids": ["drive-file-123"]})
        if request.url.path.endswith("/upload/drive/v3/files"):
            metadata = json.loads(request.content)
            assert metadata["id"] == "drive-file-123"
            assert metadata["parents"] == ["folder-123"]
            assert metadata["appProperties"]["zephyr_sha256"] == digest
            return httpx.Response(200, headers={"Location": "https://upload.example/session"})
        if request.url.params.get("alt") == "media":
            if request.headers.get("Range"):
                return httpx.Response(
                    206,
                    content=b"artifact",
                    headers={"Content-Range": "bytes 0-7/14", "Content-Length": "8"},
                )
            return httpx.Response(200, content=b"artifact bytes")
        if request.url.path.endswith("/files/drive-file-123"):
            return httpx.Response(
                200,
                json={
                    "id": "drive-file-123",
                    "size": "14",
                    "mimeType": "application/octet-stream",
                    "appProperties": {"zephyr_sha256": digest, "zephyr_size": "14"},
                    "sha256Checksum": digest,
                    "trashed": False,
                },
            )
        return httpx.Response(404)

    storage = GoogleDriveStorage(
        drive_settings(),
        token_provider=lambda: "test-token",
        transport=httpx.MockTransport(handler),
    )

    target = storage.initiate_upload(digest, 14, "application/octet-stream")
    assert target.object_key == "drive-file-123"
    assert target.url == "https://upload.example/session"
    assert target.headers == {"Content-Type": "application/octet-stream"}

    storage.verify(target.object_key, digest, 14)
    assert b"".join(storage.open_download(target.object_key)) == b"artifact bytes"
    partial = storage.open_download_response(target.object_key, "bytes=0-7")
    assert partial.status_code == 206
    assert partial.headers["Content-Range"] == "bytes 0-7/14"
    assert b"".join(partial.content) == b"artifact"
    assert requests[-1].headers["Range"] == "bytes=0-7"
    assert len(requests) == 5


def test_google_drive_verification_rejects_wrong_size() -> None:
    digest = "b" * 64

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "size": "99",
                "appProperties": {"zephyr_sha256": digest},
                "sha256Checksum": digest,
                "trashed": False,
            },
        )

    storage = GoogleDriveStorage(
        drive_settings(),
        token_provider=lambda: "test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(StorageError, match="size does not match"):
        storage.verify("drive-file-123", digest, 14)


def test_google_drive_verification_requires_checksum() -> None:
    digest = "c" * 64

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "size": "14",
                "appProperties": {"zephyr_sha256": digest},
                "trashed": False,
            },
        )

    storage = GoogleDriveStorage(
        drive_settings(),
        token_provider=lambda: "test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(StorageError, match="checksum does not match"):
        storage.verify("drive-file-123", digest, 14)


def test_google_drive_download_reports_streamed_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"message": "Shared Drive access denied"}},
        )

    storage = GoogleDriveStorage(
        drive_settings(),
        token_provider=lambda: "test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(StorageError, match="Shared Drive access denied"):
        storage.open_download("drive-file-123")


def test_artifact_download_tokens_round_trip() -> None:
    settings = drive_settings()
    url = artifact_download_url(settings, "drive-file-123", "image/png")
    token = url.rsplit("/", 1)[-1]

    assert decode_download_token(settings, token) == ("drive-file-123", "image/png")
