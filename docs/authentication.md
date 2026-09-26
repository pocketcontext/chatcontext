# Identity and account administration

All clients use PocketBase's default `users` collection. Authentication grants an account session; a separate source-only `team_members` record grants team authority. Visitor accounts never receive team access from their email domain alone.

## Visitor email sign-in

1. `POST /api/collections/users/request-otp` with `{"email":"visitor@example.test"}` returns `{"otpId":"..."}` and sends an eight-digit email code.
2. `POST /api/collections/users/auth-with-otp` with `{"otpId":"...","password":"12345678"}` exchanges the code for the standard PocketBase `{token, record}` response.
3. `POST /api/collections/users/auth-refresh` renews an active session. Application tokens last seven days.

Codes expire after ten minutes, can be consumed once, and are replaced by a new request. Each challenge permits at most five attempts; PocketBase also throttles attempts per account. Issuance has a per-IP limit. Successful consumption is serialized to prevent two concurrent exchanges from both succeeding. Attempt counters are private, excluded from SQL, and removed when PocketBase deletes the corresponding OTP.

First issuance creates an unverified identity shell with a generated unknown password and the public label `Visitor`. It has no application access until the email code is proven. Public direct account creation remains blocked. Case variants resolve to the same email identity. A disabled account receives no code. Email delivery requires configured SMTP; no support reply notifications are sent in version one.

## Workspace and autonomous clients

Google sign-in requires server-verified email and exact trusted Workspace claims. Set `CHATCONTEXT_GOOGLE_WORKSPACE_DOMAIN=pocketcontext.com` and a dedicated Google OAuth client. First trusted admission creates or upgrades the ordinary account and grants non-administrator team membership. Client `createData` cannot choose privileged fields. Explicit membership management consumes that admission too: a later Google login never restores revoked team access.

Administrators provision autonomous clients as ordinary users with their own passwords and explicit team membership. Personal assistants may use the person's session. Stored authorship and receipts identify the account, not proof that a person read a message.

## Administrator maintenance

An operator bootstraps the first verified administrator through the PocketBase dashboard or superuser REST API: create a user, then create `team_members` with its `account` ID and `is_admin: true`. No real account is seeded.

Ordinary administrators can use these maintenance REST operations:

- Create `users` with `email`, public `name`, `password`, and `passwordConfirm`. Created clients are verified by the administrator.
- Patch an existing user with `disabled` only. Administrators cannot take over an existing identity by changing its password, email, verification state, or public name.
- List/view `team_members` to discover membership IDs; create membership with `account` and `is_admin`; patch `is_admin`; delete membership to revoke team authority.

The `team_members` REST reads are an administrator-only maintenance exception to the application's SQL-first read model. The collection remains unavailable through SQL. Other users cannot enumerate it. Auth record reads remain restricted to the account itself; the public directory exposes only ID and display name.

The last active administrator cannot remove or demote their own final administrative membership or disable their account. Disabling an account rotates its token key: old API, refresh and file tokens remain revoked even if it is re-enabled. Account deletion is blocked to preserve authorship. Revoking team membership is applied to the next SQL snapshot and each REST/file authorization check. Administrator status never bypasses private-conversation membership.

The operator remains a trusted maintenance authority with database backup access. Operational permanent erasure and credential recovery require that authority; the ordinary administrator API does not provide impersonation.
