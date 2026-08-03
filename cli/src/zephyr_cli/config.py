from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    pass


def config_dir() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".config"
    return base / "zephyr"


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass(frozen=True)
class Credentials:
    server: str
    token: str

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
        return cls(server=str(server).rstrip("/"), token=str(token))

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
            temporary.unlink(missing_ok=True)
            raise
