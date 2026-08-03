# Architecture

Zephyr is a monorepo with hard package boundaries:

```text
ALAMO / zph
      │  HTTPS JSON + presigned object transfers
      ▼
FastAPI service ───────── React dashboard
      │                         │
      ├── PostgreSQL catalog    └── same-origin session
      └── S3-compatible object storage
```

The API process is stateless. PostgreSQL is the authoritative catalog for
users, runs, projects, provenance, telemetry indexes, and artifact manifests.
Object bytes are immutable and content-addressed by SHA-256 in Cloudflare R2
(MinIO locally). A run artifact is a versioned logical path pointing to one of
those objects, so duplicate uploads cost no extra storage.

## Run identity and state

Every run has a server UUID. ALAMO's `HASH`, when available, is a searchable
alias and an idempotency key per owner; it is not the canonical identifier.
Heartbeat sequence numbers are monotonic, so retries and out-of-order messages
cannot move a run backwards. A `starting` or `running` run whose heartbeat is
more than two minutes old is displayed as `unreachable` without destroying its
last declared state.

`metadata` is stored both verbatim and as normalized key/value and section
indexes. `thermo.dat` is split into immutable-schema segments when a header
changes or the local file is truncated. Sequence numbers make append retries
idempotent.

## Security boundary

Browser users authenticate through Google OIDC and must present a verified
hosted-domain claim for `solids.group`. Browser mutations additionally require
a session CSRF token. CLI/API tokens are random, shown once, stored as an
HMAC-SHA256 digest, individually revocable, and never placed in run directories.

Runs are private to their owner unless attached to a project. Private projects
use explicit memberships, group projects are readable by authenticated group
members, and public projects expose a deliberately separate read-only API.
Object downloads remain short-lived presigned URLs.

## Data lifecycle

Working records remain until their owner explicitly deletes them. A run deletion
removes its catalog, telemetry, and artifact links; unreferenced immutable object
bytes remain quarantined for a future garbage-collection policy. External archival
deposition is deliberately deferred until retention and recovery semantics are
agreed upon. Before production archival claims are made, enable
Render PostgreSQL point-in-time recovery and R2 object versioning/lifecycle
controls, then test restoration on a schedule.
