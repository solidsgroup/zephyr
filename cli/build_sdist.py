#!/usr/bin/env python3
"""Build a minimal, dependency-free zph source distribution."""

import argparse
import re
import tarfile
from pathlib import Path


def package_version(root):
    source = (root / "src" / "zephyr_cli" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)
    if not match:
        raise RuntimeError("Cannot determine zph version")
    return match.group(1)


def included_files(root):
    for relative in (Path("README.md"), Path("setup.py")):
        yield root / relative, relative
    for source in sorted((root / "src").rglob("*.py")):
        if "__pycache__" not in source.parts:
            yield source, source.relative_to(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    version = package_version(root)
    prefix = Path(f"zph-{version}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, "w:gz") as archive:
        for source, relative in included_files(root):
            archive.add(source, arcname=str(prefix / relative), recursive=False)
    print(f"Built zph {version} source distribution at {args.output}")


if __name__ == "__main__":
    main()
