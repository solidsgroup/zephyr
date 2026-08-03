from __future__ import annotations

import http.client
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from . import __version__
from .config import Credentials


class ApiError(RuntimeError):
    pass


class Client:
    def __init__(self, credentials: Credentials) -> None:
        self.server = credentials.server.rstrip("/")
        self.token = credentials.token

    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        query: list[tuple[str, str]] | None = None,
    ) -> Any:
        url = f"{self.server}/api/v1{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": f"zph/{__version__}",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as error:
            detail = error.reason
            try:
                data = json.loads(error.read())
                detail = data.get("detail", data)
            except (ValueError, OSError):
                pass
            raise ApiError(f"Zephyr returned {error.code}: {detail}") from error
        except URLError as error:
            raise ApiError(f"Cannot reach {self.server}: {error.reason}") from error

    def upload_file(self, url: str, source: Path, headers: dict[str, str]) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ApiError("Object store returned an invalid upload URL")
        connection_type = (
            http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        )
        connection = connection_type(parsed.hostname, parsed.port, timeout=300)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        try:
            connection.putrequest("PUT", target)
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.putheader("Content-Length", str(source.stat().st_size))
            connection.endheaders()
            with source.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    connection.send(block)
            response = connection.getresponse()
            response.read()
            if not 200 <= response.status < 300:
                raise ApiError(f"Object upload failed with HTTP {response.status}")
        except OSError as error:
            raise ApiError(f"Object upload failed: {error}") from error
        finally:
            connection.close()

    @staticmethod
    def download(url: str) -> bytes:
        try:
            with urlopen(url, timeout=300) as response:
                return response.read()
        except (HTTPError, URLError) as error:
            raise ApiError(f"Object download failed: {error}") from error
