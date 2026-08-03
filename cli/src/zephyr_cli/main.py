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
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .alamo import ThermoTail, derived_status, metadata_digest, metadata_values
from .client import ApiError, Client, api_request
from .config import ConfigError, Credentials, normalize_server_url
from .workspace import WorkspaceError

TERMINAL_STATUSES = {"completed", "failed", "interrupted"}
WATCH_LOCAL_POLL_SECONDS = 0.25
MAX_CAPTURED_TEXT_BYTES = 1_000_000

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_BLUE = "\033[34m"
ANSI_CYAN = "\033[36m"


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
        url = f"https://{url.removeprefix('ssh://git@')}"
    return url.removesuffix(".git").rstrip("/") or None


def scheduler_job_id() -> str | None:
    for name in ("SLURM_JOB_ID", "PBS_JOBID", "LSB_JOBID", "JOB_ID"):
        if value := os.environ.get(name):
            return f"{name}={value}"
    return None


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
    payload = {
        "alamo_hash": alamo_hash,
        "name": name or values.get("Title") or directory.name,
        "status": status,
        "started_at": utcnow(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "scheduler_job_id": scheduler_job_id(),
        "git_commit": values.get("Git_commit_hash") or git_commit(directory),
        "git_repository_url": git_repository_url(directory),
        "command": command or [],
    }
    run = client.request("POST", "/runs", payload)
    if text:
        client.request("PUT", f"/runs/{run['id']}/metadata", {"raw_text": text})
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
            raise WorkspaceError(f"{target} is not an ALAMO metadata file")
        return target.parent, [target.parent]
    if not target.is_dir():
        raise WorkspaceError(f"{target} is not a directory")

    try:
        directories = {
            metadata.parent.resolve()
            for metadata in target.rglob("metadata")
            if metadata.is_file()
        }
    except OSError as error:
        raise WorkspaceError(f"Cannot scan {target}: {error}") from error
    return target, sorted(directories, key=lambda directory: str(directory))


def display_run_path(directory: Path, root: Path) -> str:
    try:
        relative = directory.relative_to(root)
    except ValueError:
        return str(directory)
    return "." if relative == Path(".") else str(relative)


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
        print(f"  {paint('○', ANSI_YELLOW, enabled=color)} No ALAMO runs found.")
        print()
        return

    client = configured_client()
    try:
        owner_id = str(client.request("GET", "/auth/me")["user"]["id"])
    except (KeyError, TypeError) as error:
        raise ApiError("Zephyr returned an invalid user record") from error

    added = 0
    updated = 0
    skipped = len(ignored)
    failed = 0
    for directory in directories:
        location = display_run_path(directory, root)
        alamo_hash = ""
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

            existing = lookup_owned_run_by_hash(client, alamo_hash, owner_id)
            status, _ = derived_status(values)
            run = import_directory(client, directory, status=status)
            run_id = str(run["id"])
            sync_once(
                client,
                run_id,
                directory,
                ThermoTail(directory / "thermo.dat"),
                status_override=status,
            )
            action = "UPDATED" if existing else "ADDED"
            if existing:
                updated += 1
            else:
                added += 1
            print_add_record(action, alamo_hash, status, location, color=color)
        except (ApiError, WorkspaceError, OSError) as error:
            failed += 1
            print_add_record(
                "ERROR",
                alamo_hash or "—",
                "failed",
                location,
                color=color,
                detail=str(error),
            )

    processed = added + updated
    print()
    print(f"  {paint(rule, ANSI_DIM, enabled=color)}")
    summary = (
        f"{processed} processed  ·  "
        f"{paint(str(added), ANSI_GREEN, ANSI_BOLD, enabled=color)} added  ·  "
        f"{paint(str(updated), ANSI_CYAN, ANSI_BOLD, enabled=color)} updated"
    )
    if skipped:
        summary += f"  ·  {paint(str(skipped), ANSI_YELLOW, ANSI_BOLD, enabled=color)} skipped"
    if failed:
        summary += f"  ·  {paint(str(failed), ANSI_RED, ANSI_BOLD, enabled=color)} failed"
    print(f"  {paint('Done', ANSI_BOLD, enabled=color)}  {summary}")
    print()
    if failed:
        raise WorkspaceError(f"{failed} run{'s' if failed != 1 else ''} could not be added")


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
    prior_digest = getattr(sync_once, "metadata_digest", {}).get(run_id)
    if text and digest != prior_digest:
        client.request("PUT", f"/runs/{run_id}/metadata", {"raw_text": text})
        digests = getattr(sync_once, "metadata_digest", {})
        digests[run_id] = digest
        sync_once.metadata_digest = digests
    sync_run_output(client, run_id, directory)
    for batch in tail.poll():
        client.request("POST", f"/runs/{run_id}/thermo", batch)
        tail.ack()
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
    return status


def captured_text(path: Path, *, keep_tail: bool) -> tuple[str, bool]:
    size = path.stat().st_size
    truncated = size > MAX_CAPTURED_TEXT_BYTES
    with path.open("rb") as stream:
        if truncated and keep_tail:
            stream.seek(size - MAX_CAPTURED_TEXT_BYTES)
        data = stream.read(MAX_CAPTURED_TEXT_BYTES)
    return data.decode("utf-8", errors="replace"), truncated


def sync_run_output(client: Client, run_id: str, directory: Path) -> None:
    stdout_path = next(
        (path for name in ("out.log", "stdout") if (path := directory / name).is_file()),
        None,
    )
    sources = {
        "stdout": (stdout_path, True),
        "git_diff": (directory / "diff.patch", False),
    }
    digests = getattr(sync_run_output, "digests", {})
    updates: dict[str, object] = {}
    pending: dict[tuple[str, str], str] = {}
    for field, (path, keep_tail) in sources.items():
        if path is None or not path.is_file():
            continue
        text, truncated = captured_text(path, keep_tail=keep_tail)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        key = (run_id, field)
        if digests.get(key) == digest:
            continue
        updates[field] = text
        updates[f"{field}_truncated"] = truncated
        pending[key] = digest
    if not updates:
        return
    client.request("PUT", f"/runs/{run_id}/output", updates)
    digests.update(pending)
    sync_run_output.digests = digests


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
        while block := stream.read(1024 * 1024):
            digest.update(block)
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


def safe_destination(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise WorkspaceError(f"Server returned an unsafe artifact path: {relative}")
    return target


def write_output(path: Path, content: bytes, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise WorkspaceError(f"Refusing to overwrite {path}; pass --overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def cmd_get(args: argparse.Namespace) -> None:
    client = configured_client()
    run = find_run_by_hash(client, args.alamo_hash)
    run_id = str(run["id"])
    run_data = client.request("GET", f"/runs/{run_id}")
    root = Path(args.output or args.alamo_hash).resolve()
    root.mkdir(parents=True, exist_ok=True)
    metadata = run_data.get("metadata")
    if metadata:
        write_output(root / "metadata", metadata["raw_text"].encode(), args.overwrite)
    write_output(
        root / "zephyr-run.json",
        (json.dumps(run_data["run"], indent=2) + "\n").encode(),
        args.overwrite,
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
            args.overwrite,
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
        write_output(target, Client.download(downloadable["download_url"]), args.overwrite)
        print(f"downloaded {relative}")
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
    result = argparse.ArgumentParser(prog="zph", description="Zephyr client for ALAMO runs")
    result.add_argument("--version", action="version", version=f"zph {__version__}")
    commands = result.add_subparsers(dest="subcommand", required=True)

    login = commands.add_parser("login", help="save and verify server credentials")
    login.add_argument("server")
    login.add_argument("--name", help="name shown for this device")
    login.add_argument("--token", help="use an existing API token instead of browser login")
    login.set_defaults(handler=cmd_login)

    import_command = commands.add_parser("import", help="register an existing ALAMO run")
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
        help="recursively register ALAMO runs beneath a path",
        description=(
            "Discover ALAMO metadata files recursively and add or update their Zephyr records."
        ),
    )
    add.add_argument(
        "paths",
        metavar="PATH",
        nargs="*",
        help="directories, metadata files, or wildcard patterns (default: current directory)",
    )
    add.set_defaults(handler=cmd_add)

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

    get = commands.add_parser("get", help="restore a run and its latest artifacts")
    get.add_argument("alamo_hash", metavar="HASH")
    get.add_argument("--output", "-o")
    get.add_argument("--overwrite", action="store_true")
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
