from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import mimetypes
import os
import platform
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from . import __version__
from .alamo import ThermoTail, derived_status, metadata_digest, metadata_values
from .client import ApiError, Client, api_request
from .config import ConfigError, Credentials, normalize_server_url
from .workspace import WorkspaceError

TERMINAL_STATUSES = {"completed", "failed", "interrupted"}
WATCH_LOCAL_POLL_SECONDS = 0.25
MAX_CAPTURED_TEXT_BYTES = 1_000_000
BOX_LIB_DATA_TREE = re.compile(r"^\d+(?:cell|node)$", re.IGNORECASE)
ALWAYS_PRUNED_DIRECTORIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}
ALAMO_SOURCE_DIRECTORIES = {
    ".make",
    ".simba",
    "bin",
    "build",
    "docs",
    "ext",
    "lib",
    "scripts",
    "src",
    "zephyr",
}
SLURM_DETAIL_ENVIRONMENT = {
    "account": "SLURM_JOB_ACCOUNT",
    "array_job_id": "SLURM_ARRAY_JOB_ID",
    "array_task_id": "SLURM_ARRAY_TASK_ID",
    "cluster": "SLURM_CLUSTER_NAME",
    "constraints": "SLURM_JOB_CONSTRAINTS",
    "cpus_on_node": "SLURM_CPUS_ON_NODE",
    "cpus_per_task": "SLURM_CPUS_PER_TASK",
    "gpus": "SLURM_GPUS",
    "gpus_on_node": "SLURM_GPUS_ON_NODE",
    "gpus_per_node": "SLURM_GPUS_PER_NODE",
    "job_gpu_ids": "SLURM_JOB_GPUS",
    "job_name": "SLURM_JOB_NAME",
    "memory_per_cpu": "SLURM_MEM_PER_CPU",
    "memory_per_node": "SLURM_MEM_PER_NODE",
    "node_count": "SLURM_JOB_NUM_NODES",
    "node_list": "SLURM_JOB_NODELIST",
    "partition": "SLURM_JOB_PARTITION",
    "qos": "SLURM_JOB_QOS",
    "submit_directory": "SLURM_SUBMIT_DIR",
    "task_count": "SLURM_NTASKS",
}
SYNCED_METADATA_DIGESTS: dict[str, str] = {}
SYNCED_OUTPUT_DIGESTS: dict[tuple[str, str], str] = {}

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_BLUE = "\033[34m"
ANSI_CYAN = "\033[36m"


@dataclass(frozen=True)
class DirectoryInventory:
    file_count: int
    total_size_bytes: int
    has_cell_data: bool
    has_node_data: bool
    manifest_digest: str


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git_commit(directory: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=directory,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def git_repository_url(directory: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=directory,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    url = result.stdout.strip()
    match = re.fullmatch(r"git@([^:]+):(.+)", url)
    if match:
        url = f"https://{match.group(1)}/{match.group(2)}"
    elif url.startswith("ssh://git@"):
        url = f"https://{url[len('ssh://git@'):]}"
    if url.endswith(".git"):
        url = url[:-4]
    return url.rstrip("/") or None


def scheduler_context() -> tuple[str | None, str | None, dict[str, str]]:
    slurm_job_id = os.environ.get("SLURM_JOB_ID")
    if slurm_job_id:
        details = {}
        for name, variable in SLURM_DETAIL_ENVIRONMENT.items():
            value = os.environ.get(variable)
            if value:
                details[name] = value
        return "slurm", slurm_job_id, details
    for system, variable in (
        ("pbs", "PBS_JOBID"),
        ("lsf", "LSB_JOBID"),
        ("sge", "JOB_ID"),
    ):
        value = os.environ.get(variable)
        if value:
            return system, value, {}
    return None, None, {}


def scheduler_job_id() -> str | None:
    return scheduler_context()[1]


def device_login(server: str, device_name: str | None = None) -> Credentials:
    server = normalize_server_url(server)
    flow = api_request(
        server,
        "POST",
        "/auth/device",
        {"device_name": (device_name or socket.gethostname())[:100]},
    )
    try:
        verification_url = str(flow["verification_url"])
        device_code = str(flow["device_code"])
        expires_in = int(flow["expires_in"])
        interval = max(int(flow["interval"]), 1)
    except (KeyError, TypeError, ValueError) as error:
        raise ApiError("Zephyr returned an invalid device-login response") from error

    print("Open this URL in a browser to connect zph:")
    print(f"  {verification_url}")
    print("Attempting to open it automatically; copy the URL if no browser appears.")
    try:
        webbrowser.open(verification_url)
    except (OSError, webbrowser.Error):
        pass
    print("Waiting for browser login…", flush=True)

    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        result = api_request(
            server,
            "POST",
            "/auth/device/token",
            {"device_code": device_code},
        )
        state = result.get("status") if isinstance(result, dict) else None
        if state == "approved":
            token = result.get("token")
            if not isinstance(token, str) or not token:
                raise ApiError("Zephyr approved the login without returning a token")
            credentials = Credentials(server=server, token=token)
            user = Client(credentials).request("GET", "/auth/me")["user"]
            credentials.save()
            print(f"Authenticated as {user['email']} at {server}")
            return credentials
        if state in {"expired", "consumed"}:
            raise ConfigError(f"Device login was {state}; run `zph login {server}` again")
        if state != "pending":
            raise ApiError("Zephyr returned an invalid device-login status")
        time.sleep(interval)
    raise ConfigError(f"Device login expired; run `zph login {server}` again")


def credentials_for_server(
    server: str | None = None,
    *,
    login_if_missing: bool = False,
) -> Credentials:
    requested = normalize_server_url(server) if server else None
    try:
        credentials = Credentials.load()
    except ConfigError:
        if requested and login_if_missing:
            return device_login(requested)
        raise
    if requested and credentials.server != requested:
        if login_if_missing:
            return device_login(requested)
        raise ConfigError(
            f"zph is connected to {credentials.server}, not the requested server {requested}"
        )
    return credentials


def configured_client() -> Client:
    return Client(credentials_for_server())


def color_enabled(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return stream.isatty() and os.environ.get("TERM") != "dumb"


def paint(text: str, *styles: str, enabled: bool) -> str:
    if not enabled or not styles:
        return text
    return f"{''.join(styles)}{text}{ANSI_RESET}"


def read_metadata(directory: Path) -> tuple[str, dict[str, str]]:
    path = directory / "metadata"
    if not path.exists():
        return "", {}
    text = path.read_text(encoding="utf-8", errors="replace")
    return text, metadata_values(text)


def require_alamo_hash(directory: Path) -> str:
    _, values = read_metadata(directory)
    alamo_hash = values.get("HASH") or values.get("Hash")
    if not alamo_hash:
        raise WorkspaceError(f"No HASH found in {directory.resolve() / 'metadata'}")
    return alamo_hash


def runs_by_hash(client: Client, alamo_hash: str) -> list[dict[str, Any]]:
    runs = client.request(
        "GET",
        "/runs",
        query=[("search", alamo_hash), ("limit", "1000")],
    )
    return [run for run in runs if run.get("alamo_hash") == alamo_hash]


def lookup_run_by_hash(client: Client, alamo_hash: str) -> dict[str, Any] | None:
    matches = runs_by_hash(client, alamo_hash)
    if len(matches) > 1:
        raise WorkspaceError(
            f"More than one accessible Zephyr run has HASH {alamo_hash}; "
            "remove the duplicate before continuing"
        )
    return matches[0] if matches else None


def lookup_owned_run_by_hash(
    client: Client,
    alamo_hash: str,
    owner_id: str,
) -> dict[str, Any] | None:
    matches = [
        run for run in runs_by_hash(client, alamo_hash) if str(run.get("owner_id")) == owner_id
    ]
    if len(matches) > 1:
        raise WorkspaceError(f"More than one owned Zephyr run has HASH {alamo_hash}")
    return matches[0] if matches else None


def find_run_by_hash(client: Client, alamo_hash: str) -> dict[str, Any]:
    run = lookup_run_by_hash(client, alamo_hash)
    if run is None:
        raise WorkspaceError(f"No Zephyr run found for HASH {alamo_hash}")
    return run


def import_directory(
    client: Client,
    directory: Path,
    name: str | None = None,
    status: str = "starting",
    command: list[str] | None = None,
    allow_missing_hash: bool = False,
) -> dict[str, Any]:
    directory = directory.resolve()
    text, values = read_metadata(directory)
    alamo_hash = values.get("HASH") or values.get("Hash")
    if not alamo_hash and not allow_missing_hash:
        raise WorkspaceError(f"No HASH found in {directory / 'metadata'}")
    scheduler_system, job_id, scheduler_details = scheduler_context()
    plot_file = values.get("plot_file") or values.get("amr.plot_file")
    if plot_file:
        plot_file = plot_file.strip().strip("\"'")
    submit_directory = scheduler_details.get("submit_directory")
    if submit_directory:
        try:
            plot_file = str(directory.relative_to(Path(submit_directory).resolve()))
        except ValueError:
            pass
    if plot_file:
        scheduler_details["plot_file"] = plot_file
    payload = {
        "alamo_hash": alamo_hash,
        "name": name or values.get("Title") or directory.name,
        "status": status,
        "started_at": utcnow(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "output_path": str(directory),
        "git_commit": values.get("Git_commit_hash") or git_commit(directory),
        "git_repository_url": git_repository_url(directory),
        "command": command or [],
    }
    if scheduler_system and job_id:
        payload.update(
            {
                "scheduler_job_id": job_id,
                "scheduler_system": scheduler_system,
                "scheduler_details": scheduler_details,
            }
        )
    run = client.request("POST", "/runs", payload)
    if text:
        client.request("PUT", f"/runs/{run['id']}/metadata", {"raw_text": text})
        SYNCED_METADATA_DIGESTS[str(run["id"])] = metadata_digest(text)
    return run


def cmd_login(args: argparse.Namespace) -> None:
    server = normalize_server_url(args.server)
    if not args.token:
        try:
            existing = Credentials.load()
        except ConfigError:
            existing = None
        if existing is not None and existing.server == server:
            try:
                user = Client(existing).request("GET", "/auth/me")["user"]
            except (ApiError, KeyError, TypeError):
                pass
            else:
                print(f"Already authenticated as {user['email']} at {server}")
                return
        device_login(server, args.name)
        return
    credentials = Credentials(server=server, token=args.token)
    user = Client(credentials).request("GET", "/auth/me")["user"]
    credentials.save()
    print(f"Authenticated as {user['email']} at {server}")


def cmd_import(args: argparse.Namespace) -> None:
    directory = Path(args.directory)
    client = configured_client()
    run = import_directory(client, directory, args.name, status=args.status)
    print(f"{run['alamo_hash']}  {run['name']}")


def expand_add_paths(patterns: list[str]) -> list[Path]:
    matches: list[Path] = []
    unmatched: list[str] = []
    for pattern in patterns or ["."]:
        expanded = str(Path(pattern).expanduser())
        literal = Path(expanded)
        if literal.exists():
            found = [expanded]
        else:
            found = sorted(glob.glob(expanded, recursive=True))
        if not found:
            unmatched.append(pattern)
            continue
        matches.extend(Path(match).resolve() for match in found)
    if unmatched:
        raise WorkspaceError(f"No paths matched: {', '.join(unmatched)}")
    return list(dict.fromkeys(matches))


def discover_run_directories(path: Path) -> tuple[Path, list[Path]]:
    try:
        target = path.expanduser().resolve(strict=True)
    except OSError as error:
        raise WorkspaceError(f"Cannot scan {path}: {error}") from error

    if target.is_file():
        if target.name != "metadata":
            raise WorkspaceError(f"{target} is not an Alamo metadata file")
        return target.parent, [target.parent]
    if not target.is_dir():
        raise WorkspaceError(f"{target} is not a directory")
    if BOX_LIB_DATA_TREE.fullmatch(target.name):
        return target, []

    try:
        directories = set()

        def raise_walk_error(error: OSError) -> None:
            raise error

        for root, child_directories, filenames in os.walk(target, onerror=raise_walk_error):
            child_directories[:] = [
                name
                for name in child_directories
                if name not in ALWAYS_PRUNED_DIRECTORIES
                and not BOX_LIB_DATA_TREE.fullmatch(name)
            ]
            if "metadata" in filenames:
                metadata = Path(root) / "metadata"
                if metadata.is_file():
                    directories.add(metadata.parent.resolve())
                    child_directories[:] = []
                    continue
            if "configure" in filenames and "src" in child_directories:
                child_directories[:] = [
                    name for name in child_directories if name not in ALAMO_SOURCE_DIRECTORIES
                ]
    except OSError as error:
        raise WorkspaceError(f"Cannot scan {target}: {error}") from error
    return target, sorted(directories, key=lambda directory: str(directory))


def display_run_path(directory: Path, root: Path) -> str:
    try:
        relative = directory.relative_to(root)
    except ValueError:
        return str(directory)
    return "." if relative == Path(".") else str(relative)


def directory_inventory(directory: Path) -> DirectoryInventory:
    try:
        root = directory.expanduser().resolve(strict=True)
    except OSError as error:
        raise WorkspaceError(f"Cannot inventory {directory}: {error}") from error
    if not root.is_dir():
        raise WorkspaceError(f"Cannot inventory {root}: not a directory")

    file_count = 0
    total_size_bytes = 0
    has_cell_data = False
    has_node_data = False
    manifest = hashlib.sha256()

    def raise_walk_error(error: OSError) -> None:
        raise error

    try:
        for current, child_directories, filenames in os.walk(
            root,
            topdown=True,
            onerror=raise_walk_error,
            followlinks=False,
        ):
            current_path = Path(current)
            retained_directories: list[str] = []
            for name in sorted(child_directories):
                child = current_path / name
                if child.is_symlink():
                    continue
                retained_directories.append(name)
                relative_directory = child.relative_to(root).as_posix()
                manifest.update(b"directory\0")
                manifest.update(
                    relative_directory.encode("utf-8", errors="surrogateescape")
                )
                manifest.update(b"\n")
                match = BOX_LIB_DATA_TREE.fullmatch(name)
                if match:
                    if name.lower().endswith("cell"):
                        has_cell_data = True
                    if name.lower().endswith("node"):
                        has_node_data = True
            child_directories[:] = retained_directories

            for name in sorted(filenames):
                path = current_path / name
                try:
                    details = path.lstat()
                except FileNotFoundError:
                    # A running simulation may replace a file while it is being scanned.
                    continue
                if not stat.S_ISREG(details.st_mode):
                    continue
                match = BOX_LIB_DATA_TREE.fullmatch(name)
                if match:
                    if name.lower().endswith("cell"):
                        has_cell_data = True
                    if name.lower().endswith("node"):
                        has_node_data = True
                relative = path.relative_to(root).as_posix()
                manifest.update(relative.encode("utf-8", errors="surrogateescape"))
                manifest.update(b"\0")
                manifest.update(str(details.st_size).encode("ascii"))
                manifest.update(b"\0")
                manifest.update(str(details.st_mtime_ns).encode("ascii"))
                manifest.update(b"\n")
                file_count += 1
                total_size_bytes += details.st_size
    except OSError as error:
        raise WorkspaceError(f"Cannot inventory {root}: {error}") from error

    return DirectoryInventory(
        file_count=file_count,
        total_size_bytes=total_size_bytes,
        has_cell_data=has_cell_data,
        has_node_data=has_node_data,
        manifest_digest=manifest.hexdigest(),
    )


def update_copy_location(
    client: Client,
    run_id: str,
    directory: Path,
    action: str,
    inventory: DirectoryInventory | None = None,
) -> dict[str, Any]:
    root = directory.expanduser().resolve(strict=True)
    snapshot = inventory or directory_inventory(root)
    host = socket.gethostname()
    return client.request(
        "PUT",
        f"/runs/{run_id}/copies",
        {
            "site": (
                os.environ.get("ZEPHYR_SITE")
                or os.environ.get("SLURM_CLUSTER_NAME")
                or host
            ),
            "host": host,
            "path": str(root),
            "platform": platform.platform(),
            "file_count": snapshot.file_count,
            "total_size_bytes": snapshot.total_size_bytes,
            "has_cell_data": snapshot.has_cell_data,
            "has_node_data": snapshot.has_node_data,
            "manifest_digest": snapshot.manifest_digest,
            "last_action": action,
        },
    )


def format_file_size(size: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def copy_data_label(inventory: DirectoryInventory) -> str:
    kinds = []
    if inventory.has_cell_data:
        kinds.append("cell")
    if inventory.has_node_data:
        kinds.append("node")
    return "+".join(kinds) if kinds else "copy"


def status_style(status: str) -> str:
    if status == "completed":
        return ANSI_GREEN
    if status == "failed":
        return ANSI_RED
    if status == "interrupted":
        return ANSI_YELLOW
    return ANSI_BLUE


def print_add_record(
    action: str,
    alamo_hash: str,
    status: str,
    directory: str,
    *,
    color: bool,
    detail: str | None = None,
) -> None:
    appearances = {
        "ADDED": ("●", ANSI_GREEN),
        "UPDATED": ("↻", ANSI_CYAN),
        "CURRENT": ("✓", ANSI_DIM),
        "SKIPPED": ("○", ANSI_YELLOW),
        "ERROR": ("×", ANSI_RED),
    }
    symbol, action_color = appearances[action]
    prefix = paint(f"{symbol} {action:<8}", ANSI_BOLD, action_color, enabled=color)
    identity = paint(f"{alamo_hash:>20}", ANSI_BOLD, enabled=color)
    state = paint(f"{status:<11}", status_style(status), enabled=color)
    location = paint(directory, ANSI_DIM, enabled=color)
    suffix = f"  {paint(detail, action_color, enabled=color)}" if detail else ""
    print(f"  {prefix}  {identity}  {state}  {location}{suffix}")


def fetch_sync_states(client: Client, hashes: list[str]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(hashes), 1000):
        records = client.request(
            "POST",
            "/runs/sync-state",
            {"hashes": hashes[offset : offset + 1000]},
        )
        for record in records:
            alamo_hash = str(record["alamo_hash"])
            if alamo_hash in states:
                raise WorkspaceError(f"More than one owned Zephyr run has HASH {alamo_hash}")
            states[alamo_hash] = record
    return states


def post_heartbeat(
    client: Client,
    run_id: str,
    status: str,
    progress: int | None,
) -> None:
    client.request(
        "POST",
        f"/runs/{run_id}/heartbeat",
        {
            "sequence": time.time_ns(),
            "status": status,
            "progress": progress,
            "observed_at": utcnow(),
        },
    )


def record_thermo_digest(client: Client, run_id: str, path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = file_digest(path)
    client.request("PUT", f"/runs/{run_id}/output", {"thermo_digest": digest})
    return digest


def sync_thermo_snapshot(
    client: Client,
    run_id: str,
    path: Path,
    remote_digest: str | None,
) -> bool:
    if not path.is_file():
        return False
    digest = file_digest(path)
    if digest == remote_digest:
        return False
    tail = ThermoTail(path)
    for batch in tail.poll():
        client.request("POST", f"/runs/{run_id}/thermo", batch)
        tail.ack()
    client.request("PUT", f"/runs/{run_id}/output", {"thermo_digest": digest})
    return True


def sync_existing_directory(
    client: Client,
    remote: dict[str, Any],
    directory: Path,
    status: str,
) -> list[str]:
    run_id = str(remote["id"])
    changes: list[str] = []
    text, values = read_metadata(directory)
    digest = metadata_digest(text) if text else ""
    if text and digest != remote.get("metadata_digest"):
        client.request("PUT", f"/runs/{run_id}/metadata", {"raw_text": text})
        SYNCED_METADATA_DIGESTS[run_id] = digest
        changes.append("metadata")

    output_fields = sync_run_output(client, run_id, directory, remote)
    changes.extend(output_fields)

    if sync_thermo_snapshot(
        client,
        run_id,
        directory / "thermo.dat",
        remote.get("thermo_digest"),
    ):
        changes.append("thermo")

    _, progress = derived_status(values)
    remote_progress = remote.get("progress")
    needs_heartbeat = remote.get("status") != status or remote_progress != progress
    if needs_heartbeat:
        post_heartbeat(client, run_id, status, progress)
        changes.append("status" if status in TERMINAL_STATUSES else "heartbeat")
    return changes


def cmd_add(args: argparse.Namespace) -> None:
    color = color_enabled()
    rule = "─" * 72
    patterns = args.paths or ["."]
    request_label = " ".join(patterns)
    print()
    print(
        f"  {paint('ZEPHYR', ANSI_BOLD, ANSI_CYAN, enabled=color)}"
        f"  {paint('recursive add', ANSI_DIM, enabled=color)}"
    )
    print(f"  {paint(rule, ANSI_DIM, enabled=color)}")
    print(f"  Scan   {paint(request_label, ANSI_BOLD, enabled=color)}", flush=True)
    targets = expand_add_paths(patterns)
    roots: list[Path] = []
    discovered: set[Path] = set()
    ignored: list[Path] = []
    for target in targets:
        if target.is_file() and target.name != "metadata":
            ignored.append(target)
            continue
        root, directories = discover_run_directories(target)
        roots.append(root)
        discovered.update(directories)
    directories = sorted(discovered, key=str)
    if roots:
        root = Path(os.path.commonpath([str(item) for item in roots]))
    else:
        root = Path(os.path.commonpath([str(item.parent) for item in targets]))
    print(f"  Match  {paint(str(len(targets)), ANSI_BOLD, enabled=color)} paths")
    print(f"  Root   {paint(str(root), ANSI_BOLD, enabled=color)}")
    print(f"  Found  {paint(str(len(directories)), ANSI_BOLD, enabled=color)} metadata files")
    print()

    for path in ignored:
        print_add_record(
            "SKIPPED",
            "—",
            "unknown",
            display_run_path(path, root),
            color=color,
            detail="not a directory or metadata file",
        )

    if not directories:
        print(f"  {paint('○', ANSI_YELLOW, enabled=color)} No Alamo runs found.")
        print()
        return

    added = 0
    updated = 0
    current = 0
    skipped = len(ignored)
    failed = 0
    candidates: list[tuple[Path, str, str, str]] = []
    seen_hashes: dict[str, str] = {}
    for directory in directories:
        location = display_run_path(directory, root)
        try:
            _, values = read_metadata(directory)
            alamo_hash = values.get("HASH") or values.get("Hash")
            if not alamo_hash:
                skipped += 1
                print_add_record(
                    "SKIPPED",
                    "—",
                    "unknown",
                    location,
                    color=color,
                    detail="metadata has no HASH",
                )
                continue
            first_location = seen_hashes.get(alamo_hash)
            if first_location:
                skipped += 1
                print_add_record(
                    "SKIPPED",
                    alamo_hash,
                    "duplicate",
                    location,
                    color=color,
                    detail=f"same HASH as {first_location}",
                )
                continue
            seen_hashes[alamo_hash] = location
            status, _ = derived_status(values)
            candidates.append((directory, location, alamo_hash, status))
        except (ApiError, WorkspaceError, OSError) as error:
            failed += 1
            print_add_record(
                "ERROR",
                "—",
                "failed",
                location,
                color=color,
                detail=str(error),
            )

    client = configured_client()
    print(
        f"  Check  {paint(str(len(candidates)), ANSI_BOLD, enabled=color)} fingerprints",
        flush=True,
    )
    existing_by_hash = fetch_sync_states(
        client, [candidate[2] for candidate in candidates]
    )

    def sync_candidate(candidate: tuple[Path, str, str, str]) -> tuple[bool, list[str]]:
        directory, _, alamo_hash, status = candidate
        remote = existing_by_hash.get(alamo_hash)
        if remote is not None:
            return False, sync_existing_directory(client, remote, directory, status)
        run = import_directory(client, directory, status=status)
        run_id = str(run["id"])
        sync_once(
            client,
            run_id,
            directory,
            ThermoTail(directory / "thermo.dat"),
            status_override=status,
        )
        record_thermo_digest(client, run_id, directory / "thermo.dat")
        return True, ["new run"]

    worker_count = min(4, len(candidates))
    if worker_count:
        print(
            f"  Sync   {paint(str(len(candidates)), ANSI_BOLD, enabled=color)} runs  ·  "
            f"{worker_count} concurrent connections",
            flush=True,
        )
        print()
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(sync_candidate, candidate): candidate for candidate in candidates
            }
            for future in as_completed(futures):
                _, location, alamo_hash, status = futures[future]
                try:
                    is_new, changes = future.result()
                    if is_new:
                        action = "ADDED"
                        added += 1
                    elif changes:
                        action = "UPDATED"
                        updated += 1
                    else:
                        action = "CURRENT"
                        current += 1
                    print_add_record(
                        action,
                        alamo_hash,
                        status,
                        location,
                        color=color,
                        detail=", ".join(changes) if changes else "already current",
                    )
                except (ApiError, WorkspaceError, OSError) as error:
                    failed += 1
                    print_add_record(
                        "ERROR",
                        alamo_hash,
                        "failed",
                        location,
                        color=color,
                        detail=str(error),
                    )

    print()
    print(f"  {paint(rule, ANSI_DIM, enabled=color)}")
    summary = (
        f"{len(candidates)} checked  ·  "
        f"{paint(str(added), ANSI_GREEN, ANSI_BOLD, enabled=color)} added  ·  "
        f"{paint(str(updated), ANSI_CYAN, ANSI_BOLD, enabled=color)} updated"
    )
    if current:
        summary += f"  ·  {paint(str(current), ANSI_BOLD, enabled=color)} current"
    if skipped:
        summary += f"  ·  {paint(str(skipped), ANSI_YELLOW, ANSI_BOLD, enabled=color)} skipped"
    if failed:
        summary += f"  ·  {paint(str(failed), ANSI_RED, ANSI_BOLD, enabled=color)} failed"
    print(f"  {paint('Done', ANSI_BOLD, enabled=color)}  {summary}")
    print()
    if failed:
        raise WorkspaceError(f"{failed} run{'s' if failed != 1 else ''} could not be added")


def cmd_sync(args: argparse.Namespace) -> None:
    color = color_enabled()
    rule = "─" * 72
    patterns = args.paths or ["."]
    print()
    print(
        f"  {paint('ZEPHYR', ANSI_BOLD, ANSI_CYAN, enabled=color)}"
        f"  {paint('copy inventory', ANSI_DIM, enabled=color)}"
    )
    print(f"  {paint(rule, ANSI_DIM, enabled=color)}")
    print(f"  Scan   {paint(' '.join(patterns), ANSI_BOLD, enabled=color)}", flush=True)

    targets = expand_add_paths(patterns)
    roots: list[Path] = []
    discovered: set[Path] = set()
    for target in targets:
        root, directories = discover_run_directories(target)
        roots.append(root)
        discovered.update(directories)
    directories = sorted(discovered, key=str)
    if not directories:
        raise WorkspaceError("No Alamo copies with metadata were found")
    display_root = Path(os.path.commonpath([str(root) for root in roots]))

    candidates: list[tuple[Path, str]] = []
    failed = 0
    for directory in directories:
        try:
            candidates.append((directory, require_alamo_hash(directory)))
        except (WorkspaceError, OSError) as error:
            failed += 1
            print_add_record(
                "ERROR",
                "—",
                "failed",
                display_run_path(directory, display_root),
                color=color,
                detail=str(error),
            )
    if not candidates:
        raise WorkspaceError("No copies with a valid HASH were found")

    hashes = list(dict.fromkeys(alamo_hash for _, alamo_hash in candidates))
    print(f"  Found  {len(candidates)} copies of {len(hashes)} simulations")
    print("  Inventorying every regular file; BoxLib trees are included.", flush=True)
    client = configured_client()
    runs = fetch_sync_states(client, hashes)
    for alamo_hash in hashes:
        if alamo_hash in runs:
            continue
        directory = next(path for path, value in candidates if value == alamo_hash)
        _, values = read_metadata(directory)
        status, _ = derived_status(values)
        run = import_directory(client, directory, status=status)
        runs[alamo_hash] = {
            "id": run["id"],
            "alamo_hash": alamo_hash,
        }

    synced = 0
    for directory, alamo_hash in candidates:
        location = display_run_path(directory, display_root)
        try:
            inventory = directory_inventory(directory)
            update_copy_location(
                client,
                str(runs[alamo_hash]["id"]),
                directory,
                "sync",
                inventory,
            )
            synced += 1
            details = (
                f"{inventory.file_count:,} files, "
                f"{format_file_size(inventory.total_size_bytes)}, "
                f"{copy_data_label(inventory)}"
            )
            print_add_record(
                "UPDATED",
                alamo_hash,
                "stored",
                location,
                color=color,
                detail=details,
            )
        except (ApiError, WorkspaceError, OSError) as error:
            failed += 1
            print_add_record(
                "ERROR",
                alamo_hash,
                "failed",
                location,
                color=color,
                detail=str(error),
            )

    print(f"  {paint(rule, ANSI_DIM, enabled=color)}")
    print(
        f"  {paint('Done', ANSI_BOLD, enabled=color)}  "
        f"{paint(str(synced), ANSI_CYAN, ANSI_BOLD, enabled=color)} locations updated"
    )
    print()
    if failed:
        raise WorkspaceError(f"{failed} cop{'y' if failed == 1 else 'ies'} could not be synced")


def sync_once(
    client: Client,
    run_id: str,
    directory: Path,
    tail: ThermoTail,
    status_override: str | None = None,
) -> str:
    text, values = read_metadata(directory)
    status, progress = derived_status(values)
    if status_override:
        status = status_override
    digest = metadata_digest(text) if text else ""
    prior_digest = SYNCED_METADATA_DIGESTS.get(run_id)
    if text and digest != prior_digest:
        client.request("PUT", f"/runs/{run_id}/metadata", {"raw_text": text})
        SYNCED_METADATA_DIGESTS[run_id] = digest
    sync_run_output(client, run_id, directory)
    for batch in tail.poll():
        client.request("POST", f"/runs/{run_id}/thermo", batch)
        tail.ack()
    post_heartbeat(client, run_id, status, progress)
    return status


def captured_text(path: Path, *, keep_tail: bool) -> tuple[str, bool]:
    size = path.stat().st_size
    truncated = size > MAX_CAPTURED_TEXT_BYTES
    with path.open("rb") as stream:
        if truncated and keep_tail:
            stream.seek(size - MAX_CAPTURED_TEXT_BYTES)
        data = stream.read(MAX_CAPTURED_TEXT_BYTES)
    return data.decode("utf-8", errors="replace"), truncated


def sync_run_output(
    client: Client,
    run_id: str,
    directory: Path,
    remote_digests: dict[str, Any] | None = None,
) -> list[str]:
    stdout_path = None
    for name in ("out.log", "stdout"):
        candidate = directory / name
        if candidate.is_file():
            stdout_path = candidate
            break
    sources = {
        "stdout": (stdout_path, True),
        "git_diff": (directory / "diff.patch", False),
    }
    updates: dict[str, object] = {}
    pending: dict[tuple[str, str], str] = {}
    changed: list[str] = []
    for field, (path, keep_tail) in sources.items():
        if path is None or not path.is_file():
            continue
        text, truncated = captured_text(path, keep_tail=keep_tail)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        key = (run_id, field)
        if remote_digests is not None and remote_digests.get(f"{field}_digest") == digest:
            SYNCED_OUTPUT_DIGESTS[key] = digest
            continue
        if SYNCED_OUTPUT_DIGESTS.get(key) == digest:
            continue
        updates[field] = text
        updates[f"{field}_truncated"] = truncated
        pending[key] = digest
        changed.append("stdout" if field == "stdout" else "git diff")
    if not updates:
        return []
    client.request("PUT", f"/runs/{run_id}/output", updates)
    SYNCED_OUTPUT_DIGESTS.update(pending)
    return changed


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


def post_terminal(
    client: Client,
    run_id: str,
    directory: Path,
    tail: ThermoTail,
    final: str,
) -> None:
    for attempt in range(3):
        try:
            sync_once(client, run_id, directory, tail, status_override=final)
            return
        except ApiError as error:
            if attempt == 2:
                print(f"zph: could not post terminal state: {error}", file=sys.stderr)
            else:
                time.sleep(2**attempt)


def local_watch_status(directory: Path) -> str:
    _, values = read_metadata(directory)
    status, _ = derived_status(values)
    return status


def metadata_revision(directory: Path) -> tuple[int, int] | None:
    try:
        details = (directory / "metadata").stat()
    except FileNotFoundError:
        return None
    return details.st_mtime_ns, details.st_size


def final_watch_status(directory: Path, last_status: str) -> str:
    metadata_status = local_watch_status(directory)
    if metadata_status in TERMINAL_STATUSES:
        return metadata_status
    if last_status in TERMINAL_STATUSES:
        return last_status
    return "interrupted"


def cmd_watch(args: argparse.Namespace) -> None:
    directory = Path(args.directory).resolve()
    stopping = threading.Event()

    def stop(_: int, __: object) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    requested_server = args.server or os.environ.get("ZEPHYR_SERVER")
    credentials = credentials_for_server(requested_server, login_if_missing=bool(requested_server))
    client = Client(credentials)
    initial_status = local_watch_status(directory)
    if initial_status not in TERMINAL_STATUSES:
        initial_status = "starting"
    run = import_directory(client, directory, args.name, status=initial_status)
    run_id = str(run["id"])
    alamo_hash = str(run["alamo_hash"])
    tail = ThermoTail(directory / args.thermo)
    print(f"Watching HASH {alamo_hash}; heartbeat every {args.interval:g}s")
    last_status = "running"
    heartbeat_interval = max(args.interval, WATCH_LOCAL_POLL_SECONDS)
    next_heartbeat = time.monotonic()
    previous_metadata_revision: object = object()
    local_status = "running"
    while not stopping.is_set():
        current_metadata_revision = metadata_revision(directory)
        if current_metadata_revision != previous_metadata_revision:
            local_status = local_watch_status(directory)
            previous_metadata_revision = current_metadata_revision
        if local_status in TERMINAL_STATUSES:
            last_status = local_status
            break
        if args.pid and not process_exists(args.pid):
            break

        now = time.monotonic()
        if now >= next_heartbeat:
            try:
                last_status = sync_once(client, run_id, directory, tail)
            except ApiError as error:
                print(f"zph: telemetry delayed: {error}", file=sys.stderr)
            if last_status in TERMINAL_STATUSES:
                break
            next_heartbeat = time.monotonic() + heartbeat_interval

        wait_for = min(
            WATCH_LOCAL_POLL_SECONDS,
            max(0.0, next_heartbeat - time.monotonic()),
        )
        stopping.wait(wait_for)
    final = final_watch_status(directory, last_status)
    post_terminal(client, run_id, directory, tail, final)
    print(f"Run marked {final}")


def cmd_run(args: argparse.Namespace) -> None:
    if not args.command:
        raise WorkspaceError("A command is required after `zph run --`")
    directory = Path(args.directory).resolve()
    client = configured_client()
    run = import_directory(
        client,
        directory,
        name=args.name,
        status="running",
        command=args.command,
        allow_missing_hash=True,
    )
    run_id = str(run["id"])
    tail = ThermoTail(directory / args.thermo)
    try:
        process = subprocess.Popen(args.command, cwd=directory)
    except OSError:
        post_terminal(client, run_id, directory, tail, "failed")
        raise
    print(f"Started simulation (PID {process.pid})")
    try:
        while process.poll() is None:
            try:
                sync_once(client, run_id, directory, tail, status_override="running")
            except ApiError as error:
                print(f"zph: telemetry delayed: {error}", file=sys.stderr)
            time.sleep(args.interval)
        final = "completed" if process.returncode == 0 else "failed"
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        process.wait()
        final = "interrupted"
    post_terminal(client, run_id, directory, tail, final)
    try:
        identity = f"HASH {require_alamo_hash(directory)}"
    except WorkspaceError:
        identity = "Run"
    print(f"{identity} marked {final} (exit {process.returncode})")
    if process.returncode:
        raise SystemExit(process.returncode)


def expanded_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern, recursive=True))
        if not matches and Path(pattern).exists():
            matches = [pattern]
        paths.extend(Path(match) for match in matches if Path(match).is_file())
    return list(dict.fromkeys(path.resolve() for path in paths))


def artifact_kind(path: Path) -> str:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if content_type.startswith("image/"):
        return "image"
    if path.suffix.lower() in {".csv", ".tsv", ".dat"}:
        return "table"
    if path.suffix.lower() in {".log", ".out", ".err"}:
        return "log"
    return "file"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        block = stream.read(1024 * 1024)
        while block:
            digest.update(block)
            block = stream.read(1024 * 1024)
    return digest.hexdigest()


def cmd_put(args: argparse.Namespace) -> None:
    paths = expanded_paths(args.paths)
    if not paths:
        raise WorkspaceError("No files matched")

    override = Path(args.directory).resolve() if args.directory else None
    grouped: dict[Path, list[Path]] = {}
    for path in paths:
        directory = override or path.parent
        grouped.setdefault(directory, []).append(path)

    # Validate every local association before creating or uploading any records.
    hashes = {directory: require_alamo_hash(directory) for directory in grouped}
    client = configured_client()
    color = color_enabled()
    for directory, run_paths in grouped.items():
        alamo_hash = hashes[directory]
        run = lookup_run_by_hash(client, alamo_hash)
        if run is None:
            _, values = read_metadata(directory)
            status, _ = derived_status(values)
            run = import_directory(client, directory, status=status)
        run_id = str(run["id"])
        print(
            f"{paint('HASH', ANSI_BOLD, ANSI_CYAN, enabled=color)} "
            f"{paint(alamo_hash, ANSI_BOLD, enabled=color)}  "
            f"{paint(str(directory), ANSI_DIM, enabled=color)}"
        )
        for path in run_paths:
            digest = file_digest(path)
            size = path.stat().st_size
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            initiated = client.request(
                "POST",
                f"/runs/{run_id}/artifacts/initiate",
                {"sha256": digest, "size": size, "content_type": content_type},
            )
            if not initiated["already_present"]:
                client.upload_file(initiated["upload_url"], path, initiated["headers"])
            try:
                logical_path = path.relative_to(directory).as_posix()
            except ValueError:
                logical_path = path.name
            record = client.request(
                "POST",
                f"/runs/{run_id}/artifacts/complete",
                {
                    "sha256": digest,
                    "path": logical_path,
                    "logical_name": path.name,
                    "kind": artifact_kind(path),
                },
            )
            print(f"  {record['sha256'][:12]}  {record['path']}  v{record['version']}")
        inventory = directory_inventory(directory)
        update_copy_location(client, run_id, directory, "put", inventory)
        print(
            f"  {paint('↻ location', ANSI_CYAN, enabled=color)}  "
            f"{inventory.file_count:,} files  ·  "
            f"{format_file_size(inventory.total_size_bytes)}  ·  "
            f"{copy_data_label(inventory)}"
        )


def safe_destination(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise WorkspaceError(f"Server returned an unsafe artifact path: {relative}") from None
    return target


def path_basename(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().rstrip("/\\")
    if not normalized:
        return None
    name = re.split(r"[/\\]", normalized)[-1]
    return name if name not in {"", ".", ".."} else None


def run_output_names(run: dict[str, Any]) -> list[str]:
    details = run.get("scheduler_details")
    plot_file = details.get("plot_file") if isinstance(details, dict) else None
    names = [
        name
        for name in (path_basename(run.get("output_path")), path_basename(plot_file))
        if name
    ]
    return list(dict.fromkeys(names))


def preferred_run_directory(run: dict[str, Any]) -> str:
    output_names = run_output_names(run)
    if output_names:
        return output_names[0]
    name = path_basename(run.get("name"))
    if name:
        return name
    return str(run.get("alamo_hash") or run.get("id") or "zephyr-run")


def matching_runs(runs: list[dict[str, Any]], reference: str) -> list[dict[str, Any]]:
    requested_name = path_basename(reference) or reference
    hash_matches = [run for run in runs if run.get("alamo_hash") == reference]
    if hash_matches:
        return hash_matches
    directory_matches = [run for run in runs if requested_name in run_output_names(run)]
    if directory_matches:
        return directory_matches
    return [run for run in runs if run.get("name") in {reference, requested_name}]


def merge_runs(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for run in group:
            merged[str(run.get("id"))] = run
    return list(merged.values())


def describe_run_choice(run: dict[str, Any]) -> str:
    directory = preferred_run_directory(run)
    alamo_hash = str(run.get("alamo_hash") or "no HASH")
    status = str(run.get("effective_status") or run.get("status") or "unknown")
    details = run.get("scheduler_details")
    cluster = details.get("cluster") if isinstance(details, dict) else None
    location = cluster or run.get("host") or "unknown host"
    updated = format_time(run.get("updated_at"))
    return (
        f"{directory}  |  HASH {alamo_hash}  |  {status}  |  {location}  |  {updated}\n"
        f"       {run.get('name') or directory}  |  UID {run.get('id')}"
    )


def choose_run(
    matches: list[dict[str, Any]],
    reference: str,
    *,
    interactive: bool | None = None,
    prompt: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    if not matches:
        raise WorkspaceError(f"No Zephyr run found for {reference!r}")
    if len(matches) == 1:
        return matches[0]

    if interactive is None:
        interactive = sys.stdin.isatty()
    choices = "\n".join(
        f"  [{index}] {describe_run_choice(run)}"
        for index, run in enumerate(matches, start=1)
    )
    if not interactive:
        raise WorkspaceError(
            f"More than one Zephyr run matches {reference!r}:\n{choices}\n"
            "Run zph get again with one of the listed UIDs or HASH values."
        )

    print(f"More than one Zephyr run matches {reference!r}:")
    print(choices)
    read = prompt or input
    while True:
        try:
            answer = read(f"Choose a run [1-{len(matches)}], or q to cancel: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise WorkspaceError("Restore cancelled; no files were downloaded") from None
        if answer.lower() in {"q", "quit", "cancel"}:
            raise WorkspaceError("Restore cancelled; no files were downloaded")
        try:
            selected = int(answer)
        except ValueError:
            selected = 0
        if 1 <= selected <= len(matches):
            return matches[selected - 1]
        print(f"Enter a number from 1 to {len(matches)}, or q.")


def find_run(
    client: Client,
    reference: str,
    *,
    interactive: bool | None = None,
    prompt: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    try:
        run_id = str(uuid.UUID(reference))
    except ValueError:
        run_id = None
    if run_id:
        detail = client.request("GET", f"/runs/{run_id}")
        run = detail.get("run") if isinstance(detail, dict) else None
        if not isinstance(run, dict):
            raise WorkspaceError(f"Zephyr returned an invalid run for UID {reference}")
        return run

    query = [
        ("search", reference),
        ("limit", "1000"),
        ("include_scheduler_metadata", "true"),
    ]
    searched = client.request("GET", "/runs", query=query)
    matches = matching_runs(searched, reference)
    if not matches:
        # Older records can derive their output directory solely from metadata,
        # which the server cannot filter before reading the metadata row.
        recent = client.request(
            "GET",
            "/runs",
            query=[("limit", "1000"), ("include_scheduler_metadata", "true")],
        )
        matches = matching_runs(merge_runs(searched, recent), reference)
    return choose_run(matches, reference, interactive=interactive, prompt=prompt)


def next_available_directory(path: Path) -> Path:
    base_name = path.name or "zephyr-run"
    parent = path.parent if path.name else path
    counter = 2
    while True:
        candidate = parent / f"{base_name}-{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def prepare_restore_directory(
    path: Path,
    *,
    overwrite: bool = False,
    rename: bool = False,
    interactive: bool | None = None,
    prompt: Callable[[str], str] | None = None,
) -> tuple[Path, bool]:
    if overwrite and rename:
        raise WorkspaceError("Choose only one of --overwrite or --rename")
    destination = path.expanduser().resolve()
    while destination.exists():
        is_directory = destination.is_dir()
        if overwrite:
            if not is_directory:
                raise WorkspaceError(
                    f"{destination} already exists and is not a directory; "
                    "use --output PATH or --rename"
                )
            return destination, True
        alternate = next_available_directory(destination)
        if rename:
            print(f"{destination} already exists; restoring as {alternate.name}")
            return alternate, False
        if interactive is None:
            interactive = sys.stdin.isatty()
        if not interactive:
            raise WorkspaceError(
                f"Local path {destination} already exists. Use --output PATH to choose "
                "another location, --rename to use the next available name "
                f"({alternate.name}), or --overwrite to merge into the existing directory."
            )

        print(f"Local path already exists: {destination}")
        print(f"  [1] Restore as {alternate.name}")
        print("  [2] Choose another path")
        if is_directory:
            print("  [3] Merge into it and overwrite conflicting files")
        print("  [q] Cancel")
        read = prompt or input
        default_prompt = (
            "Choose [1/2/3/q] (default 1): "
            if is_directory
            else "Choose [1/2/q] (default 1): "
        )
        try:
            answer = read(default_prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            raise WorkspaceError("Restore cancelled; no files were downloaded") from None
        if answer in {"", "1", "rename"}:
            return alternate, False
        if answer in {"2", "path"}:
            try:
                replacement = read("New destination: ").strip()
            except (EOFError, KeyboardInterrupt):
                raise WorkspaceError("Restore cancelled; no files were downloaded") from None
            if not replacement:
                print("Enter a destination path.")
                continue
            destination = Path(replacement).expanduser().resolve()
            continue
        if is_directory and answer in {"3", "overwrite", "merge"}:
            return destination, True
        if answer in {"q", "quit", "cancel"}:
            raise WorkspaceError("Restore cancelled; no files were downloaded")
        print("Choose one of the displayed options.")
    return destination, False


def write_output(path: Path, content: bytes, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise WorkspaceError(f"Refusing to overwrite {path}; pass --overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def cmd_get(args: argparse.Namespace) -> None:
    client = configured_client()
    run = find_run(client, args.reference)
    run_id = str(run["id"])
    requested_root = Path(args.output or preferred_run_directory(run))
    root, overwrite = prepare_restore_directory(
        requested_root,
        overwrite=args.overwrite,
        rename=args.rename,
    )
    print(
        f"Restoring {run.get('name') or preferred_run_directory(run)} "
        f"(HASH {run.get('alamo_hash') or '-'}, UID {run_id})"
    )
    run_data = client.request("GET", f"/runs/{run_id}")
    root.mkdir(parents=True, exist_ok=True)
    metadata = run_data.get("metadata")
    if metadata:
        write_output(root / "metadata", metadata["raw_text"].encode(), overwrite)
    write_output(
        root / "zephyr-run.json",
        (json.dumps(run_data["run"], indent=2) + "\n").encode(),
        overwrite,
    )
    thermo_lines: list[str] = []
    for series in run_data.get("thermo", []):
        columns = series["columns"]
        thermo_lines.append(" ".join(columns))
        for row in series["rows"]:
            thermo_lines.append(
                " ".join(
                    "nan" if row["values"].get(column) is None else str(row["values"][column])
                    for column in columns
                )
            )
    if thermo_lines:
        write_output(
            root / "thermo.dat",
            ("\n".join(thermo_lines) + "\n").encode(),
            overwrite,
        )
    records = client.request("GET", f"/runs/{run_id}/artifacts")
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest.setdefault(record["path"], record)
    for relative, record in latest.items():
        # Never restore identity files created by pre-0.2.2 clients.
        if relative in {"metadata", "thermo.dat", ".zephyr.json", "zephyr-run.json"}:
            continue
        downloadable = client.request(
            "GET", f"/runs/{run_id}/artifacts/{record['id']}/download"
        )
        target = safe_destination(root, relative)
        write_output(target, Client.download(downloadable["download_url"]), overwrite)
        print(f"downloaded {relative}")
    inventory = directory_inventory(root)
    update_copy_location(client, run_id, root, "get", inventory)
    print(
        f"Tracked local copy: {inventory.file_count:,} files, "
        f"{format_file_size(inventory.total_size_bytes)}, {copy_data_label(inventory)}"
    )
    print(f"Restored run into {root}")


def format_time(value: str | None) -> str:
    return value[:19].replace("T", " ") if value else "-"


def cmd_list(args: argparse.Namespace) -> None:
    client = configured_client()
    query: list[tuple[str, str]] = []
    if args.status:
        query.append(("status", args.status))
    if args.search:
        query.append(("search", args.search))
    runs = client.request("GET", "/runs", query=query)
    if args.json:
        print(json.dumps(runs, indent=2))
        return
    print(f"{'HASH':20}  {'STATUS':12}  {'UPDATED':19}  NAME")
    for run in runs:
        print(
            f"{(run['alamo_hash'] or '-'):20}  {run['effective_status'][:12]:12}  "
            f"{format_time(run['updated_at']):19}  {run['name']}"
        )


def cmd_compare(args: argparse.Namespace) -> None:
    if len(args.alamo_hashes) < 2:
        raise WorkspaceError("Comparison requires at least two HASH values")
    client = configured_client()
    run_ids = [str(find_run_by_hash(client, value)["id"]) for value in args.alamo_hashes]
    data = client.request(
        "GET", "/comparisons/runs", query=[("ids", run_id) for run_id in run_ids]
    )
    if args.json:
        print(json.dumps(data, indent=2))
        return
    keys = sorted({key for item in data["runs"] for key in item["metadata"]})
    print("field\t" + "\t".join(item["run"]["name"] for item in data["runs"]))
    for key in keys:
        values = [str(item["metadata"].get(key, "")) for item in data["runs"]]
        if len(set(values)) > 1 or args.all:
            print(f"{key}\t" + "\t".join(values))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="zph", description="Zephyr client for Alamo runs")
    result.add_argument("--version", action="version", version=f"zph {__version__}")
    commands = result.add_subparsers(dest="subcommand", required=True)

    login = commands.add_parser("login", help="save and verify server credentials")
    login.add_argument("server")
    login.add_argument("--name", help="name shown for this device")
    login.add_argument("--token", help="use an existing API token instead of browser login")
    login.set_defaults(handler=cmd_login)

    import_command = commands.add_parser("import", help="register an existing Alamo run")
    import_command.add_argument("directory", nargs="?", default=".")
    import_command.add_argument("--name")
    import_command.add_argument(
        "--status",
        choices=["starting", "running", "completed", "failed", "interrupted"],
        default="completed",
    )
    import_command.set_defaults(handler=cmd_import)

    add = commands.add_parser(
        "add",
        help="recursively register Alamo runs beneath a path",
        description=(
            "Discover Alamo metadata files recursively and add or update their Zephyr records."
        ),
    )
    add.add_argument(
        "paths",
        metavar="PATH",
        nargs="*",
        help="directories, metadata files, or wildcard patterns (default: current directory)",
    )
    add.set_defaults(handler=cmd_add)

    sync = commands.add_parser(
        "sync",
        help="recursively refresh local copy locations and file inventories",
        description=(
            "Find every Alamo metadata directory beneath PATH and refresh its local "
            "copy location, file count, size, filename fingerprint, and BoxLib data flags."
        ),
    )
    sync.add_argument(
        "paths",
        metavar="PATH",
        nargs="*",
        help="directories, metadata files, or wildcard patterns (default: current directory)",
    )
    sync.set_defaults(handler=cmd_sync)

    watch = commands.add_parser("watch", help="post heartbeats, metadata, and thermo data")
    watch.add_argument("directory", nargs="?", default=".")
    watch.add_argument("--name")
    watch.add_argument("--pid", type=int, help="stop when this local PID exits")
    watch.add_argument("--interval", type=float, default=30.0)
    watch.add_argument("--thermo", default="thermo.dat")
    watch.add_argument("--server", help="connect to this server if zph is not configured")
    watch.set_defaults(handler=cmd_watch)

    run = commands.add_parser("run", help="run a command and monitor it")
    run.add_argument("--directory", default=".")
    run.add_argument("--name")
    run.add_argument("--interval", type=float, default=30.0)
    run.add_argument("--thermo", default="thermo.dat")
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(handler=cmd_run)

    put = commands.add_parser(
        "put",
        help="upload artifacts using the metadata beside each file",
    )
    put.add_argument("paths", nargs="+")
    put.add_argument(
        "--directory",
        help="use this run directory for every file instead of each file's directory",
    )
    put.set_defaults(handler=cmd_put)

    get = commands.add_parser(
        "get",
        help="restore a run by output-directory name, HASH, or UID",
    )
    get.add_argument("reference", metavar="DIRECTORY|HASH|UID")
    get.add_argument("--output", "-o", help="restore into this local directory")
    collision = get.add_mutually_exclusive_group()
    collision.add_argument(
        "--rename",
        action="store_true",
        help="use the next available directory name if the destination exists",
    )
    collision.add_argument(
        "--overwrite",
        action="store_true",
        help="merge into an existing directory and overwrite conflicting files",
    )
    get.set_defaults(handler=cmd_get)

    listing = commands.add_parser("list", help="list accessible runs")
    listing.add_argument("--status")
    listing.add_argument("--search")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(handler=cmd_list)

    compare = commands.add_parser("compare", help="compare metadata across runs")
    compare.add_argument("alamo_hashes", metavar="HASH", nargs="+")
    compare.add_argument("--all", action="store_true", help="include identical metadata")
    compare.add_argument("--json", action="store_true")
    compare.set_defaults(handler=cmd_compare)
    return result


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if getattr(args, "command", None) and args.command[0] == "--":
        args.command = args.command[1:]
    try:
        args.handler(args)
    except (ApiError, ConfigError, WorkspaceError, OSError) as error:
        print(f"zph: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
