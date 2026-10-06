# Deployment and recovery

The old ChatContext deployment is retired. This source change does not recreate it.
See [CI and deployment lifecycle](ci-and-deployment.md) for common release controls.
Historical deployment records are not current provisioning instructions.

## Runtime configuration

The image serves port 80 with database-backed `/up`, uses tini and a single Python
entrypoint, and stores SQLite state in `/storage/pb_data`. It requires all five
`CHATCONTEXT_S3_` settings: `BUCKET`, `ENDPOINT`, `REGION`, `ACCESS_KEY_ID`,
`SECRET_ACCESS_KEY`. `FORCE_PATH_STYLE` is `true` by default. Litestream separately
requires `LITESTREAM_BUCKET`, `LITESTREAM_PATH`, `LITESTREAM_ACCESS_KEY_ID` and
`LITESTREAM_SECRET_ACCESS_KEY`; configure endpoint and region for the provider.
Primary files and replicas must use different buckets and access keys. Private
objects must remain available for as long as retained database replicas reference them.
`LITESTREAM_DISABLED` is unsupported. No archive supervisor runs in this image.

Supply paired `CHATCONTEXT_GOOGLE_CLIENT_ID` / `CHATCONTEXT_GOOGLE_CLIENT_SECRET`
and the exact `CHATCONTEXT_GOOGLE_WORKSPACE_DOMAIN` for verified Workspace JIT.
Optional paired `CHATCONTEXT_SUPERUSER_EMAIL` / `CHATCONTEXT_SUPERUSER_PASSWORD`
are maintenance credentials, never ordinary client credentials. Set `BASE_URL`
and the ordinary SMTP environment for authentication email. Keep secrets outside
Git and logs. Replica credentials and operator passwords are removed from the
server process environment. App authorization remains unchanged.

## Initialization and recovery

Run the image's `init` command once with an empty volume and empty replica. It
refuses an existing replica and records incomplete initialization durably. Then
start the default command using the same volume and configuration. Ordinary startup
requires a local database or a recoverable replica, never silently initializes.

A restored database is staged outside the active directory. SQLite integrity,
all file-field references (including auth avatars), and original SHA-256 checks
must pass before atomic installation. Missing/corrupt objects fail closed and leave
no installed database. Existing databases also verify files before serving.
Litestream synchronizes through private IPC before HTTP is accepted. Graceful
shutdown stops the single writer and synchronizes its replica. Asynchronous
replication does not guarantee zero data loss on crashes.

Frozen handoffs require the private `maintenance.json` marker, main database and
consistent `auxiliary.db`; startup refuses storage changes or missing auxiliary
state, skips provisioning, and leaves explicit thaw to the operator. Fence the old
writer before starting a replacement. Never test against production replicas.

`docker/backup.py` and its tests remain for offline legacy archive compatibility;
they are excluded from the image. New runtime recovery uses primary objects plus
the Litestream replica exclusively. Local server development may still use local
files; it is not the container storage contract.

## Validation

Run the README application/auth/client/maintenance suites and `tests/entrypoint.py`.
Build the image and run `docker/smoke.py config`, `smoke`, and `restore` with
`--image IMAGE`. The populated restore gate provisions isolated MinIO buckets and
scoped synthetic credentials, checks protected downloads, freezes/restarts,
compares all database tables, destroys source volumes and tests automatic recovery.
It also rejects absent replicas and reinitialization of an existing replica.
No live data, cloud resources or deployment access is needed for these gates.

`CHATCONTEXT_BROWSER_ORIGINS` may explicitly allow a separate website client;
otherwise CORS permits only `BASE_URL`. SMTP must be verified before visitor OTP.
