FROM node:20-alpine AS web-build
WORKDIR /build/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ZEPHYR_STATIC_DIR=/app/static
WORKDIR /app
COPY server/pyproject.toml /tmp/server/pyproject.toml
COPY server/src /tmp/server/src
RUN pip install --no-cache-dir /tmp/server
COPY server/alembic.ini /app/alembic.ini
COPY server/alembic /app/alembic
COPY --from=web-build /build/web/dist /app/static
EXPOSE 8000
CMD ["uvicorn", "zephyr_server.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
