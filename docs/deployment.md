# Render deployment

`render.yaml` defines a Docker web service and managed PostgreSQL database in
Render's Ohio region. Render deploys every push to `master`, runs Alembic before
traffic moves to the new image, and checks `/healthz`.

## One-time setup

1. Create a Render Blueprint from `solidsgroup/zephyr`.
2. Create Google OAuth web credentials. Add
   `https://zephyr.solids.group/api/v1/auth/callback/google` as an authorized
   redirect URI and configure the consent screen for the group.
3. Create a private Cloudflare R2 bucket and an API token scoped only to that
   bucket.
4. Fill the unsynchronized `ZEPHYR_GOOGLE_*` and `ZEPHYR_S3_*` secrets in
   Render. The R2 endpoint is
   `https://ACCOUNT_ID.r2.cloudflarestorage.com`; the region remains `auto`.
5. Point the `zephyr.solids.group` DNS record as Render instructs and verify the
   custom domain certificate.
6. Enable PostgreSQL recovery/backup options and R2 object versioning before
   treating Zephyr as an archive.

The service needs no persistent Render disk. Uploaded bytes travel directly
between clients and R2 with short-lived signed URLs; the web process only
verifies object headers and writes manifests.

## Operational checks

- `/healthz` returns the server version without authentication.
- `/api/v1/meta` describes client compatibility and capabilities.
- a smoke run can log in, create a CLI token, `zph import`, post a heartbeat,
  upload an image, and download the restored run.
- migration and restore exercises should run before any schema release.

Secrets are intentionally not present in `render.yaml` or `.env.example`.
