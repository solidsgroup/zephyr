# Architecture

Zephyr is a monorepo with hard package boundaries:

```text
Alamo / zph
      │  HTTPS JSON + resumable artifact uploads
      ▼
FastAPI service ───────── React dashboard
      │                         │
      ├── PostgreSQL catalog    └── same-origin session
      └── Google Shared Drive
```

The API process is stateless. PostgreSQL is the authoritative catalog for
users, runs, projects, provenance, telemetry indexes, and artifact manifests.
Selected working artifact bytes are immutable and content-addressed by SHA-256
in a group-owned Google Shared Drive. A run artifact is a versioned logical path
pointing to one of those files, so duplicate uploads cost no extra storage.
Drive file IDs are implementation details and are never used as run identity.

## Run identity and state

Every run has a server UUID for database relationships and internal API routes.
That UUID is an implementation detail: locally and in the CLI, Alamo's `HASH`
is the run identifier and idempotency key. It is read from `metadata`; Zephyr
does not write a separate identity marker into the simulation directory.
Heartbeat sequence numbers are monotonic, so retries and out-of-order messages
cannot move a run backwards. A `starting` or `running` run whose heartbeat is
more than two minutes old is displayed as `unreachable` without destroying its
last declared state.

`metadata` is stored both verbatim and as normalized key/value and section
indexes. `thermo.dat` is split into immutable-schema segments when a header
changes or the local file is truncated. Sequence numbers make append retries
idempotent.

Copy locations are append-preserving catalog records keyed by run, storage
site, and absolute path. `zph get`, `zph put`, and `zph sync` refresh a record's
last update time and local inventory. Normal syncs use a path-only digest and a
user-level directory timestamp cache to avoid per-file metadata calls. An
explicit deep sync additionally records total size and fingerprints file sizes
and mtimes. Copy-location updates are committed through a bulk endpoint without
placing the file manifest or raw BoxLib data in Zephyr. Moving a directory
therefore records its new location without silently erasing the last-known
location of the old copy.

## Security boundary

Browser users authenticate through Google OIDC and must present a verified
hosted-domain claim for `solids.group`. Browser mutations additionally require
a session CSRF token. CLI login uses a ten-minute device authorization with
separate browser-approval and terminal-polling secrets. Approval creates a
random API token that is returned once, stored as an HMAC-SHA256 digest,
individually revocable, and never placed in run directories.

Runs are private to their owner unless attached to a project. Private projects
use explicit memberships, group projects are readable by authenticated group
members, and public projects expose a deliberately separate read-only API.
Artifact downloads use short-lived Zephyr-signed URLs. Zephyr streams the bytes
from Drive so Drive membership and credentials are never exposed to clients.

## Data lifecycle

Working records remain until their owner explicitly deletes them. A run deletion
removes its catalog, telemetry, and artifact links; unreferenced immutable Drive
files remain quarantined for a future garbage-collection policy. Drive is for
images, logs, inputs, checkpoints, and modest result bundles that benefit from
collaboration. Large raw datasets and definitive archival copies remain outside
Zephyr until retention, deposition, and recovery semantics are agreed upon.
