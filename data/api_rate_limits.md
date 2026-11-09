# API Rate Limits and Throttling

Last updated: 2026-08-02
Owner: Platform Engineering
Applies to: REST API v2

## Default limits by plan

Limits are enforced per workspace and per minute unless stated otherwise.

| Plan | Sustained requests/min | Burst (10s window) | Concurrent exports |
| --- | --- | --- | --- |
| Starter | 60 | 20 | 1 |
| Growth | 300 | 100 | 3 |
| Scale | 1,200 | 400 | 8 |
| Enterprise | Contractual (default 3,000) | 1,000 | 16 |

Sandbox (`nk_test_`) keys are limited to 60 requests/min on every plan so that load tests do not affect production.

## Rate limit response

When a limit is exceeded the API returns HTTP `429` with error code `rate_limit_exceeded`:

```http
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 300
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1731091260
Retry-After: 7
Content-Type: application/json

{"error":{"code":"rate_limit_exceeded","message":"Workspace rate limit exceeded","retry_after_seconds":7}}
```

`X-RateLimit-Reset` is a Unix timestamp in seconds (UTC). `Retry-After` is the recommended wait before retrying the same request.

## Recommended client behavior

1. Read `Retry-After` and wait at least that long.
2. Apply exponential backoff with jitter when no header is returned: `min(2^attempt, 60) + random(0, 1)` seconds.
3. Cap retries at 5 attempts.
4. Do not retry non-idempotent POST requests blindly — use the `Idempotency-Key` header so a retried create does not produce duplicate tickets.
5. Spread bulk work over time rather than retrying in a tight loop. A client that ignores `Retry-After` may have its key temporarily suspended for 10 minutes after 100 consecutive 429 responses.

## Bulk and list endpoints

- List endpoints return at most 100 records per page, controlled by `limit` (max 100) and `cursor`.
- `GET /v2/tickets` with a `since` parameter counts toward normal limits.
- Bulk export endpoints (`/v2/exports`) are limited separately: 10 export jobs per workspace per hour. Export jobs run asynchronously and do not count against request-per-minute limits once accepted.

## Webhooks are not affected

Outbound webhook deliveries are not subject to inbound API rate limits. Retry behavior for webhooks is documented in `webhooks_troubleshooting.md`.

## Diagnosing unexpected 429 responses

Common causes:

1. **Polling loops** — dashboards that poll every few seconds. Move to webhooks or a 60-second interval.
2. **Retry storms** — a client retrying immediately without honoring `Retry-After`.
3. **Shared keys** — multiple services using one API key, so their traffic adds up against one workspace limit.
4. **Burst-heavy imports** — importing 10,000 records as individual creates. Use the bulk import endpoint instead.
5. **Plan change not applied** — after a downgrade, the lower limit applies at the next billing cycle boundary, not immediately.

## Requesting a limit increase

Enterprise workspaces can request an increase through their Customer Success Manager. Scale workspaces can open a ticket with expected peak requests/min, endpoint mix, and the business justification. Increases are applied per workspace and usually take effect within two business days.

## Support escalation guidance

If a customer reports sustained `429` responses while their observed request rate is below their plan limit, collect: workspace ID, key ID suffix, time window in UTC, endpoint, and three sample response headers. Escalate to Platform Engineering for edge log review. Do not promise a limit increase from the support tier; increases are approved by the plan owner listed above.
