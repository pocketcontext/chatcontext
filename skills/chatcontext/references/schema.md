# SQL and write contract

`schema.json` is the tested SQL projection. Run `cc.py schema` for the live contract and `check` to compare it. Auth records, team-role authority and counters are not exported. No SQL mutation is supported. All source rows are filtered for the authenticated account before query execution.

| Table | Key fields and purpose |
|---|---|
| conversations | kind (`public_channel`, `private_channel`, `dm`, `support`), title, visitor, assignee, status, archived, revision; creation accepts extra `participants` account array |
| memberships | conversation, account, active, revision; channel subscriptions/access, fixed DM members |
| messages | conversation, parent (root message), body, internal, deleted, mentions JSON, author, revision |
| attachments | message, original (protected filename), sha256, author, revision; immutable originals |
| reactions | message, account, emoji, active, revision; unique account/message/emoji |
| read_receipts | message, account; explicit immutable acknowledgement, unique account/message |
| inbox | account, message, reason (`mention`, `reply`), created; server-managed |
| changes | seq, collection, record, conversation, message, internal, action, created; monotonic cursor and no message content |
| audit_log | collection, record, conversation, message, internal, actor, action, changes JSON, created; administrators with conversation access only |
| user_directory | id, name; public display labels only, no emails; visitor projection includes self and visible support authors |

Business updates require extra `expected_revision` from the last SQL read. Do not write attribution, audit, inbox or change records. No administrator privacy bypass. Writes use `/api/collections/COLLECTION/records` POST or PATCH `/ID`; batches use `/api/batch`. File uploads are multipart POSTs to attachments; protected originals use `/api/files/attachments/ID/FILENAME` with a short-lived file token.

Messages max 20,000 characters; Markdown is text, not executable HTML. Thread parents must be roots in the same conversation; replies inherit internal-note visibility. Only authors edit/delete messages. Deleted messages hide body and mentions from ordinary reads and hide attachments. Read receipt visibility is self-only in channels; other participants may see DM/support receipts, subject to message visibility. Inbox entries remain visible only while their referenced message is accessible and nondeleted.
