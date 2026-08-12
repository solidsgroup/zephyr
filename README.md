# Zephyr

**Z**ero-effort **E**xecution **P**rovenance and **H**ealth for **Y**our Alamo **R**uns.

Zephyr is the run registry and results workspace built for
[Alamo](https://github.com/solidsgroup/alamo). It keeps track of where a
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
- Alamo metadata parsing and append-only `thermo.dat` segments;
- W&B-style run table, run detail, plots, and multi-run comparisons;
- stacked artifact previews with a user-selected image thumbnail for each run;
- an inventory of every known on-premises copy, including file counts and
  BoxLib cell/node data markers;
- content-addressed working artifacts in a group-owned Google Shared Drive;
- private, group, and public projects with per-user sharing;
- Google OIDC restricted to `@solids.group` plus revocable CLI tokens;
- one-command artifact upload and complete local run restoration.

## CLI workflow

Install the CLI and connect once:

```console
python3 -m pip install --user --upgrade \
  'https://github.com/solidsgroup/zephyr/archive/refs/heads/master.zip#subdirectory=cli'
export PATH="$HOME/.local/bin:$PATH"
zph login https://zephyr.solids.group
```

This regular-pip installation is suitable for clusters and does not require
`pipx` or `git`. Omit `--user` inside an activated virtual or Conda environment.
After the one-time installation above, update from the command line with
`zph --upgrade`. The CLI supports Python 3.7+ and has no runtime dependencies.
On a cluster without usable packaging tools, `python3 cli/install.py` produces
a single `~/.local/bin/zph` executable without using `pip`, `pipx`, `setuptools`,
or `wheel`; `zph --upgrade` can later replace it with the regular-pip install.

`zph` prints a ten-minute browser link and tries to open it automatically. Sign
in with Google in the browser; the terminal receives and stores a revocable CLI
token without asking you to copy a secret.

Register a completed directory, monitor an existing process, or let `zph`
wrap a new execution:

```console
zph import /scratch/run-0042
zph add /scratch/alamo-results
zph add 'output*'
zph sync /scratch/alamo-results
zph watch /scratch/run-0042 --pid 38192
zph run --directory /scratch/run-0043 -- alamo input
```

`zph add` accepts one or more directories, metadata files, or wildcard patterns,
then recursively discovers every Alamo `metadata` file beneath the matches. It
imports the associated metadata, `thermo.dat`, `out.log`, `diff.patch`, and
final status. Running watchers refresh the captured terminal output alongside
the heartbeat. Shell-expanded
wildcards (`zph add output*`) and quoted patterns (`zph add 'output*'`) both
work. Its summary distinguishes newly added records from existing records that
were updated. Color is enabled for interactive terminals and disabled when
output is piped or `NO_COLOR` is set. Numbered BoxLib data trees ending in
`cell` or `node` are pruned from recursive discovery before they are entered.
Discovery also stops beneath a run's `metadata` file and skips Alamo
source/vendor trees, virtual environments, VCS data, and package caches. Bulk
registration uses a single catalog lookup and up to four concurrent syncs.

`zph sync PATH...` recursively discovers every Alamo copy beneath the supplied
paths, including multiple directories with the same HASH. Unlike the fast
discovery pass used by `zph add`, it inventories filenames throughout each run,
including BoxLib trees. The default scan avoids per-file stat calls and reuses
an incremental cache in `~/.config/zephyr/sync-cache.json` when directory
timestamps show that filenames have not changed. Zephyr records the absolute
path, storage site and host, file count, a path fingerprint, and whether numbered
`cell` or `node` data is present. It does not upload the raw dataset. Use
`zph sync --deep PATH` when a full byte total and size/mtime fingerprint are
needed. Moving a copy creates a new known location; the previous location is
retained with its last update time. Set `ZEPHYR_SITE` to give shared cluster
storage a stable name when `SLURM_CLUSTER_NAME` is unavailable.

Upload and restore results:

```console
zph put '*.png' 'profiles/*.csv'
zph put output/myfile.png
zph list --status running
zph compare HASH_A HASH_B
zph get output.481516
```

By default, `zph put` associates each file with the `metadata` file in that
file's directory. Files from several output directories can be supplied in one
command and are grouped by run automatically. Use `--directory RUN_DIRECTORY`
to explicitly associate every target with a single run instead.

`zph get` accepts an output-directory name, HASH, or Zephyr UID. It restores to
the original output-directory name by default. If that name identifies several
runs, an interactive terminal displays their HASH, UID, status, host or cluster,
and update time and asks which one to use. If the local destination already
exists, `zph` offers to use the next available name, choose another path, merge
and overwrite conflicting files, or cancel. For scripts, use `--output PATH`,
`--rename`, or `--overwrite` to make the collision policy explicit.
Successful `zph get`, `zph put`, and `zph sync` operations refresh the local
copy inventory and its last-update action.

`ZEPHYR_SERVER` and `ZEPHYR_TOKEN` override the credential file for jobs and
CI. Locally, the `HASH` in Alamo's `metadata` file is the complete run identity;
Zephyr does not add a marker file to simulation directories, and credentials
never live there.

Alamo authenticates `zph` as part of configuration, then starts the watcher only
for simulations given the boolean `--post` flag:

```console
./configure --zephyr https://zephyr.solids.group
alamo --post input
```

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
Artifact transfers are disabled locally by default; set the three
`ZEPHYR_ARTIFACT_STORE` and `ZEPHYR_GOOGLE_DRIVE_*` variables to use a
dedicated development folder when exercising `zph put` and `zph get`.

Run all checks with:

```console
make test
make lint
npm --prefix web run build
```

## Architecture and operations

See [architecture](docs/architecture.md),
[Alamo integration](docs/alamo-integration.md), and
[Render deployment](docs/deployment.md). The OpenAPI document is served at
`/docs` and protocol compatibility is advertised by `/api/v1/meta`.

Zephyr is intentionally not a scientific postprocessor. Alamo or a user's
workflow creates scientific tables and images; Zephyr indexes, visualizes,
compares, shares, and preserves those outputs.

Google Drive is the collaboration layer for selected working artifacts, not a
replacement for long-term archival storage of large raw simulation datasets.

## Status

Zephyr is alpha software. Database migrations and protocol compatibility are
maintained from the first hosted deployment, but operational backups must be
configured before the service is treated as the definitive archive.

Licensed under the [MIT License](LICENSE).
