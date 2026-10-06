# Initial release — 26 September 2026

Historical evidence only. The old deployment is now retired. Current release and
deployment controls are documented in [the common contract](ci-and-deployment.md),
and current container recovery is documented in [deployment](deployment.md).

Application source: `8c724d17ed85ebcbe4f562f5f6aab971ea31a3d5`.
PocketContext server: `381f81042586afdaa6498b8c0e2a78229a55bdff`.
Shared workspace registration: `6a7d311`.

The repository `pocketcontext/chatcontext` is public. The GHCR package is public independently of source visibility. The container supports Linux AMD64 and ARM64, and production deployment remains disabled unless explicitly enabled and configured.

Image index: `sha256:1923f117c32828cd5a4b03828982de9ffbb537b0fdd40caad8f6c36669c51860`.

- AMD64: `sha256:599cf5ee6b23a59adba86be4a2337cc5c089a66087ae6f6faa23701598d66633`.
- ARM64: `sha256:9593e73e21c36cbabb50dac9afd025bc197425094102ade2773876f272e362f5`.

Both image configurations identify the application source above. This release record is a documentation-only follow-up; it does not alter the published application.

All twelve local suites passed: messaging integration, adversarial authorization, realtime SSE, email OTP/account administration, Google OAuth integration, copied portable skill, deployment settings, complete database/attachment recovery, client utilities, OAuth client, backup utilities and deployment orchestration. Tests use synthetic records, local SMTP/provider fixtures and disposable storage. The pinned server was built with Go 1.27.1, CGO and sqlite_math_functions.

Final-source [application CI](https://github.com/pocketcontext/chatcontext/actions/runs/36224251306) passed. Final-source [container CI](https://github.com/pocketcontext/chatcontext/actions/runs/36224251389) passed configuration, smoke and isolated destructive-volume restore before image publication. The restore gate verifies original attachment bytes as well as database recovery and graceful final replication. Real SSE positive controls prove locked ordinary domain subscriptions do not leak private messages or internal notes.

Anonymous verification passed for the final image: it reads the multiarchitecture index, both platform manifests and configurations, and checks successful access to every layer without user credentials. A package's public visibility is not inferred from the repository setting. Docker is unavailable on the local workstation; actual container startup/restore checks run in GitHub Actions.

No production instance, DNS record, Google client, bucket, SMTP configuration, website interface or real accounts were provisioned. Real Google browser sign-in, external email delivery and measured production recovery remain deployment checks. Hourly complete snapshots and two-hour recovery are engineering targets, not observed production guarantees.
