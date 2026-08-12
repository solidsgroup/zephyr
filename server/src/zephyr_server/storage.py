from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from .config import Settings, get_settings

DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


class StorageError(RuntimeError):
    pass


class StoredObjectNotFound(StorageError):
    pass


@dataclass(frozen=True)
class UploadTarget:
    object_key: str
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class DownloadStream:
    content: Iterator[bytes]
    status_code: int
    headers: dict[str, str]


class ServiceAccountTokenProvider:
    def __init__(self, credentials_json: str) -> None:
        try:
            info = json.loads(credentials_json)
            self.credentials: service_account.Credentials = (
                service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
                    info, scopes=[DRIVE_SCOPE]
                )
            )
        except (ValueError, TypeError, KeyError) as error:
            raise StorageError("Google Drive service account credentials are invalid") from error
        self.lock = threading.Lock()

    def __call__(self) -> str:
        with self.lock:
            try:
                if not self.credentials.valid:
                    self.credentials.refresh(  # type: ignore[no-untyped-call]
                        GoogleAuthRequest()
                    )
            except GoogleAuthError as error:
                raise StorageError("Google Drive authentication failed") from error
            token = self.credentials.token
            if not token:
                raise StorageError("Google Drive did not issue an access token")
            return str(token)


class GoogleDriveStorage:
    """Content-addressed working artifacts stored in a Google Shared Drive."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        token_provider: Callable[[], str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if self.settings.artifact_store != "google_drive":
            raise StorageError("Google Drive artifact storage is not configured")
        if not self.settings.google_drive_folder_id:
            raise StorageError("Google Drive artifact folder is not configured")
        self.token_provider = token_provider or ServiceAccountTokenProvider(
            self.settings.google_drive_service_account_json
        )
        self.client = httpx.Client(transport=transport, timeout=60)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token_provider()}"}
        if extra:
            headers.update(extra)
        return headers

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
            message = payload.get("error", {}).get("message")
            if message:
                return str(message)
        except (ValueError, AttributeError):
            pass
        return response.text[:300] or response.reason_phrase

    def _check(self, response: httpx.Response) -> httpx.Response:
        if response.status_code == 404:
            raise StoredObjectNotFound("Google Drive artifact was not found")
        if not response.is_success:
            message = self._error_message(response)
            raise StorageError(f"Google Drive returned HTTP {response.status_code}: {message}")
        return response

    def _generate_file_id(self) -> str:
        response = self._check(
            self.client.get(
                f"{DRIVE_API}/files/generateIds",
                params={"count": 1, "space": "drive", "type": "files"},
                headers=self._headers(),
            )
        )
        ids = response.json().get("ids", [])
        if not ids:
            raise StorageError("Google Drive did not return a file ID")
        return str(ids[0])

    def initiate_upload(
        self,
        sha256: str,
        size: int,
        content_type: str,
        object_key: str | None = None,
    ) -> UploadTarget:
        file_id = object_key or self._generate_file_id()
        metadata = {
            "id": file_id,
            "name": sha256,
            "parents": [self.settings.google_drive_folder_id],
            "mimeType": content_type,
            "appProperties": {
                "zephyr_sha256": sha256,
                "zephyr_size": str(size),
            },
        }
        response = self._check(
            self.client.post(
                f"{DRIVE_UPLOAD_API}/files",
                params={"uploadType": "resumable", "supportsAllDrives": "true"},
                headers=self._headers(
                    {
                        "Content-Type": "application/json; charset=UTF-8",
                        "X-Upload-Content-Type": content_type,
                        "X-Upload-Content-Length": str(size),
                    }
                ),
                json=metadata,
            )
        )
        upload_url = response.headers.get("Location")
        if not upload_url:
            raise StorageError("Google Drive did not return a resumable upload URL")
        return UploadTarget(file_id, upload_url, {"Content-Type": content_type})

    def metadata(self, object_key: str) -> dict[str, Any]:
        response = self._check(
            self.client.get(
                f"{DRIVE_API}/files/{object_key}",
                params={
                    "supportsAllDrives": "true",
                    "fields": "id,size,mimeType,appProperties,sha256Checksum,trashed",
                },
                headers=self._headers(),
            )
        )
        return dict(response.json())

    def verify(self, object_key: str, sha256: str, size: int) -> None:
        metadata = self.metadata(object_key)
        properties = metadata.get("appProperties") or {}
        if metadata.get("trashed"):
            raise StorageError("Google Drive artifact is in the trash")
        if int(metadata.get("size", -1)) != size:
            raise StorageError("Google Drive artifact size does not match")
        if properties.get("zephyr_sha256") != sha256:
            raise StorageError("Google Drive artifact digest metadata does not match")
        drive_digest = metadata.get("sha256Checksum")
        if drive_digest != sha256:
            raise StorageError("Google Drive artifact checksum does not match")

    def open_download_response(
        self,
        object_key: str,
        byte_range: str | None = None,
    ) -> DownloadStream:
        headers = self._headers({"Range": byte_range} if byte_range else None)
        request = self.client.build_request(
            "GET",
            f"{DRIVE_API}/files/{object_key}",
            params={"alt": "media", "supportsAllDrives": "true"},
            headers=headers,
        )
        response = self.client.send(request, stream=True)
        if not response.is_success:
            try:
                response.read()
                self._check(response)
            finally:
                response.close()

        def chunks() -> Iterator[bytes]:
            try:
                yield from response.iter_bytes(chunk_size=1024 * 1024)
            finally:
                response.close()

        response_headers = {"Accept-Ranges": "bytes"}
        for source, target in (
            ("content-range", "Content-Range"),
            ("content-length", "Content-Length"),
        ):
            if value := response.headers.get(source):
                response_headers[target] = value
        return DownloadStream(
            content=chunks(),
            status_code=response.status_code,
            headers=response_headers,
        )

    def open_download(self, object_key: str) -> Iterator[bytes]:
        return self.open_download_response(object_key).content


@lru_cache
def get_storage() -> GoogleDriveStorage:
    return GoogleDriveStorage()
