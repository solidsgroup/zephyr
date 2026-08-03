from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

KEY_VALUE = re.compile(r"^\s*([^:=#][^:=]*?)\s*[:=]\s*(.*?)\s*$")


def metadata_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = KEY_VALUE.match(line)
        if match:
            values[match.group(1).strip().replace(" ", "_")] = match.group(2).strip()
    return values


def metadata_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def derived_status(values: dict[str, str]) -> tuple[str, int | None]:
    raw = values.get("Status", values.get("STATUS", "")).strip().lower()
    match = re.fullmatch(r"([^()]+?)(?:\s*\((\d+)%\))?", raw)
    source = match.group(1).strip() if match else raw
    mapping = {
        "running": "running",
        "complete": "completed",
        "completed": "completed",
        "failed": "failed",
        "error": "failed",
        "abort": "failed",
        "segfault": "failed",
        "interrupt": "interrupted",
        "interrupted": "interrupted",
    }
    status = mapping.get(source, "running")
    progress = int(match.group(2)) if match and match.group(2) else None
    raw_progress = values.get("Progress", values.get("PROGRESS"))
    if raw_progress:
        try:
            progress = max(0, min(100, round(float(raw_progress.rstrip("%")))))
        except ValueError:
            pass
    return status, progress


def is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


@dataclass
class ThermoTail:
    path: Path
    offset: int = 0
    segment: int = 0
    columns: list[str] = field(default_factory=list)
    sequence: int = 0
    partial: str = ""
    pending: list[dict[str, object]] = field(default_factory=list)

    def poll(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return list(self.pending)
        size = self.path.stat().st_size
        if size < self.offset:
            self.offset = 0
            self.segment += 1
            self.columns = []
            self.sequence = 0
            self.partial = ""
        with self.path.open("r", encoding="utf-8", errors="replace") as stream:
            stream.seek(self.offset)
            data = stream.read()
            self.offset = stream.tell()
        if not data:
            return list(self.pending)
        data = self.partial + data
        if not data.endswith("\n"):
            data, self.partial = data.rsplit("\n", 1) if "\n" in data else ("", data)
        else:
            self.partial = ""
        batches: list[dict[str, object]] = []
        rows: list[dict[str, object]] = []
        for raw in data.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if not all(is_number(value) for value in fields):
                if rows and self.columns:
                    batches.append({"segment": self.segment, "columns": self.columns, "rows": rows})
                    rows = []
                    self.segment += 1
                    self.sequence = 0
                self.columns = fields
                continue
            if not self.columns:
                self.columns = [f"column_{index}" for index in range(len(fields))]
            if len(fields) != len(self.columns):
                continue
            parsed = [float(value) for value in fields]
            values = {
                column: value if math.isfinite(value) else None
            for column, value in zip(self.columns, parsed)
            }
            rows.append({"sequence": self.sequence, "values": values})
            self.sequence += 1
            if len(rows) == 1000:
                batches.append({"segment": self.segment, "columns": self.columns, "rows": rows})
                rows = []
        if rows and self.columns:
            batches.append({"segment": self.segment, "columns": self.columns, "rows": rows})
        self.pending.extend(batches)
        return list(self.pending)

    def ack(self) -> None:
        if self.pending:
            self.pending.pop(0)
