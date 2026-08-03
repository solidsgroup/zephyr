from __future__ import annotations

import os
from pathlib import Path

from alembic.config import Config

from alembic import command

DEFAULT_CONFIG_PATH = Path("/app/alembic.ini")


def main() -> None:
    """Upgrade the configured database without relying on shell arguments."""
    config_path = Path(os.environ.get("ZEPHYR_ALEMBIC_CONFIG", DEFAULT_CONFIG_PATH))
    if not config_path.is_file():
        raise FileNotFoundError(f"Alembic configuration not found: {config_path}")

    command.upgrade(Config(str(config_path)), "head")
