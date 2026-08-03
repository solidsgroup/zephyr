# Zephyr

**Z**ero-effort **E**xecution **P**rovenance and **H**ealth for **Y**our ALAMO **R**uns.

Zephyr is the run registry and results workspace built for
[ALAMO](https://github.com/solidsgroup/alamo). It keeps track of where a
simulation ran, the source revision and platform it used, whether it is still
healthy, its `metadata` and `thermo.dat` records, and the files worth keeping.
The interface takes inspiration from Weights & Biases, but the data model and
workflow are specific to computational solid mechanics.

This repository contains two separately packaged products behind one protocol:

- `server/` and `web/`: the hosted FastAPI/React service at
  `zephyr.solids.group`.
- `cli/`: the dependency-free Python client installed as `zph`.

Neither package imports the other. Their only shared boundary is the versioned
HTTP/JSON contract under `/api/v1`.

## What works in the first release

- live run registry with heartbeats and stale-run detection;
- ALAMO metadata parsing and append-only `thermo.dat` segments;
- W&B-style run table, run detail, plots, and multi-run comparisons;
- content-addressed artifacts in any S3-compatible object store;
- private, group, and public projects with per-user sharing;
- Google OIDC restricted to `@solids.group` plus revocable CLI tokens;
- one-command artifact upload and complete local run restoration.

## CLI workflow

Create a token in **Settings → CLI tokens**, then connect once:

```console
pipx install zph
zph login https://zephyr.solids.group
```

Register a completed directory, monitor an existing process, or let `zph`
wrap a new execution:

```console
zph import /scratch/run-0042
zph watch /scratch/run-0042 --pid 38192
zph run --directory /scratch/run-0043 -- alamo input
```

Upload and restore results:

```console
zph put '*.png' 'profiles/*.csv'
zph list --status running
zph compare RUN_ID_A RUN_ID_B
zph get RUN_ID --output restored-run
```

`ZEPHYR_SERVER` and `ZEPHYR_TOKEN` override the credential file for jobs and
CI. Local run identity lives in `.zephyr.json`; credentials never do.

## Local development

Requirements are Python 3.11+, Node 20+, and Docker.

```console
cp .env.example .env
make infra
python -m venv .venv
. .venv/bin/activate
pip install -e 'server[dev]' -e 'cli[dev]'
npm install --prefix web
make migrate
uvicorn zephyr_server.main:app --reload
```

In a second terminal, run `npm --prefix web run dev` and visit
`http://localhost:5173`. Development login is enabled by `.env.example`.

Run all checks with:

```console
make test
make lint
npm --prefix web run build
```

## Architecture and operations

See [architecture](docs/architecture.md),
[ALAMO integration](docs/alamo-integration.md), and
[Render deployment](docs/deployment.md). The OpenAPI document is served at
`/docs` and protocol compatibility is advertised by `/api/v1/meta`.

Zephyr is intentionally not a scientific postprocessor. ALAMO or a user's
workflow creates scientific tables and images; Zephyr indexes, visualizes,
compares, shares, and preserves those outputs.

## Status

Zephyr is alpha software. Database migrations and protocol compatibility are
maintained from the first hosted deployment, but operational backups must be
configured before the service is treated as the definitive archive.

Licensed under the [MIT License](LICENSE).
