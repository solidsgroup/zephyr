# Render deployment

`render.yaml` defines a Docker web service and managed PostgreSQL database in
Render's Ohio region. Render deploys every push to `master`, runs Alembic before
traffic moves to the new image, and checks `/healthz`.

The pre-deploy phase invokes the zero-argument `zephyr-migrate` package entry
point. Keep this as a single command token: it calls Alembic programmatically so
Docker command parsing cannot drop the migration revision arguments.

The initial deployment is intentionally sized as one always-on Starter web
service plus a Basic-256mb PostgreSQL instance with a 1 GB disk. Database
storage autoscaling is disabled so that the monthly cost cannot grow without an
intentional configuration change. Increase the database compute plan and disk
size only after measurements show that Zephyr needs them; Render cannot shrink
an existing PostgreSQL disk.

## One-time setup

1. Create a Render Blueprint from `solidsgroup/zephyr`.
2. Create Google OAuth web credentials. Add
   `https://zephyr.solids.group/api/v1/auth/callback/google` as an authorized
   redirect URI and configure the consent screen for the group.
3. Enable the Google Drive API in the Zephyr Google Cloud project and create a
   `zephyr-artifacts` service account with a JSON key.
4. Create a `Zephyr Artifacts` folder in a group-owned Shared Drive. Add the
   service account's email as a Content manager and copy the folder ID from its
   browser URL.
5. Fill the unsynchronized Google secrets in Render. Store the entire service
   account key JSON in `ZEPHYR_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`, and store the
   folder ID in `ZEPHYR_GOOGLE_DRIVE_FOLDER_ID`.
6. Point the `zephyr.solids.group` DNS record as Render instructs and verify the
   custom domain certificate.
7. Enable PostgreSQL recovery and establish separate archival deposition for
   large datasets before treating Zephyr as a definitive archive.

The service needs no persistent Render disk. Uploads travel directly from `zph`
to a resumable Google Drive session. Downloads are streamed through Zephyr using
short-lived signed links so private and public project access remains governed
by Zephyr rather than Drive sharing settings.

## Operational checks

- `/healthz` returns the server version without authentication.
- `/api/v1/meta` describes client compatibility and capabilities.
- a smoke run can log in, create a CLI token, `zph import`, post a heartbeat,
  upload an image, and download the restored run.
- migration and restore exercises should run before any schema release.

Secrets are intentionally not present in `render.yaml` or `.env.example`.
