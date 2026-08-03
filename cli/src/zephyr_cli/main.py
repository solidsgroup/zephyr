from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import mimetypes
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from . import __version__
from .alamo import ThermoTail, derived_status, metadata_digest, metadata_values
from .client import ApiError, Client, api_request
from .config import ConfigError, Credentials, normalize_server_url
from .workspace import RunMarker, WorkspaceError


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


def client_for_workspace(directory: Path | None = None) -> tuple[Client, RunMarker | None]:
    credentials = credentials_for_server()
    marker = RunMarker.load(directory) if directory is not None else None
    if marker and marker.server.rstrip("/") != credentials.server.rstrip("/"):
        raise WorkspaceError(
            f"This run belongs to {marker.server}, but zph is configured for {credentials.server}"
        )
    return Client(credentials), marker


def read_metadata(directory: Path) -> tuple[str, dict[str, str]]:
    path = directory / "metadata"
    if not path.exists():
        return "", {}
    text = path.read_text(encoding="utf-8", errors="replace")
    return text, metadata_values(text)


def import_directory(
    client: Client,
    directory: Path,
    name: str | None = None,
    status: str = "starting",
    command: list[str] | None = None,
) -> dict[str, Any]:
    directory = directory.resolve()
    text, values = read_metadata(directory)
    alamo_hash = values.get("HASH") or values.get("Hash")
    payload = {
        "alamo_hash": alamo_hash,
        "name": name or values.get("Title") or directory.name,
        "status": status,
        "started_at": utcnow(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "scheduler_job_id": scheduler_job_id(),
        "git_commit": values.get("Git_commit_hash") or git_commit(directory),
        "command": command or [],
    }
    run = client.request("POST", "/runs", payload)
    marker = RunMarker(run_id=run["id"], server=client.server)
    marker.save(directory)
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
    client, _ = client_for_workspace()
    run = import_directory(client, directory, args.name, status=args.status)
    print(f"{run['id']}  {run['name']}")


def sync_once(
    client: Client,
    marker: RunMarker,
    directory: Path,
    tail: ThermoTail,
    status_override: str | None = None,
) -> str:
    text, values = read_metadata(directory)
    status, progress = derived_status(values)
    if status_override:
        status = status_override
    digest = metadata_digest(text) if text else ""
    prior_digest = getattr(sync_once, "metadata_digest", {}).get(marker.run_id)
    if text and digest != prior_digest:
        client.request("PUT", f"/runs/{marker.run_id}/metadata", {"raw_text": text})
        digests = getattr(sync_once, "metadata_digest", {})
        digests[marker.run_id] = digest
        sync_once.metadata_digest = digests
    for batch in tail.poll():
        client.request("POST", f"/runs/{marker.run_id}/thermo", batch)
        tail.ack()
    client.request(
        "POST",
        f"/runs/{marker.run_id}/heartbeat",
        {
            "sequence": time.time_ns(),
            "status": status,
            "progress": progress,
            "observed_at": utcnow(),
        },
    )
    return status


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
    marker: RunMarker,
    directory: Path,
    tail: ThermoTail,
    final: str,
) -> None:
    for attempt in range(3):
        try:
            sync_once(client, marker, directory, tail, status_override=final)
            return
        except ApiError as error:
            if attempt == 2:
                print(f"zph: could not post terminal state: {error}", file=sys.stderr)
            else:
                time.sleep(2**attempt)


def final_watch_status(directory: Path, last_status: str) -> str:
    _, values = read_metadata(directory)
    metadata_status, _ = derived_status(values)
    if metadata_status in {"completed", "failed"}:
        return metadata_status
    if last_status in {"completed", "failed"}:
        return last_status
    return "interrupted"


def cmd_watch(args: argparse.Namespace) -> None:
    directory = Path(args.directory).resolve()
    requested_server = args.server or os.environ.get("ZEPHYR_SERVER")
    credentials = credentials_for_server(requested_server, login_if_missing=bool(requested_server))
    client = Client(credentials)
    try:
        marker = RunMarker.load(directory)
    except WorkspaceError:
        import_directory(client, directory, args.name)
        marker = RunMarker.load(directory)
    if marker.server.rstrip("/") != credentials.server.rstrip("/"):
        raise WorkspaceError(
            f"This run belongs to {marker.server}, but zph is configured for {credentials.server}"
        )
    assert marker is not None
    tail = ThermoTail(directory / args.thermo)
    stopping = threading.Event()

    def stop(_: int, __: object) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"Watching {marker.run_id}; heartbeat every {args.interval:g}s")
    last_status = "running"
    while not stopping.is_set():
        try:
            last_status = sync_once(client, marker, directory, tail)
        except ApiError as error:
            print(f"zph: telemetry delayed: {error}", file=sys.stderr)
        if args.pid and not process_exists(args.pid):
            stopping.set()
            break
        if last_status in {"completed", "failed", "interrupted"}:
            break
        stopping.wait(args.interval)
    final = final_watch_status(directory, last_status)
    post_terminal(client, marker, directory, tail, final)
    print(f"Run marked {final}")


def cmd_run(args: argparse.Namespace) -> None:
    if not args.command:
        raise WorkspaceError("A command is required after `zph run --`")
    directory = Path(args.directory).resolve()
    client, _ = client_for_workspace()
    run = import_directory(
        client,
        directory,
        name=args.name,
        status="running",
        command=args.command,
    )
    marker = RunMarker(run_id=run["id"], server=client.server)
    tail = ThermoTail(directory / args.thermo)
    try:
        process = subprocess.Popen(args.command, cwd=directory)
    except OSError:
        post_terminal(client, marker, directory, tail, "failed")
        raise
    print(f"Started {run['id']} (PID {process.pid})")
    try:
        while process.poll() is None:
            try:
                sync_once(client, marker, directory, tail, status_override="running")
            except ApiError as error:
                print(f"zph: telemetry delayed: {error}", file=sys.stderr)
            time.sleep(args.interval)
        final = "completed" if process.returncode == 0 else "failed"
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        process.wait()
        final = "interrupted"
    post_terminal(client, marker, directory, tail, final)
    print(f"Run marked {final} (exit {process.returncode})")
    if process.returncode:
        raise SystemExit(process.returncode)


def expanded_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matches = glob.glob(pattern, recursive=True)
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
    directory = Path(args.directory).resolve()
    client, marker = client_for_workspace(directory)
    assert marker is not None
    paths = expanded_paths(args.paths)
    if not paths:
        raise WorkspaceError("No files matched")
    for path in paths:
        digest = file_digest(path)
        size = path.stat().st_size
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        initiated = client.request(
            "POST",
            f"/runs/{marker.run_id}/artifacts/initiate",
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
            f"/runs/{marker.run_id}/artifacts/complete",
            {
                "sha256": digest,
                "path": logical_path,
                "logical_name": path.name,
                "kind": artifact_kind(path),
            },
        )
        print(f"{record['sha256'][:12]}  {record['path']}  v{record['version']}")


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
    client, _ = client_for_workspace()
    run_data = client.request("GET", f"/runs/{args.run_id}")
    root = Path(args.output or args.run_id).resolve()
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
    records = client.request("GET", f"/runs/{args.run_id}/artifacts")
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest.setdefault(record["path"], record)
    for relative, record in latest.items():
        if relative in {"metadata", "thermo.dat", ".zephyr.json", "zephyr-run.json"}:
            continue
        downloadable = client.request(
            "GET", f"/runs/{args.run_id}/artifacts/{record['id']}/download"
        )
        target = safe_destination(root, relative)
        write_output(target, Client.download(downloadable["download_url"]), args.overwrite)
        print(f"downloaded {relative}")
    RunMarker(run_id=args.run_id, server=client.server).save(root)
    print(f"Restored run into {root}")


def format_time(value: str | None) -> str:
    return value[:19].replace("T", " ") if value else "-"


def cmd_list(args: argparse.Namespace) -> None:
    client, _ = client_for_workspace()
    query: list[tuple[str, str]] = []
    if args.status:
        query.append(("status", args.status))
    if args.search:
        query.append(("search", args.search))
    runs = client.request("GET", "/runs", query=query)
    if args.json:
        print(json.dumps(runs, indent=2))
        return
    print(f"{'ID':8}  {'STATUS':12}  {'UPDATED':19}  NAME")
    for run in runs:
        print(
            f"{run['id'][:8]}  {run['effective_status'][:12]:12}  "
            f"{format_time(run['updated_at']):19}  {run['name']}"
        )


def cmd_compare(args: argparse.Namespace) -> None:
    if len(args.run_ids) < 2:
        raise WorkspaceError("Comparison requires at least two run IDs")
    client, _ = client_for_workspace()
    data = client.request(
        "GET", "/comparisons/runs", query=[("ids", run_id) for run_id in args.run_ids]
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

    put = commands.add_parser("put", help="upload artifacts for the current run")
    put.add_argument("paths", nargs="+")
    put.add_argument("--directory", default=".")
    put.set_defaults(handler=cmd_put)

    get = commands.add_parser("get", help="restore a run and its latest artifacts")
    get.add_argument("run_id")
    get.add_argument("--output", "-o")
    get.add_argument("--overwrite", action="store_true")
    get.set_defaults(handler=cmd_get)

    listing = commands.add_parser("list", help="list accessible runs")
    listing.add_argument("--status")
    listing.add_argument("--search")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(handler=cmd_list)

    compare = commands.add_parser("compare", help="compare metadata across runs")
    compare.add_argument("run_ids", nargs="+")
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
