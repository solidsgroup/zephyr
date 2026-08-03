from pathlib import Path

import pytest
from alembic.config import Config

from zephyr_server import migrate
from zephyr_server.config import database_url_from_environment


def test_migrate_upgrades_to_head(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "alembic.ini"
    config_path.write_text("[alembic]\n")
    monkeypatch.setenv("ZEPHYR_ALEMBIC_CONFIG", str(config_path))

    invocation: tuple[Config, str] | None = None

    def record_upgrade(config: Config, revision: str) -> None:
        nonlocal invocation
        invocation = (config, revision)

    monkeypatch.setattr("zephyr_server.migrate.command.upgrade", record_upgrade)

    migrate.main()

    assert invocation is not None
    assert invocation[0].config_file_name == str(config_path)
    assert invocation[1] == "head"


def test_migrate_reports_missing_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "missing.ini"
    monkeypatch.setenv("ZEPHYR_ALEMBIC_CONFIG", str(config_path))

    with pytest.raises(FileNotFoundError, match="Alembic configuration not found"):
        migrate.main()


def test_database_configuration_does_not_require_app_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZEPHYR_ENV", "production")
    monkeypatch.setenv("ZEPHYR_DATABASE_URL", "postgresql://user:pass@db/zephyr")
    monkeypatch.delenv("ZEPHYR_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZEPHYR_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", raising=False)

    assert database_url_from_environment() == "postgresql+asyncpg://user:pass@db/zephyr"
