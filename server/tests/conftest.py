import os
from pathlib import Path

TEST_DATABASE = Path("/tmp") / f"zephyr-tests-{os.getpid()}.db"

os.environ["ZEPHYR_ENV"] = "development"
os.environ["ZEPHYR_DEV_AUTH"] = "true"
os.environ["ZEPHYR_DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DATABASE}"
os.environ["ZEPHYR_SESSION_SECRET"] = "test-session-secret-that-is-long-enough"
os.environ["ZEPHYR_TOKEN_PEPPER"] = "test-token-pepper-that-is-also-long-enough"
