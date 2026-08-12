from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class ConfigError(RuntimeError):
    pass


def normalize_server_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    if not candidate:
        raise ConfigError("Zephyr server URL cannot be empty")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as error:
        raise ConfigError(f"Invalid Zephyr server URL: {value}") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError(
            "Zephyr server must be an HTTP(S) origin, such as https://zephyr.solids.group"
        )
    netloc = parsed.hostname
    if ":" in netloc and not netloc.startswith("["):
        netloc = f"[{netloc}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


def config_dir() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".config"
    return base / "zephyr"


def config_path() -> Path:
    return config_dir() / "config.json"


def sync_cache_path() -> Path:
    return config_dir() / "sync-cache.json"


def load_sync_cache() -> dict[str, Any]:
    path = sync_cache_path()
    if not path.exists():
        return {"version": 1, "paths": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "paths": {}}
    if data.get("version") != 1 or not isinstance(data.get("paths"), dict):
        return {"version": 1, "paths": {}}
    return data


def save_sync_cache(data: dict[str, Any]) -> None:
    directory = config_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, stat.S_IRWXU)
    descriptor, temporary_name = tempfile.mkstemp(prefix="sync-cache.", dir=directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, sync_cache_path())
        os.chmod(sync_cache_path(), stat.S_IRUSR | stat.S_IWUSR)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


@dataclass(frozen=True)
class Credentials:
    server: str
    token: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "server", normalize_server_url(self.server))

    @classmethod
    def load(cls) -> Credentials:
        server_override = os.environ.get("ZEPHYR_SERVER")
        token_override = os.environ.get("ZEPHYR_TOKEN")
        data: dict[str, Any] = {}
        path = config_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ConfigError(f"Cannot read {path}: {error}") from error
        server = server_override or data.get("server")
        token = token_override or data.get("token")
        if not server or not token:
            raise ConfigError("Zephyr is not configured; run `zph login SERVER` first")
        return cls(server=str(server), token=str(token))

    def save(self) -> None:
        directory = config_dir()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, stat.S_IRWXU)
        path = config_path()
        descriptor, temporary_name = tempfile.mkstemp(prefix="config.", dir=directory)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(
                    {"server": self.server.rstrip("/"), "token": self.token},
                    stream,
                    indent=2,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except BaseException:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
