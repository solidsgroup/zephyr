# Contributing

Keep the server, browser, and CLI independently packageable. New behavior that
crosses their boundary begins as an additive `/api/v1` contract change and must
work with retries and out-of-order telemetry.

Before opening a change, run `make test`, `make lint`, and
`npm --prefix web run build`. Include an Alembic migration for every catalog
schema change. Never commit `.env`, CLI credentials, simulation data, or signed
object URLs.
