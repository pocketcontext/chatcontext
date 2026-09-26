# Deployment and recovery

ChatContext is deployed at `https://chat.pocketcontext.com`; see [the production deployment record](../DEPLOYMENT.md) for exact image digests, verified checks and remaining verification. The separate website chat UI is outside the application image. The repository and `ghcr.io/pocketcontext/chatcontext` image are public; anonymous manifest/configuration/layer access was verified independently of repository visibility. Future deployments still require authorization and verification of their own provider settings.

The image pins PocketContext, base-image digests and Litestream release checksums. It serves port 80 with database-backed `/up`, stores all state under `/storage/pb_data`, enables rate limits, and uses tini for signal forwarding. The Docker build context denies new files by default. Only synthetic test data belongs in CI.

## Required configuration

Configure a separate Internal Google Web client for `pocketcontext.com`, with redirects `http://127.0.0.1:8765/callback` and `https://chat.pocketcontext.com/api/oauth2-redirect`. Supply `CHATCONTEXT_GOOGLE_CLIENT_ID`, `CHATCONTEXT_GOOGLE_CLIENT_SECRET` and `CHATCONTEXT_GOOGLE_WORKSPACE_DOMAIN=pocketcontext.com`. The first two must be supplied together. Verified Workspace login grants ordinary team membership, never administrator access.

Use an explicitly provisioned operator identity via paired `CHATCONTEXT_SUPERUSER_EMAIL` and `CHATCONTEXT_SUPERUSER_PASSWORD`; provision initial team administrator authority separately through the operator API. Never use operator credentials in the skill. Automated clients use ordinary users accounts.

ONCE supplies `BASE_URL`, `SMTP_ADDRESS`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` and `MAILER_FROM_ADDRESS`. SMTP must be tested before enabling visitor sign-in; email is only for authentication in version one. Set `CHATCONTEXT_TRUSTED_PROXY_HEADER=X-Forwarded-For`. `CHATCONTEXT_RATE_LIMITS=true` is the image default. If the website lives at another origin, explicitly configure `CHATCONTEXT_BROWSER_ORIGINS` with the comma-separated exact HTTPS app and website origins. Default CORS is `BASE_URL` only. Never use wildcard origins for production.

Use a dedicated private `chatcontext-backup` bucket with unique `LITESTREAM_PATH=once-pocketcontext/chatcontext`, `LITESTREAM_REGION=auto`, the verified jurisdiction-specific `LITESTREAM_ENDPOINT`, and narrowly scoped `LITESTREAM_ACCESS_KEY_ID`/`LITESTREAM_SECRET_ACCESS_KEY`. Bucket creation and DNS changes require separate deployment authorization. Do not reuse another application's replica.

For future scaffold provisioning, place app-specific parameter variables in `/home/jack/code/pocketcontext/once-pocketcontext/.envrc.private`, using `COLORS_PAR_APP_CHATCONTEXT_` names corresponding to the settings above, including Google, operator and Litestream credentials. Keep that file unversioned, mode 0600; preserve existing entries and never print values. No credentials are generated or copied by this repository. Read the scaffold README and the create-context-app deployment guide before changing it.

## Complete attachment recovery

Litestream alone cannot restore attachments. `docker/backup.py` takes an online SQLite backup, reads exactly its immutable `attachments.original` references, and verifies each recorded SHA-256 while copying the files. A checksummed archive includes the database and originals; the remote latest pointer changes only after upload succeeds. Message soft deletion does not remove originals from backups. Do not physically erase originals during an online snapshot.

The first snapshot starts after five seconds and subsequent snapshots run at most hourly (`CHATCONTEXT_BACKUP_INTERVAL`, 1–3600 seconds). A clean shutdown creates a final snapshot. A failed snapshot stops the supervised writer rather than silently losing the backup guarantee. Initial engineering targets are hourly recoverable snapshots and recovery within two hours for a small deployment; actual capacity must be monitored. Backup archives and database settings contain private content and credentials and remain private indefinitely until an explicit retention/erasure policy is approved.

Startup prefers an existing local database and verifies its originals. On an empty volume it restores a complete snapshot before considering Litestream. An inaccessible/corrupt remote or missing/corrupt original fails closed. A Litestream-only database with attachment references but no files cannot start. A complete snapshot is a consistent recovery point and may precede later database-only replication; do not combine newer database state with older originals. `LITESTREAM_DISABLED=true` is for disposable testing only.

Recovery drills use a separate destination and isolated replica, never another writer against the live production replica. Run `tests/backup.py`, `tests/backup_integration.py`, and the container restore gate. Keep originals immutable; any permanent-erasure maintenance must coordinate retained snapshots and stop the writer.

## Release and updates

Application, identity, client, skill, deployment and complete-backup tests gate image publication. Container configuration, smoke, and destructive synthetic-volume restore checks also gate publication. Native AMD64 and ARM64 images receive immutable source tags and a manifest digest. Record the tested source revision and initial deployed image digest.

Deploy only through the dedicated locked graceful-stop wrapper in `deploy/`. Automatic ONCE updates must be disabled. The wrapper has one fixed app target, verifies exactly one existing container, pulls, stops cleanly, and updates with `--auto-update=false`. Recovery restarts the old container only if it remains the sole matching container. Apply environment changes under the same lock and no-overlap discipline.

CI deployment requires both `CHATCONTEXT_DEPLOY_ENABLED=true` and a nonempty `COLORS_PROFILE` repository variable. Leave the explicit app switch unset until separately authorized provisioning, verified TLS/SMTP/OAuth, recovery testing, and installation of the dedicated restricted SSH key/wrapper. The environment needs `SSH_PRIVATE_KEY`, `SERVER_IP`, `SERVER_USER`, and trusted `SSH_KNOWN_HOSTS`. No first-deployment bootstrap targeting real infrastructure is included.
