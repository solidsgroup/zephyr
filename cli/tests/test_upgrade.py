import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from zephyr_cli import main


def test_upgrade_parser_does_not_require_a_subcommand() -> None:
    args = main.parser().parse_args(["--upgrade"])

    assert args.upgrade is True
    assert args.subcommand is None


def test_upgrade_uses_user_install_for_system_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main.sys, "prefix", "/usr")
    monkeypatch.setattr(main.sys, "base_prefix", "/usr")
    monkeypatch.delattr(main.sys, "real_prefix", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)

    command = main.pip_upgrade_command()

    assert command[:6] == [
        main.sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--no-deps",
    ]
    assert "--user" in command
    assert command[-1] == main.ZPH_SOURCE_ARCHIVE
    assert command[-1] == "https://zephyr.solids.group/downloads/zph-latest.tar.gz"


def test_upgrade_does_not_use_user_install_in_virtual_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main.sys, "prefix", "/scratch/venv")
    monkeypatch.setattr(main.sys, "base_prefix", "/usr")
    monkeypatch.delattr(main.sys, "real_prefix", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)

    assert "--user" not in main.pip_upgrade_command()


def test_upgrade_runs_pip_and_reports_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = ["/usr/bin/python3", "-m", "pip", "install", "zph"]
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(main, "pip_upgrade_command", lambda: command)
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda value, check: calls.append((value, check))
        or subprocess.CompletedProcess(value, 0),
    )

    main.cmd_upgrade()

    assert calls == [(command, True)]
    output = capsys.readouterr().out
    assert "/usr/bin/python3 -m pip install zph" in output
    assert "upgraded successfully" in output


def test_main_dispatches_upgrade_without_a_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(main, "cmd_upgrade", lambda: calls.append(True))

    main.main(["--upgrade"])

    assert calls == [True]


def test_cluster_distribution_contains_an_installable_package(tmp_path: Path) -> None:
    cli_root = Path(__file__).resolve().parents[1]
    distribution = tmp_path / "zph-latest.tar.gz"

    subprocess.run(
        [sys.executable, str(cli_root / "build_sdist.py"), str(distribution)],
        check=True,
    )

    with tarfile.open(distribution, "r:gz") as archive:
        names = set(archive.getnames())
    assert "zph-0.5.4/setup.py" in names
    assert "zph-0.5.4/src/zephyr_cli/main.py" in names
