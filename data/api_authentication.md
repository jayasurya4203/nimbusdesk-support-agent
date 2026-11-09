# NimbusDesk API Authentication

Last updated: 2026-09-18
Owner: Platform Engineering
Applies to: REST API v2 (base URL `https://api.nimbusdesk.io/v2`)

## Overview

NimbusDesk uses bearer token authentication for all REST API requests. Every request must include an `Authorization` header with a workspace API key or an OAuth 2.0 access token. Requests without a valid token are rejected with HTTP 401 before any business logic runs.

API keys are created in **Settings → Developer → API Keys** by workspace Owners and Admins. A workspace can hold up to 25 active keys.

## Key formats

| Prefix | Environment | Notes |
| --- | --- | --- |
| `nk_live_` | Production | Full access to production data |
| `nk_test_` | Sandbox | Sandbox data only; no billing effects |

Keys are shown in full exactly once at creation. NimbusDesk stores only a SHA-256 hash, so a lost key cannot be recovered — rotate it instead.

## Required headers

```http
POST /v2/tickets HTTP/1.1
Host: api.nimbusdesk.io
Authorization: Bearer nk_live_9f2c...a71b
Content-Type: application/json
X-Nimbus-Workspace: ws_48213
```

- `Authorization` — required on every request.
- `X-Nimbus-Workspace` — required when a user belongs to more than one workspace.
- `Content-Type: application/json` — required for POST/PATCH bodies.

## Common authentication errors

### 401 `invalid_token`
The key does not exist, was deleted, or belongs to a different environment (for example a `nk_test_` key sent to `api.nimbusdesk.io`).
**Resolution:** confirm the prefix matches the environment, then verify the key ID in Settings → Developer → API Keys. Compare the last four characters of the key ID; do not paste the secret into logs or tickets.

### 401 `token_expired`
OAuth access tokens expire after 60 minutes. Static API keys do not expire, but keys flagged for rotation expire at the rotation deadline.
**Resolution:** refresh the access token using the refresh token grant, or rotate the API key.

### 401 `clock_skew`
OAuth requests signed with a JWT are rejected when the `iat` claim is more than 300 seconds away from NimbusDesk server time.
**Resolution:** sync the calling host with NTP (`timedatectl status` or `w32tm /query /status`). Do not compensate by adding seconds to `iat`.

### 403 `insufficient_scope`
The token is valid but lacks the scope required by the endpoint. For example, `tickets:write` is required to create tickets, and `admin:keys` is required to manage API keys.
**Resolution:** inspect `GET /v2/me/scopes` to see the effective scope list, then re-issue the token with the missing scope. OAuth apps must request scopes at authorization time; scopes cannot be added to an existing access token.

### 403 `ip_not_allowed`
The workspace has an IP allowlist enabled and the request came from an address outside it.
**Resolution:** add the egress IP in Settings → Security → API Access, or call the API through an approved gateway. Allow up to 5 minutes for the allowlist to propagate to all edge locations.

## Token rotation

1. Create the replacement key in Settings → Developer → API Keys.
2. Deploy the new key to your secret manager and restart consumers.
3. Watch the **API Keys → Last used** column until the old key shows no traffic for 24 hours.
4. Revoke the old key. Revocation is immediate at the edge; in-flight requests with a revoked key fail with `invalid_token`.

Rotation does not invalidate OAuth refresh tokens. To revoke those, use `POST /v2/oauth/revoke` or remove the connected app.

## OAuth 2.0 authorization code flow

- Authorize URL: `https://app.nimbusdesk.io/oauth/authorize`
- Token URL: `https://api.nimbusdesk.io/v2/oauth/token`
- Supported grants: `authorization_code`, `refresh_token`
- PKCE: required for public clients (`S256`)
- Redirect URIs: must be registered exactly, including scheme and trailing slash

Access tokens are bearer tokens and must never be embedded in browser JavaScript. Use the backend-for-frontend pattern.

## Service accounts

Service accounts are non-human identities that own API keys independently of a person. When an employee leaves, their personal keys are revoked, but service account keys continue to work. Best practice is to use one service account per integration so usage can be attributed and revoked independently.

Service accounts cannot sign in to the web app and cannot be granted the `billing:manage` scope.

## Security guidance

- Store keys in a secrets manager, never in source control or front-end code.
- Use separate keys per environment and per integration.
- Do not send API keys in query strings; they are recorded by proxies and appear in access logs.
- Rotate keys immediately if a key is exposed in a public repository or log.

## Escalation notes

Support cannot reveal, regenerate, or email an existing API key. If a customer reports that a key leaks or that authentication fails after a rotation with no configuration change, collect the workspace ID, key ID (last four characters only), request timestamp in UTC, and the full `401` response body, then escalate to Platform Engineering. Never ask the customer to share the full secret.
