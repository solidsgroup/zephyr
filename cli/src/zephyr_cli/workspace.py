from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MARKER_NAME = ".zephyr.json"


class WorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunMarker:
    run_id: str
    server: str

    @classmethod
    def load(cls, directory: Path) -> RunMarker:
        path = directory.resolve() / MARKER_NAME
        if not path.exists():
            raise WorkspaceError(f"No {MARKER_NAME} in {directory}; run `zph import` first")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(run_id=data["run_id"], server=data["server"])
        except (OSError, ValueError, KeyError) as error:
            raise WorkspaceError(f"Invalid {path}: {error}") from error

    def save(self, directory: Path) -> None:
        path = directory.resolve() / MARKER_NAME
        path.write_text(
            json.dumps({"protocol": "1.0", "run_id": self.run_id, "server": self.server}, indent=2)
            + "\n",
            encoding="utf-8",
        )
