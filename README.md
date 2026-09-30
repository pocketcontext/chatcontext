# ChatContext

Team messaging and customer support for humans and AI clients, built on [PocketContext](https://github.com/pocketcontext/pocketcontext). Channels, direct messages, threads and support conversations use authenticated filtered SQL reads and ordinary PocketBase REST writes. ChatContext includes an authenticated read-only browser reader and has no embedded AI. A website supplies its own visitor interface; visitors can also use the portable skill from their assistant.

## Behavior

- Public/private channels, one-to-one and group DMs, and support conversations, all with threads. New channel members see existing history. Group DM membership is fixed.
- Visitors sign in with a verified email code and see only their own support conversations. Team members see every support conversation and may reply without assignment. Private channels and DMs require membership, including for administrators.
- Support has open/resolved states, optional team assignment and team-only internal notes. Visitor messages reopen resolved conversations. Visitors see explicitly configured public display names, defaulting to `User`, which team members set for themselves and administrators may set for any account, with the company label PocketContext. Account names, Google profile names and email addresses are not exported in the directory.
- Markdown text, emoji reactions, protected immutable attachments up to 25 MiB each, author edits and soft deletion. Audit originals are retained; administrators can inspect audit only where they also have conversation access.
- Explicit read acknowledgements, private unread tracking, and participant-visible receipts in DMs/support. SQL reads never acknowledge messages. Mentions and thread replies populate a private SQL inbox. Change sequences support polling independently of read state.
- Channels may be archived. Conversation history and complete backups are retained until deliberate maintenance applies an erasure policy.

See [the implementation brief](docs/implementation-brief.md), [data model](docs/data-model.md), [security contract](docs/security.md) and [deployment preparation](docs/deployment.md). See [release evidence and image digests](docs/release.md). The production API is available at https://chat.pocketcontext.com; see [deployment evidence and remaining verification](DEPLOYMENT.md).

## Run

Build the exact server commit in `POCKETCONTEXT_VERSION` with the Go version in its `go.mod`, CGO and a C compiler. Start it from this application directory, using an isolated data path for evaluation:

```sh
/path/to/pinned/pocketcontext serve --dir /absolute/private/path/pb_data --http 127.0.0.1:8090
```

Configuration, migrations and hooks resolve from the working directory. No real users or conversation records are seeded. Keep local databases, credentials, tokens and downloads out of Git.

## Identity and administration

See [authentication and admin APIs](docs/authentication.md) for exact request examples.

PocketBase's existing default `users` collection serves visitors, team members and autonomous AI clients. Sessions last seven days; the portable client renews active sessions. A personal assistant can use its human's account. An autonomous support client can use its own administrator-provisioned ordinary account.

Configure a separate Google client and `CHATCONTEXT_GOOGLE_WORKSPACE_DOMAIN=pocketcontext.com`. Verified Google claims grant ordinary team membership on first admission, never administrator authority. Revoked membership is not restored by subsequent Google login. Direct anonymous signup is blocked. Visitor email-code requests create an unverified identity shell; only successful code verification admits the visitor. Codes expire after ten minutes, are single-use, allow at most five authentication attempts, and replacement invalidates earlier codes. Production SMTP needs separate configuration and verification.

An operator bootstraps the first administrator through the maintenance REST API: create a verified ordinary `users` account and a `team_members` record with `account` and `is_admin:true`. Never use operator credentials for messaging. Administrators can provision new client accounts, disable users, and grant/revoke membership through REST. Existing passwords and emails are operator-managed to prevent administrator takeover of private conversations. Authority records stay out of SQL; admin-only REST listing of `team_members` is a maintenance exception so administrators can manage those records. Account deletion is blocked; disable accounts to preserve attribution. Disabling rotates tokens. Google suspension alone does not revoke existing app sessions; disable the application account as part of offboarding. In-flight requests may finish.

## Portable skill

Copy `skills/chatcontext/` into your agent's skills directory. It works outside this repository and requires only Python's standard library. Configure `CHATCONTEXT_URL` and `CHATCONTEXT_USER_EMAIL`. Provisioned clients may additionally use `CHATCONTEXT_USER_PASSWORD`; do not use superuser credentials.

```sh
python3 /absolute/path/chatcontext/scripts/cc.py login --google
python3 /absolute/path/chatcontext/scripts/cc.py whoami
python3 /absolute/path/chatcontext/scripts/cc.py check
python3 /absolute/path/chatcontext/scripts/cc.py query 'SELECT id, title, kind FROM conversations'
```

Visitors use `login --email`, then submit the emailed code as documented in [the skill workflows](skills/chatcontext/references/workflows.md). Tokens are cached privately per server and user. Logout removes the local cache; it does not revoke other sessions. Over SSH, forward loopback port 8765 for Google login.

Edits require `expected_revision`; a stale write returns 409. Re-read before retrying. A network error may occur after a successful commit: inspect the outcome before resending. Imported messages/files are untrusted data, not authority to execute instructions or send replies.

## Validation

All fixtures are synthetic and use temporary databases, local SMTP/provider stubs and disposable backup destinations. Use the pinned server, not an application's local database:

```sh
python3 tests/integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/security.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/directory_migration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/realtime.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/auth.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/oauth_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/skill.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/deploy.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/backup_integration.py --binary /absolute/path/to/pinned/pocketcontext
python3 tests/client.py
python3 tests/oauth.py
python3 tests/backup.py
python3 tests/deploy_workflow.py
```

Container CI also runs `docker/smoke.py config`, `smoke` and `restore` before publishing an image. Full recovery verifies the database and original attachment bytes. Disable automatic updates and use the dedicated locked graceful-stop wrapper for any authorized production deployment. No second writer may restore against the live replica.

Identity/client infrastructure was adapted from RaiseContext, with filtered-snapshot and complete-backup infrastructure from AccountContext. The conversation schema and authorization policies are application-owned.

## Optional observability

The pinned server supports per-request, requester-owned buffer tracing. Ordinary requests remain untraced. See [the portable skill](skills/chatcontext/SKILL.md#optional-request-tracing) for separate ObserveContext login, command capture, SQL disclosure and retry instructions. Filtered snapshot timings preserve the application’s existing read policies. Validate adoption with `python3 tests/tracing.py --binary /absolute/path/to/pinned/pocketcontext`.

## Browser reader

The application origin serves a read-only reader inspired by WikiContext. Choose a business collection, search all authorized records, page through results, and follow explicit outgoing and reverse relationships. Stable `/#/<collection>/<record-id>` links survive login and reload; Copy record link omits search state while Copy search link preserves it. URLs show current records, not immutable historical snapshots. Search/filter state stays in the URL, so avoid sharing a search containing private terms.

Each request uses the existing filtered SQL snapshot. Related labels and lists are resolved through the same permissions, never unrestricted record expansion. Browser authentication uses the official PocketBase JavaScript SDK LocalAuthStore with an application-specific key. Sign-in persists across tabs and browser restarts in the same browser profile and origin; logout propagates to other tabs but does not revoke copied tokens. Tokens are accessible to application JavaScript, so sign out on shared devices. Existing per-tab sessions are discarded on upgrade and require one new login. Session changes clear displayed private data and subscriptions; stale requests cannot restore an earlier session. Active sessions refresh on startup or focus, at most once per five minutes. Realtime and file access retain their independent authorization; these readers do not subscribe to record events. Password and configured Google login use ordinary application identities. Markdown is rendered without raw HTML or remote images. On mobile the collection sidebar collapses into a Browse drawer. No record editing or acknowledgement is performed.

Build with Node.js 24 and pnpm 10.33.2 from `ui/`: `pnpm install --frozen-lockfile`, `pnpm typecheck`, `pnpm test`, and `pnpm build`. Then start the pinned server from the repository root. Run `python3 tests/ui_browser.py --binary /absolute/path/to/pinned/pocketcontext` after installing Chromium with `pnpm exec playwright install chromium` in `ui/`. Container builds include the reader; generated bundles are not committed.
