# Webhook Delivery and Troubleshooting

Last updated: 2026-09-11
Owner: Platform Engineering
Applies to: REST API v2, all plans

## Overview

NimbusDesk sends webhooks when events occur in a workspace, for example `ticket.created`, `ticket.updated`, `comment.created`, `sla.breached`, and `member.deactivated`.

Webhooks are configured in Settings → Developer → Webhooks. Each endpoint has:

- A destination URL (HTTPS only; HTTP is rejected in production)
- A signing secret (`whsec_...`) generated at creation
- An event subscription list
- An enabled/disabled toggle
- A delivery log with the last 30 days of attempts

## Request format

```http
POST /your-endpoint HTTP/1.1
Content-Type: application/json
User-Agent: NimbusDesk-Webhooks/2.0
X-Nimbus-Event: ticket.created
X-Nimbus-Delivery: dliv_01J8Z4Q3M9
X-Nimbus-Signature: t=1731091200,v1=6f3a9c...
```

Payloads are JSON with a top-level `event`, `workspace_id`, `occurred_at`, and `data` object. Payloads are limited to 256 KB. Events with larger payloads are truncated and include `"truncated": true`; fetch the full object from the API using the ID in `data`.

## Verifying the signature

The signature is computed over the raw request body:

```
signed_payload = f"{timestamp}.{raw_body}"
expected = HMAC_SHA256(signing_secret, signed_payload)  # hex
```

Compare using a constant-time comparison. Accept the request only if:

1. `v1` matches the computed signature, and
2. `abs(now - timestamp) <= 300` seconds.

Compute the HMAC over the raw bytes exactly as received. Parsing JSON and re-serializing changes whitespace and key order and produces a different signature — this is the single most common integration bug.

## Delivery and retries

| Attempt | Delay after failure |
| --- | --- |
| 1 | Immediate |
| 2 | 30 seconds |
| 3 | 2 minutes |
| 4 | 10 minutes |
| 5 | 30 minutes |
| 6 | 2 hours |
| 7 | 6 hours |
| 8 | 24 hours |

A delivery is considered successful only for a 2xx response within 10 seconds. Redirects (3xx) are treated as failures. The endpoint is automatically disabled after 8 consecutive failed deliveries or if a URL fails verification at creation.

Failed events are available in the delivery log for 30 days and can be replayed manually or via `POST /v2/webhooks/{id}/deliveries/{delivery_id}/replay`.

## Common failure modes

### 401/403 from the receiving endpoint
The endpoint expects its own authentication in addition to the NimbusDesk signature. NimbusDesk does not send customer credentials. Use the signature header for verification instead of an additional shared secret.

### Timeout (10 seconds)
The receiving endpoint is doing synchronous work. Acknowledge with 2xx immediately and process asynchronously with a queue.

### Duplicate events
Delivery is at-least-once. The same `X-Nimbus-Delivery` ID can arrive more than once, especially after retries. Store delivery IDs and deduplicate before processing.

### Events out of order
Webhooks are not ordered. Use `occurred_at` plus the object's `version` field, and fetch the current object from the API when ordering matters.

### TLS handshake failure
The endpoint certificate chain is incomplete, expired, or uses an RSA key shorter than 2048 bits. NimbusDesk requires TLS 1.2 or later and a complete chain. Self-signed certificates are not supported in production; use the sandbox for local testing with a tunnel.

### Endpoint disabled
Automatic disablement happens after 8 consecutive failures. Re-enable the endpoint after fixing the receiver. Replays are not automatic after re-enabling.

## Local development

Use a tunneling tool to expose a local server over HTTPS, or point the webhook to the sandbox with a test workspace. Never place the signing secret in client-side code.

## Escalation guidance

Escalate to Platform Engineering when:

- Signatures fail for all deliveries after the secret was rotated correctly
- The delivery log shows successful attempts but the customer's server never receives requests
- Events are missing for more than 15 minutes while the workspace is otherwise healthy

Collect: webhook ID, delivery ID, event type, `occurred_at` in UTC, destination hostname, and the response status and first 500 characters of the response body. Never ask for the signing secret; the customer can rotate it themselves.
