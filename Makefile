.PHONY: dev infra migrate test lint build

infra:
	docker compose up -d postgres minio minio-init

migrate:
	alembic -c server/alembic.ini upgrade head

dev:
	@echo "Run 'uvicorn zephyr_server.main:app --reload' and 'npm --prefix web run dev' in separate terminals."

test:
	pytest server/tests cli/tests
	npm --prefix web test

lint:
	ruff check server cli
	npm --prefix web run lint
	npm --prefix web run typecheck

build:
	docker build -t zephyr:local .
