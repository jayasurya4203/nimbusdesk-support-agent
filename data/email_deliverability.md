# Email Notification and Deliverability Guide

Last updated: 2026-08-16
Owner: Messaging Platform
Applies to: All plans

## Emails NimbusDesk sends

- Password reset and email verification
- Invitations to join a workspace
- Ticket assignment and mention notifications
- SLA warning and breach notifications
- Invoice and payment failure notices
- Security alerts (new device sign-in, MFA changes, API key created)

Emails are sent from `notifications@nimbusdesk.io`. Password reset and security emails are sent from `security@nimbusdesk.io`. Both domains use SPF, DKIM, and DMARC. NimbusDesk does not use a shared third-party marketing domain for transactional mail.

## Why a notification may not arrive

1. **Notification preferences** — each member can disable email notifications under Profile → Notifications. Workspace Admins can set defaults but cannot override an individual's unsubscribe.
2. **Spam or quarantine** — corporate filters often quarantine the first message from a new sender. Ask the customer to search quarantine for `nimbusdesk.io` and allowlist the domain.
3. **Distribution group** — invitations sent to a group address are often dropped. Invite the individual address.
4. **Typo or alias** — confirm the exact invited email. Invitations expire after 7 days; the inviter can resend from Settings → Members → Pending invitations.
5. **Suppression list** — a hard bounce or a spam complaint suppresses the address. Suppression is permanent until the address owner confirms opt-in. Support cannot remove a suppression without Messaging Platform approval.
6. **Rate limiting** — a member can trigger at most 5 invitation emails per hour and 3 password reset emails per hour. Additional requests are silently dropped to prevent abuse.

## Deliverability checks

Ask the customer's IT team to confirm:

- SPF and DKIM pass for `nimbusdesk.io`
- DMARC alignment is not overridden by a restrictive internal policy
- The sending IP ranges are not blocked (published at `https://trust.nimbusdesk.io/sending-ips`)
- The message is not being rewritten by a link-scanning gateway in a way that breaks the reset link

Reset links are single-use and expire after 30 minutes. A link-scanning gateway that pre-fetches links can consume the token before the user clicks it; in that case the user sees "This link is no longer valid". This is a common false alarm. Ask IT to allowlist the link-scanning exception for `*.nimbusdesk.io`.

## Password reset emails specifically

- Only send a reset to the email on the member profile. Support cannot send a reset to an alternate address.
- Reset emails are not sent for SSO-enforced members; they must reset through their identity provider.
- If three resets are requested within an hour, further requests are dropped. Wait 60 minutes.
- If the member no longer has access to the email, the workspace Owner must update the member email first. Identity verification is required and the case is account-sensitive.

## Invitations

- Invitations expire after 7 days.
- A pending invitation can be resent from Settings → Members.
- If the invitee already has a NimbusDesk account under a different email, the invitation will create a separate member. Merge is not supported; the Owner should invite the existing address.

## Support boundaries

Support may:

- Confirm that a notification was queued (the email log shows queued/sent/delivered/bounced status).
- Resend an invitation if the customer is an Admin.
- Explain suppression, rate limits, and expiry windows.
- Recommend allowlisting domains and IPs.

Support may not:

- Change a member's email address.
- Remove a suppression without Messaging Platform approval.
- Reveal whether an arbitrary email address has a NimbusDesk account (privacy).
- Send password reset links manually.

## Escalation

Escalate to Messaging Platform when:

- Multiple recipients in a verified domain report missing emails while the email log shows delivered
- A password reset link is consumed by a security scanner and the user is locked out repeatedly
- A suppression must be removed after the address owner confirms opt-in
- Invoice emails are missing for a Billing Admin with notifications enabled

Include: workspace ID, recipient domain (not the full address if it contains personal data), email type, timestamps in UTC, message IDs from the email log, and the sending IP if available.
