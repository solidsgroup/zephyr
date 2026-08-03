from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedMetadata:
    values: dict[str, str]
    sections: dict[str, list[str]]
    digest: str


STATUS_RE = re.compile(r"^([^()]+?)(?:\s*\((\d+)%\))?$")


def parse_metadata(raw: str) -> ParsedMetadata:
    values: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    section = "General"
    sections[section] = []

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title and not set(title) <= {"="}:
                section = title.title()
                sections.setdefault(section, [])
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        values[key] = value.strip().strip('"')
        sections.setdefault(section, []).append(key)

    return ParsedMetadata(
        values=values,
        sections=sections,
        digest=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def status_from_metadata(values: dict[str, str]) -> tuple[str | None, int | None]:
    raw_status = values.get("Status")
    if not raw_status:
        return None, None
    match = STATUS_RE.match(raw_status)
    if not match:
        return raw_status.lower(), None
    source = match.group(1).strip().lower()
    status_map = {
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
    progress = int(match.group(2)) if match.group(2) else None
    if progress is None and (raw_progress := values.get("Progress")):
        try:
            progress = max(0, min(100, round(float(raw_progress.rstrip("%")))))
        except ValueError:
            pass
    return status_map.get(source, source), progress
