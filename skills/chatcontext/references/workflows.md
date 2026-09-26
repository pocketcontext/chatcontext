# Workflows

In commands below, `cc` means `python3 /absolute/path/to/installed/chatcontext/scripts/cc.py`.

## Identity

Set `CHATCONTEXT_URL=https://chat.pocketcontext.com` to the actual operator-provided origin and `CHATCONTEXT_USER_EMAIL=your-address`. The hostname is a candidate until deployment is configured. HTTPS is required except on loopback for local tests. Credentials are scoped to URL and email in private `XDG_CACHE_HOME/chatcontext` files (or `~/.cache/chatcontext`).

- Team: `cc login --google`. Open the printed Google URL. For SSH, forward localhost port 8765; the CLI shows the command. Only verified Workspace claims admit new team members.
- Visitor: `cc login --email` prints an `otpId` and emails a code. Then run `cc login --email --otp-id ID`; enter the code at the hidden prompt. Code expiry is ten minutes, single-use, with failed-attempt limits. Requesting another code invalidates the previous one. Do not put codes in command arguments, shell history or documents.
- Provisioned AI account: supply `CHATCONTEXT_USER_PASSWORD` privately, then `cc login --password`. Such accounts are provisioned by an administrator, not this client.
- `cc whoami` checks identity. `cc logout` removes only the local session, not sessions on other devices. Sessions last seven days; active email/Google clients refresh them. Revoked/disabled sessions need operator resolution and fresh login.

The client does not retain Google provider tokens. It refuses redirects to avoid forwarding credentials and validates the returned ordinary-user identity against the configured email.

## Read and synchronize

`cc schema`, `cc check`, `cc query 'SELECT ...'`, and `cc get messages ID` use authenticated SQL. Filtering includes conversation membership, support ownership, internal notes, protected metadata, private inbox, receipts and audit. Do not infer global absence from a filtered result.

`cc sync --after 0 --limit 100` returns ordered `changes`, `next_cursor` and `page_full`. For each event, re-query the affected record via SQL; deletions retain tombstones with ordinary body cleared. Apply each page before durably storing its cursor, then request the next page. A full page can mean more results remain; fetch until a short/empty page. On errors or truncated results, do not advance. Processing a page must tolerate duplicates after a crash.

Sync is a notification index, not a data export. Membership expansion requires fetching accessible history; revocation requires discarding inaccessible local rows/files. Clients must periodically revalidate their entire cache against current visibility, including on reconnect and membership changes. An inaccessible conversation may no longer emit visible events, so an empty page never proves cached access remains valid. Prefer querying server data on demand over retaining persistent private caches.

`cc inbox` lists the latest 100 mentions/replies; use SQL pagination for older entries. `cc unread` counts unread messages in subscribed channels, DMs and support, excluding own authored messages. `cc ack ID [ID ...]` explicitly acknowledges up to 20 messages in one transaction; it does not implicitly acknowledge a thread's other messages. Existing receipts are skipped. A concurrent duplicate acknowledgement may require re-reading then retrying.

## Conversations and messages

- `cc channel 'Engineering'` creates a public channel. Add `--private --participants ACCOUNT ...` for a private channel. Creator is included. Public visibility does not require subscribing.
- `cc dm 'Release discussion' --participants ACCOUNT ...` creates a one-to-one or group DM including self. Membership is fixed; create another DM for a different group.
- `cc support 'Installation issue'` creates a visitor's own support conversation. Team members pass `--visitor ACCOUNT` to start one with an existing visitor.
- `cc send CONVERSATION 'Markdown text'` posts a root message; `cc reply CONVERSATION ROOT 'Reply'` posts a thread reply. `--mention ACCOUNT` may repeat. Use `-` for body text from stdin.
- `cc note CONVERSATION 'Private team note'` posts a support internal note. Replies inherit the root's visibility. Visitors cannot access notes, their attachments or receipts.
- `cc edit MESSAGE 'Updated text' --revision N` edits your own message. `cc delete MESSAGE --revision N` soft-deletes it; ordinary body/mentions are cleared and originals remain in authorized audit history. Neither command permanently erases data.
- `cc create reactions '{"message":"MESSAGE_ID","emoji":"👍","active":true}'` reacts; update the returned reaction with `active:false` and its `expected_revision` to withdraw it.

Generic `create COLLECTION JSON` and `update COLLECTION ID JSON` cover memberships, reactions and conversation state. JSON may be `-` for stdin. Updates require `expected_revision`. The server sets authorship; do not impersonate another account. `cc batch JSON` allows up to 20 POST/PATCH business writes in a transaction; a rejected batch saves none. Use `cc newid` for caller-chosen IDs when a batch needs cross-references. On uncertain transport outcomes inspect those IDs before retrying.

## Support and membership

Any team account can reply to support, optionally assign/reassign it to one team account, and resolve/reopen it. Assignment indicates responsibility and never grants exclusive permission. Update a conversation with `{"assignee":"ACCOUNT_ID","expected_revision":N}` or `{"status":"resolved","expected_revision":N}`. A new visitor message reopens automatically; internal notes do not.

Visitors see the author's explicitly configured public alias (default `User`) with company label “PocketContext”. Team members set their own with `cc display-name 'Alias'` (empty resets to `User`); `whoami` shows it. Visitors cannot choose an alias; emails and internal names are not a public directory. Visitors can mention only visible team authors from their conversation. They cannot invite others or browse team conversations.

Create a membership using conversation/account and `active:true`; update `active` with the current revision to leave/remove/rejoin. Team members manage public membership; current private-channel members manage its membership. New members see full history; leaving/removal revokes private access. Archive a channel with `{"archived":true,"expected_revision":N}` to preserve readable history while stopping new messages.

## Protected attachments

`cc upload MESSAGE /path/to/file` attaches an immutable original to your own nondeleted message (1 byte–25 MiB). Upload and server SHA-256 must agree. `cc download ATTACHMENT /private/path/file` reads metadata through SQL, obtains a short-lived protected file token, verifies SHA-256, and exclusively creates a mode-0600 output; it will not overwrite. Download only when requested or needed for the authorized work. Attachments inherit message visibility, including internal-note and deletion restrictions.

No reply-notification email, AI orchestration, automatic external messaging or browser frontend is supplied by this skill. Email is for sign-in only. Live updates are optional; SQL is the main read path.
