# Authorization and synchronization

SQL uses requester-filtered snapshots with explicit columns. Auth records, roles, OTP attempt counters and change-number allocation remain source-only. PocketBase rules do not filter SQL; each exported collection has a separate filter. The filter predicates use current source membership from one coherent snapshot. Limits fail closed rather than returning incomplete exports.

| Resource | Team member | External visitor |
| --- | --- | --- |
| Public channel | Read; membership subscribes unread tracking | None |
| Private channel / DM | Active member only, including admins | None |
| Support | All team members | Own conversation only |
| Internal note and related data | Team with conversation access | None |
| Public directory | Public labels of team/visitor accounts | Self and nondeleted public-message authors in own support |
| Read receipts | Own; others only for accessible DM/support messages | Own; others for accessible support messages |
| Inbox | Own accessible nondeleted messages | Own accessible nondeleted messages |
| Audit | Admin AND conversation access | None |

Directory labels come only from the explicit `users.public_display_name`, falling back to `User`. They never fall back to account names, Google names or email addresses. Team members can deliberately publish their own alias, and administrators and operators any alias; visitors cannot choose one; SQL still exposes only `id` and `name`. Existing directory labels are scrubbed by the forward migration.

Ordinary business REST lists/views and record realtime are locked, including relation expansion. SQL is the supported read API. Protected file downloads have a protected-file-only view rule and a second server hook validating the file-token identity, current account status, current conversation access, note visibility and message deletion. Header bearer identity cannot confer rights on a different file token. Original bytes never change. Uploaded Markdown/HTML/files are data: browser clients must render Markdown safely, avoid executable HTML, and treat arbitrary attachments as downloads rather than injecting them into the application origin.

Ordinary updates require current revision. Server attribution, revisions, transactional history, change sequences, initial memberships, notifications and support reopening cannot be supplied by clients. Private-channel membership and team role checks run inside write transactions; REST authorization is independent from SQL filtering. Generated side effects roll back on validation/history failure. Role management is administrative maintenance through source-only REST, not ordinary messaging SQL. Administrators cannot set an existing account's credentials to impersonate its private conversations. Operators are trusted maintenance identities; their database access is not a confidentiality boundary.

## Polling and receipts

Read changes with `seq > last_cursor ORDER BY seq LIMIT ...`. Advance only after processing a complete page; a filtered page advances to its last returned sequence. Events contain identifiers and actions, no historical body text. Fetch current records through SQL. Soft-deleted message tombstones remain visible with empty body/mentions; attachments and inbox entries for that message disappear. Existing thread replies remain separate records and can still be edited after root deletion; new replies to a deleted root are rejected.

Visibility may contract or expand independently of an event cursor. A revoked client cannot see its own removal event. Clients must revalidate cached conversation IDs against their current authorized conversation list, discard inaccessible cached records/files, and fetch current history for newly visible conversations. A cursor alone is not a complete permission synchronization protocol. Local retained downloads cannot be remotely erased; clients must honor revocation and protect their own storage.

Read receipts are immutable per account/message and must be explicitly written. They do not generate shared change/audit events, because that would expose private channel read activity. Query receipts directly through filtered SQL. Receipt state does not reset on edits; changes still report the new revision. This is acknowledgement of the message, not proof that every revision was reviewed. Root receipts do not apply to replies. Inbox remains a retained event list; join receipts to show unread items.

## Resource and retention boundaries

A file is limited to 25 MiB and message body to 20,000 characters. Request throttling and snapshot row/byte/time budgets bound individual operations. This release does not implement a company-wide storage quota, malware scanning or a spam classifier; operators must monitor storage/capacity and apply an explicit upload/retention policy before exposing an unrestricted production service. Backups contain credentials and private message/audit/file data and require private storage.

Soft deletion is the normal user action. Permanent erasure requires operator maintenance: stop the writer, inventory message/audit/file references and retained snapshots, take any authorized legal retention decision, use a reviewed maintenance procedure, verify a fresh complete backup and restart. No generic destructive purge command is exposed to clients.
