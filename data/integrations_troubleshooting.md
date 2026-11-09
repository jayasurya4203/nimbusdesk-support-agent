# Integration Troubleshooting Guide

Last updated: 2026-09-02
Owner: Integrations Team
Applies to: Slack, Microsoft Teams, Jira Cloud, Salesforce, HubSpot, and Zapier connectors

## General diagnostic order

1. Confirm the connector status in Settings → Integrations. Each card shows **Connected**, **Needs attention**, or **Disconnected**.
2. Check the connector's last sync time and error count. Open the connector's log drawer for the last 50 events.
3. Confirm the connected user still has permission in both systems. Most connector failures are authorization failures caused by a departed employee or a changed role.
4. Re-authorize the connection, which refreshes OAuth tokens without deleting configuration.
5. If the error persists, collect the connector ID and the error code from the log drawer.

## Slack integration

### `slack_channel_not_found`
The channel was archived, renamed, or the NimbusDesk app was removed from it.
**Fix:** invite the app again with `/invite @NimbusDesk` in the channel, then click **Resend test notification** in the connector settings.

### Messages post but links 404
The connected Slack user cannot access the ticket. NimbusDesk does not bypass permissions. Grant the user access to the workspace or reconnect with a user who can view the ticket.

### `slack_invalid_auth`
The OAuth token was revoked (for example after a Slack workspace admin removed the app).
**Fix:** click **Reconnect** in Settings → Integrations → Slack and approve the requested scopes. Required scopes: `channels:read`, `chat:write`, `commands`, `users:read`.

## Microsoft Teams

- Teams connectors are approved per tenant. A tenant admin must consent to the NimbusDesk app before a member can connect.
- If the connector shows `tenant_consent_required`, ask the Microsoft 365 admin to approve the app in the Entra ID admin center.
- Personal chat notifications require the user to have the NimbusDesk app installed in Teams.

## Jira Cloud

### `jira_project_not_found`
The Jira project key changed or the connected account lost browse permission.

### `jira_field_required`
A required Jira field is not mapped. Open Settings → Integrations → Jira → Field mapping and map the required field. Jira's required fields vary by project and issue type.

### `jira_issue_type_invalid`
The mapped issue type was removed or renamed in Jira. Choose an existing issue type.

### Sync delay after link creation
The first sync of a new Jira link can take up to 10 minutes. Status changes in Jira are polled every 2 minutes (Growth) or streamed in near real time (Scale and Enterprise).

## Salesforce

- Salesforce connectors require API access enabled for the connected user's profile.
- `salesforce_api_disabled` means the profile lacks "API Enabled". A Salesforce admin must enable it.
- Field-level security can silently drop synced values. If NimbusDesk shows a value that Salesforce does not, check the field-level security for the integration user.
- Sandbox orgs require a separate connection; production credentials do not work against sandboxes.

## Zapier

- Zap runs fail with `401` when the NimbusDesk connection in Zapier was revoked. Reconnect the NimbusDesk app in Zapier.
- Zapier polls the API. On Starter plans, polling can contribute to rate limits; reduce trigger frequency or switch to webhooks on supported triggers.
- Test triggers do not appear instantly if no event has occurred in 15 minutes. Create a ticket to generate a sample event.

## Connector health best practices

- Use a dedicated integration user, not a personal account, so offboarding does not break automations.
- Keep the integration user's role stable; changing from Admin to Agent can revoke access to configuration objects.
- Review the connector log weekly for repeated retries.
- Set a workspace Owner as a backup owner of critical connectors.

## When to escalate

Escalate to the Integrations Team if:

- Re-authorization succeeds but sync still fails with a 5xx from NimbusDesk
- Multiple connectors fail at the same time with different error codes
- A connector loops between Connected and Needs attention more than three times per hour

Include connector ID, connector type, affected object IDs, error code, timestamps in UTC, and whether a re-authorization was attempted. Do not include OAuth tokens or client secrets in the ticket.
