# Agreed application brief

ChatContext replaces agent-operated team messaging and supplies customer-support conversations for a separately implemented website chat client. AI behavior lives in ordinary clients, not inside the server. The initial organization is PocketContext; the trusted Google Workspace domain is pocketcontext.com.

## Accepted scope

Channels (public/private), fixed-membership one-to-one/group DMs, support conversations and root-message threads. Visitors use either a browser or portable skill and see only their own support conversations. Team members can create/manage channels; only private-channel members manage that channel's membership. New channel members read all history. Leaving/removal revokes private-channel access immediately. All team members can see/reply to support without assignment. Any team member may set a single optional assignee, with recorded history. Support owners are individual visitors; there is no guest invitation or multi-visitor support in v1.

Support opens, resolves and reopens; a new visitor message reopens automatically, internal notes do not. Team-only notes and their threads/attachments cannot leak to visitors. Visitors may open multiple conversations; team members may start one for an existing visitor. Replies show public author name plus PocketContext, preserving actual authorship internally.

Messages support Markdown text, emoji reactions and 25 MiB immutable protected attachments. Authors edit and soft-delete their own messages; retained original audit content is visible only to administrators who also have conversation access. Administrators do not bypass private-channel or DM membership. Channel archiving stops new messages and preserves history. Permanent erasure is deliberate maintenance covering stored originals and backups, not the ordinary delete action.

SQL is the primary read path for historical and new messages; REST handles mutations. Monotonic filtered change events represent edits/deletions as well as creation. Fetching does not mark read. Read acknowledgement means the account's human or agent presented or deliberately handled the message, not proof of human review. Background fetch leaves unread unchanged; autonomous clients may acknowledge after processing. Private read tracking applies everywhere, shared receipts only in DMs/support, no delivered state. Thread root acknowledgement does not acknowledge replies. Mentions and thread replies populate a personal inbox. Visitors mention only team authors already publicly participating in that support conversation.

## Recommended operational choices adopted

- Existing default users collection for every identity. Seven-day renewable app sessions. Email OTP expires in ten minutes, one use, replacement invalidation, five attempts; no anonymous direct signup.
- Verified Google Workspace first admission grants ordinary team membership. Administrator-only role and disabling controls. No automatic admin grants. Initial administrator explicitly provisioned by operator; no invented personal identity.
- Autonomous AI clients have named ordinary team identities; personal assistants may act under human identities. Public display labels are distinct from emails.
- Private repository pocketcontext/chatcontext initially; image ghcr.io/pocketcontext/chatcontext. Future origin https://chat.pocketcontext.com, separate Google client and dedicated private chatcontext-backup bucket/prefix.
- Hourly complete database/original-file backups and a two-hour recovery engineering target for initial small deployment. Retention indefinite until explicit maintenance policy.
- No external email replies/notifications in v1: only authentication email. No frontend, AI orchestration, production provisioning, Slack/WhatsApp import, E2E encryption, voice/video, or typing/presence implementation. Ordinary REST reads/realtime are deliberately locked; optional live updates are deferred while SQL polling remains the supported consumption path.

## Acceptance

Tests must prove visitor isolation, no administrator privacy bypass, internal-note and file isolation, current-membership filtering across SQL aggregates/joins and changes, protected-file revocation, per-account receipt visibility, inbox privacy, immutable originals, revision conflicts, transactional audit/inbox/change writes and rollback. Identity tests cover verified Workspace claims, unverified visitors, email-code expiry/replay/replacement/attempt exhaustion, first admission versus revoked membership, disabled-session rejection and last-administrator protection. Client tests run a copied skill outside the repository. Container config/smoke/restore gates protect publication. Real Google browser sign-in and external SMTP delivery remain deployment checks.

## Infrastructure evidence

Donor revisions inspected: AccountContext 2b78c0f38680381376b0ce485312ff659037a13f; RaiseContext 44f8f10537388f9a934a2bc1800d3df6a046c580. Server pin: 381f81042586afdaa6498b8c0e2a78229a55bdff. Selected tracked infrastructure only; no donor databases, credentials or deployment targets copied. Source publication is authorized; cloud resources and production deployment require a separate deployment task.
