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

SLURM_METADATA_FIELDS = {
    "account": ("SLURM_JOB_ACCOUNT",),
    "array_job_id": ("SLURM_ARRAY_JOB_ID",),
    "array_task_id": ("SLURM_ARRAY_TASK_ID",),
    "cluster": ("SLURM_CLUSTER_NAME",),
    "constraints": ("SLURM_JOB_CONSTRAINTS",),
    "cpus_on_node": ("SLURM_CPUS_ON_NODE",),
    "cpus_per_task": ("SLURM_CPUS_PER_TASK",),
    "gpus": ("SLURM_GPUS",),
    "gpus_on_node": ("SLURM_GPUS_ON_NODE",),
    "gpus_per_node": ("SLURM_GPUS_PER_NODE",),
    "job_gpu_ids": ("SLURM_JOB_GPUS",),
    "job_name": ("SLURM_JOB_NAME",),
    "memory_per_cpu": ("SLURM_MEM_PER_CPU",),
    "memory_per_node": ("SLURM_MEM_PER_NODE",),
    "node_count": ("SLURM_JOB_NUM_NODES",),
    "node_list": ("SLURM_JOB_NODELIST",),
    "partition": ("SLURM_JOB_PARTITION",),
    "qos": ("SLURM_JOB_QOS",),
    "submit_directory": ("SLURM_SUBMIT_DIR",),
    "task_count": ("SLURM_NTASKS", "SLURM_STEP_NUM_TASKS", "Number_of_processors"),
    "tasks_per_node": ("SLURM_TASKS_PER_NODE", "SLURM_NTASKS_PER_NODE"),
}


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


def slurm_context_from_metadata(values: dict[str, str]) -> tuple[str | None, dict[str, str]]:
    details: dict[str, str] = {}
    for field, metadata_keys in SLURM_METADATA_FIELDS.items():
        value = next((values.get(key) for key in metadata_keys if values.get(key)), None)
        if value:
            details[field] = value
    plot_file = values.get("plot_file") or values.get("amr.plot_file")
    if plot_file:
        details["plot_file"] = plot_file
    return values.get("SLURM_JOB_ID"), details


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
