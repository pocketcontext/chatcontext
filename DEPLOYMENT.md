# ChatContext deployment

Deployed on 26 September 2026 at https://chat.pocketcontext.com through the existing ONCE host. The API has no frontend or embedded AI. Conversations start empty; the first team administrator was provisioned through maintenance REST.

| Item | Verified value |
| --- | --- |
| Public repository | https://github.com/pocketcontext/chatcontext |
| Tested application source | `8c724d17ed85ebcbe4f562f5f6aab971ea31a3d5` |
| PocketContext pin | `381f81042586afdaa6498b8c0e2a78229a55bdff` |
| Public image | `ghcr.io/pocketcontext/chatcontext:latest` |
| Multiarchitecture image digest | `sha256:1923f117c32828cd5a4b03828982de9ffbb537b0fdd40caad8f6c36669c51860` |
| ARM64 platform manifest | `sha256:9593e73e21c36cbabb50dac9afd025bc197425094102ade2773876f272e362f5` |
| AMD64 platform manifest | `sha256:599cf5ee6b23a59adba86be4a2337cc5c089a66087ae6f6faa23701598d66633` |
| Application CI | [36224251306](https://github.com/pocketcontext/chatcontext/actions/runs/36224251306) — passed |
| Image CI | [36224251389](https://github.com/pocketcontext/chatcontext/actions/runs/36224251389) — passed |
| Production resources | ARM64, one CPU, 512 MiB, persistent `/storage`, one writer, automatic updates disabled |
| Backup | Dedicated private `chatcontext-backup` bucket; prefix `once-pocketcontext/chatcontext` |

## Release and live checks

Application, security, realtime, identity, skill/client, deployment and complete-backup tests passed. Native AMD64/ARM64 image publication passed container configuration, smoke and complete attachment restore gates. Anonymous access to the index, platform manifests, configurations and layers was verified. See [release evidence](docs/release.md).

Scaffold build/dry-run passed. A targeted DNS plan added only the proxied ChatContext A record on the existing host and preserved previous DNS state. No full compute/SMTP convergence occurred. All 11 baseline containers remained running with the same IDs. Existing deployment keys were preserved; the resulting 13-key set contains exactly one restricted ChatContext key.

Public HTTPS health, operator authentication, the default `users` identity collection, ordinary password login and token refresh, authenticated schema/filtered SQL, and anonymous schema/SQL denial checks passed. The live SQL schema matches the portable skill reference columns and types. No business conversation was seeded. Resource limits, persistent storage, image identity, a single writer and disabled automatic updates were verified.

Google Workspace JIT is configured for verified `pocketcontext.com` identities. The dedicated Google Web client is separate from sibling clients. The user confirmed Internal audience and both redirects: `http://127.0.0.1:8765/callback` and `https://chat.pocketcontext.com/api/oauth2-redirect`. **A real Google browser login remains unverified.** Configuration and synthetic OAuth tests do not establish end-to-end human sign-in.

Existing ONCE SMTP settings were reused. SMTP TLS and authentication passed without sending a message. **Live email-code delivery remains unverified.** Email is used for authentication only; visitor sign-in should be accepted only after its delivery check.

## Backups and recovery

Dedicated R2 head/write/read/list/delete probes passed; the temporary probe was removed. The endpoint matches the other applications, with a separate bucket and prefix. The user confirmed public access is disabled for both r2.dev and custom domains. The available provider credential could not independently inspect those console settings.

Nonempty database replicas, a complete snapshot archive and its latest-complete pointer were verified. An isolated drill restored the real complete snapshot from R2, verified its contents, and started a disposable loopback server with replication disabled. Restore and validation took **1.2 seconds**. Ordinary login, SQL/schema access and administrator authority passed, with the exact account and membership IDs preserved. Temporary restored storage was removed; no second writer used the production replica.

This was an empty-launch recovery of the initial database and identity configuration, not a populated-production attachment benchmark. Synthetic populated attachment recovery passed the native container CI gates.

Complete snapshots run shortly after startup, hourly by default, and on graceful shutdown. Monitor the latest successful complete pointer and upload age. Litestream alone cannot recover attachment bytes; use one consistent complete snapshot rather than combining a newer database with older originals. Follow [recovery instructions](docs/deployment.md). A drill must use isolated storage with replication disabled, never a second writer against the production replica.

## Deployment control

A dedicated restricted SSH key invokes the root-owned `/usr/local/sbin/deploy-chatcontext` wrapper. The fixed-target wrapper locks, pulls, gracefully stops the sole current writer, verifies clean exit, and updates only ChatContext with automatic updates disabled. A controlled update through the restricted key passed in 4.2 seconds, including pull, graceful stop and replacement. The final backup completed within the 60-second stop budget. Post-update checks passed with the same administrator account and membership IDs, without reprovisioning.

GitHub environment `once-pocketcontext` holds the dedicated SSH secret and trusted host identity. `COLORS_PROFILE=once-pocketcontext` is configured; **`CHATCONTEXT_DEPLOY_ENABLED=false` keeps CI deployment disabled pending verification.** Registry credentials supplied by CI exist only in temporary private Docker configuration; the image also supports anonymous pulls. Reinstall the wrapper after scaffold convergence rewrites authorized keys.

Operator, Google and R2 credentials and the key reference remain in the scaffold's ignored mode-0600 `.envrc.private` under `COLORS_PAR_APP_CHATCONTEXT_*`. Never print full ONCE labels, environments, authentication responses or private backup contents.

## Rollback

Acquire `/run/lock/deploy-chatcontext.lock`, stop the sole writer gracefully, and preserve its volume. Choose a tested earlier image only after checking schema compatibility. For incompatible changes, restore a selected complete backup into isolated storage, verify it, and choose a deliberate replica strategy before switching traffic. Never attach a restored writer to the active production replica. The normal fixed-target wrapper updates `latest`; it is not a general rollback interface. Repeat health, identity/access, attachment, image and sibling checks after recovery.
