# Security policy

Zephyr is currently alpha software. Report security issues privately to the
Solid Mechanics Research Group rather than opening a public issue. Rotate any
credential included in logs or issue text immediately.

Production deployments must use HTTPS, restricted Google OIDC credentials,
independent high-entropy session and token secrets, a bucket-scoped object-store
token, managed database backups, and `ZEPHYR_DEV_AUTH=false`.
