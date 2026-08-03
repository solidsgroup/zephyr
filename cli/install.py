#!/usr/bin/env python3
"""Install zph as a self-contained standard-library zip application."""

import argparse
import os
import sys
import zipapp
from pathlib import Path


def include(path):
    return (
        "__pycache__" not in path.parts
        and not any(part.endswith(".egg-info") for part in path.parts)
        and path.suffix not in {".pyc", ".pyo"}
    )


def main():
    # Keep a friendly error when this standalone installer is invoked with 3.6.
    if sys.version_info < (3, 7):  # noqa: UP036
        raise SystemExit("zph requires Python 3.7 or newer")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prefix",
        default=str(Path.home() / ".local"),
        help="installation prefix (default: ~/.local)",
    )
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / "src"
    target = Path(args.prefix).expanduser().resolve() / "bin" / "zph"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(".zph.installing")
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
    zipapp.create_archive(
        source,
        target=temporary,
        interpreter="/usr/bin/env python3",
        main="zephyr_cli.main:main",
        filter=include,
    )
    temporary.chmod(0o755)
    os.replace(str(temporary), str(target))
    print(f"Installed zph to {target}")
    if str(target.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Add {target.parent} to PATH before running zph.")


if __name__ == "__main__":
    main()
